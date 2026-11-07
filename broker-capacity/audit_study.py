"""Independent count/design audit of captured studies; no runner/model imports."""
import argparse
import hashlib
import json
from pathlib import Path


def audit(folder):
    design=json.loads((folder/"design.json").read_text())
    env=json.loads((folder/"environment.json").read_text())
    checks=[]
    def check(name,passed):checks.append({"check":name,"passed":bool(passed)})
    check("declared design hash matches environment",hashlib.sha256(
        json.dumps(design,sort_keys=True).encode()).hexdigest()==env["design_sha256"])
    check("study has terminal completion record",json.loads((folder/"completed.json").read_text())["cases"]==len(design))
    totals={"source_sends":0,"source_acks":0,"consumer_receipts":0}
    for case in design:
        r=json.loads((folder/(case["id"]+".json")).read_text())
        prefix=case["id"]+": "
        check(prefix+"case matches declared design",r["case"]==case)
        pubs=r["publishers"];cons=r["consumers"]
        sent=sum(p["sent"] for p in pubs);acked=sum(p["acknowledged"] for p in pubs)
        nacks=sum(p["rejected"] for p in pubs)
        retry=sum(p["sdk_stats"]["TX_PERSISTENT_REDELIVERED"] for p in pubs)
        check(prefix+"all source sends acknowledged with no rejection",sent==acked and nacks==0)
        check(prefix+"sources and consumers match topology",len(pubs)==case["publishers"] and len(cons)==case["fanout"])
        check(prefix+"every consumer count matches source ACKs",all(c["received"]==acked for c in cons))
        check(prefix+"runtime source settings match design",all(p["window"]==case["app_window"] and
            p["sdk_window"]==case["sdk_window"] and p["ack_timeout_ms"]==case["ack_timeout_ms"] for p in pubs))
        rx=(r["after_vpn"]["data"]["msgSpoolRxMsgCount"]-
            r["before_vpn"]["data"]["msgSpoolRxMsgCount"])
        check(prefix+"SEMP ingress reconciles original and retransmitted sends",rx==sent+retry)
        expected={case["id"]+f"-q{i}" for i in range(case["fanout"])}
        queues={q["queueName"]:q for q in r["queue_snapshot"]["data"]}
        check(prefix+"all expected queues observed",expected<=set(queues))
        check(prefix+"all queue-copy counters match and all queues drained",all(
            queues[q]["spooledMsgCount"]==acked and queues[q]["msgSpoolUsage"]==0 for q in expected))
        calculated=0
        for p in pubs:
            samples=[s for s in p["samples"] if 5<s["seconds"]<=25]
            calculated+=sum(s["ack_delta"] for s in samples)/sum(s["interval_seconds"] for s in samples)
        check(prefix+"interior statistic recomputed from raw ACK buckets",
              abs(calculated-r["steady_ack_messages_per_second"])<=max(1e-9,calculated*1e-12))
        check(prefix+"monitoring completed without an error",not r["monitor_errors"])
        totals["source_sends"]+=sent;totals["source_acks"]+=acked
        totals["consumer_receipts"]+=sum(c["received"] for c in cons)
    return {"passed":all(c["passed"] for c in checks),"case_count":len(design),
            "number_of_checks":len(checks),"totals":totals,"checks":checks,
            "scope":"internal count/design consistency; does not establish stationarity, message integrity or broker peak"}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("folder",type=Path)
    r=audit(p.parse_args().folder);print(json.dumps(r,indent=2));raise SystemExit(0 if r["passed"] else 1)
