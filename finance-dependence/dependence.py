"""Sharp product-expectation bounds for two finite nonnegative marginals.

Classical monotone/countermonotone coupling, implemented with exact fractions.
Returns attaining joint distributions, not just numerical bounds. No market
data or empirical trading profitability is assumed by these calculations.
"""
import argparse
from fractions import Fraction as F
import json
from pathlib import Path


def value(x):
    if isinstance(x,bool):raise ValueError("booleans are not numeric inputs")
    try:r=F(str(x))
    except (ValueError,ZeroDivisionError):raise ValueError("finite rational input required") from None
    if r<0:raise ValueError("nonnegative input required")
    return r


def marginal(histogram):
    weights={}
    for item in histogram:
        x,w=value(item["value"]),value(item["weight"])
        weights[x]=weights.get(x,F(0))+w
    total=sum(weights.values(),F(0))
    if total<=0:raise ValueError("a marginal must have positive total weight")
    return [(x,w/total) for x,w in sorted(weights.items()) if w]


def couple(left,right,reverse=False):
    """Merge sorted quantile steps. Inputs are normalized positive masses."""
    right=list(reversed(right)) if reverse else right
    i=j=0
    a,b=left[0][1],right[0][1]
    expectation=F(0)
    witness=[]
    while i<len(left) and j<len(right):
        mass=min(a,b)
        x,y=left[i][0],right[j][0]
        expectation+=mass*x*y
        witness.append({"x":str(x),"y":str(y),"probability":str(mass)})
        a-=mass;b-=mass
        if not a:
            i+=1
            if i<len(left):a=left[i][1]
        if not b:
            j+=1
            if j<len(right):b=right[j][1]
    if i!=len(left) or j!=len(right):raise ArithmeticError("unbalanced normalized marginals")
    return expectation,witness


def bounds(left_hist,right_hist,cost=0):
    left,right=marginal(left_hist),marginal(right_hist)
    lower,lower_witness=couple(left,right,reverse=True)
    upper,upper_witness=couple(left,right)
    mean_left=sum(x*w for x,w in left)
    mean_right=sum(x*w for x,w in right)
    independent=mean_left*mean_right
    cost=value(cost)
    return {"lower_product_expectation_exact":str(lower),
            "upper_product_expectation_exact":str(upper),
            "independence_product_expectation_exact":str(independent),
            "left_mean_exact":str(mean_left),"right_mean_exact":str(mean_right),
            "constant_cost_exact":str(cost),
            "net_lower_exact":str(lower-cost),"net_upper_exact":str(upper-cost),
            "net_independence_exact":str(independent-cost),
            "minimizing_joint_distribution":lower_witness,
            "maximizing_joint_distribution":upper_witness,
            "scope":"sharp bounds conditional on the supplied finite marginals; no empirical profitability claim"}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path)
    args=parser.parse_args()
    data=json.loads(args.input.read_text(),parse_float=str)
    print(json.dumps(bounds(data["left"],data["right"],data.get("constant_cost",0)),indent=2))
