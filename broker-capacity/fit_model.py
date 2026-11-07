"""Fit small capacity models on declared training cases, score untouched tests.

Uses only the standard library. Nonnegative least squares is solved exactly
over all active sets (at most four columns), with scaled normal equations.
"""
import argparse
import itertools
import json
import math
from pathlib import Path
import statistics


def solve(matrix,rhs):
    n=len(rhs)
    rows=[list(row)+[b] for row,b in zip(matrix,rhs)]
    for j in range(n):
        pivot=max(range(j,n),key=lambda k:abs(rows[k][j]))
        if abs(rows[pivot][j])<1e-11:return None
        rows[j],rows[pivot]=rows[pivot],rows[j]
        z=rows[j][j]
        rows[j]=[x/z for x in rows[j]]
        for k in range(n):
            if k==j:continue
            z=rows[k][j]
            rows[k]=[a-z*b for a,b in zip(rows[k],rows[j])]
    return [row[-1] for row in rows]


def nnls(x,y):
    n=len(x[0])
    scale=[max(abs(row[j]) for row in x) or 1 for j in range(n)]
    xs=[[v/s for v,s in zip(row,scale)] for row in x]
    best=[0.0]*n
    best_loss=sum(v*v for v in y)
    for bits in itertools.product([False,True],repeat=n):
        cols=[j for j,b in enumerate(bits) if b]
        if not cols:continue
        gram=[[sum(row[i]*row[j] for row in xs) for j in cols] for i in cols]
        rhs=[sum(row[j]*v for row,v in zip(xs,y)) for j in cols]
        solution=solve(gram,rhs)
        if solution is None or min(solution)<-1e-8:continue
        coef=[0.0]*n
        for j,v in zip(cols,solution):coef[j]=max(0,v)
        loss=sum((sum(a*b for a,b in zip(row,coef))-v)**2 for row,v in zip(xs,y))
        if loss<best_loss:
            best_loss=loss;best=[v/s for v,s in zip(coef,scale)]
    return best,best_loss


def dot(x,y):return sum(a*b for a,b in zip(x,y))


def fit_roofline(sizes,demands):
    """Global least-squares fit of demand=max(a,b*size), a,b >= 0.

    A possible branch change lies between two sorted sizes or at a size.
    Check unconstrained branch optima and every boundary a=b*size.
    """
    pairs=sorted(zip(sizes,demands))
    candidates=[(statistics.mean(demands),0.0),
                (0.0,sum(s*y for s,y in pairs)/sum(s*s for s,y in pairs))]
    for cut in range(1,len(pairs)):
        left,right=pairs[:cut],pairs[cut:]
        a=statistics.mean(y for s,y in left)
        b=sum(s*y for s,y in right)/sum(s*s for s,y in right)
        if b*left[-1][0]<=a+1e-9 and a<=b*right[0][0]+1e-9:candidates.append((a,b))
    for boundary in set(sizes):
        x=[max(boundary,s) for s in sizes]
        b=sum(v*y for v,y in zip(x,demands))/sum(v*v for v in x)
        candidates.append((b*boundary,b))
    return min(candidates,key=lambda ab:sum((max(ab[0],ab[1]*s)-y)**2 for s,y in pairs))


def features(case,kind):
    size=case["size"]/1024
    fanout=case["fanout"]
    if kind=="size_only":return [1,size]
    if kind=="additive_size_fanout":return [1,size,fanout]
    if kind=="joint_work":return [1,size,fanout,size*fanout]
    raise ValueError(kind)


def load(folder):
    design=json.loads((folder/"design.json").read_text())
    rows=[]
    for case in design:
        file=folder/(case["id"]+".json")
        if not file.exists():raise ValueError("study incomplete: "+case["id"])
        row=json.loads(file.read_text())
        if not row["all_accounting_checks_passed"]:
            raise ValueError("invalid retained case: "+case["id"])
        if row["case"]!=case:raise ValueError("case does not match declared design")
        rows.append(row)
    return rows


def evaluate(folder):
    rows=load(folder)
    train=[r for r in rows if r["case"]["split"]=="train"]
    test=[r for r in rows if r["case"]["split"]=="test"]
    if not train or not test:raise ValueError("training and test cases required")
    models={}
    models["constant_messages"]={"constant":statistics.median(r["steady_ack_messages_per_second"] for r in train)}
    models["constant_payload_bytes"]={"bytes_per_second":statistics.median(
        r["steady_ack_messages_per_second"]*r["case"]["size"] for r in train)}
    a,b=fit_roofline([r["case"]["size"]/1024 for r in train],
                    [1e6/r["steady_ack_messages_per_second"] for r in train])
    models["two_limit_roofline"]={"fixed_microseconds":a,"microseconds_per_payload_KiB":b,
        "effective_message_limit":1e6/a if a else None,
        "effective_payload_byte_limit":1e6*1024/b if b else None}
    for kind in ["size_only","additive_size_fanout","joint_work"]:
        x=[features(r["case"],kind) for r in train]
        y=[1e6/r["steady_ack_messages_per_second"] for r in train]
        coefficients,loss=nnls(x,y)
        models[kind]={"effective_microseconds_coefficients":coefficients,
                      "training_squared_service_demand_error":loss}
    results={}
    for name,model in models.items():
        predictions=[]
        for row in test:
            case=row["case"]
            observed=row["steady_ack_messages_per_second"]
            if name=="constant_messages":predicted=model["constant"]
            elif name=="constant_payload_bytes":predicted=model["bytes_per_second"]/case["size"]
            elif name=="two_limit_roofline":
                demand=max(model["fixed_microseconds"],model["microseconds_per_payload_KiB"]*case["size"]/1024)
                predicted=1e6/demand
            else:
                demand=dot(features(case,name),model["effective_microseconds_coefficients"])
                predicted=1e6/demand if demand>0 else math.inf
            # A documented edition limit is a separate ceiling, never fitted
            # from the held-out throughput observations.
            predicted=min(10000,predicted)
            predictions.append({"case":case["id"],"predicted_messages_per_second":predicted,
                "observed_messages_per_second":observed,
                "signed_relative_error":predicted/observed-1,
                "absolute_relative_error":abs(predicted/observed-1)})
        results[name]={"model":model,"held_out_predictions":predictions,
                       "mean_absolute_relative_error":statistics.mean(p["absolute_relative_error"] for p in predictions),
                       "max_absolute_relative_error":max(p["absolute_relative_error"] for p in predictions)}
    return {"training_cases":[r["case"]["id"] for r in train],
            "test_cases":[r["case"]["id"] for r in test],"results":results,
            "scope":"Standard-edition, fixed-SDK, completion-window-controlled pipeline; no unrestricted broker capacity claim",
            "statistical_limit":"two held-out cases; descriptive errors, no population-level accuracy or coverage claim"}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder",type=Path)
    args=parser.parse_args()
    print(json.dumps(evaluate(args.folder),indent=2))
