"""Independent evidence audit; imports neither the planner nor the shaper.

Recomputes finite-horizon bounds, all-interval source envelopes, ACK-to-queue
counts and measured peak comparisons from raw saved records. It establishes
internal consistency of this evidence, not universal safety or authenticity.
"""
import argparse
from fractions import Fraction as F
import json
from pathlib import Path


def audit(folder):
    record=json.loads((folder/"live-results.json").read_text())
    traces=json.loads((folder/"send-traces.json").read_text())
    before=json.loads((folder/"snapshot-before.json").read_text())
    after=json.loads((folder/"snapshot-after.json").read_text())
    old={q["queueName"]:q for q in before["data"]}
    new={q["queueName"]:q for q in after["data"]}
    checks=[]
    def check(name,passed):
        checks.append({"check":name,"passed":bool(passed)})
    start,expiry=record["activation_ns"],record["expiry_ns"]
    horizon=F(record["duration_seconds"])
    check("horizon matches activation and expiry",expiry-start==horizon*1_000_000_000)
    totals={}
    for policy,streams in traces.items():
        config=record["configs"][policy]
        stats=record["outcomes"][policy]["publishers"]
        rates={pub:F(s["assigned_rate_bps_exact"]) for pub,s in stats.items()}
        accepted={}
        for pub,events in streams.items():
            rate=rates[pub]
            burst=F(record["source_burst_bytes"])
            prefix=F(0)
            min_prior=None
            previous_send=start
            previous_response=start
            envelopes=times=serial=True
            for event in events:
                send=event["send_ns"]
                cost=event["payload_bytes"]
                times &= start<=send<expiry and send>=previous_send and event["response_ns"]>=send
                serial &= send>=previous_response
                t=F(send-start,1_000_000_000)
                prior=prefix-rate*t
                min_prior=prior if min_prior is None else min(min_prior,prior)
                prefix+=cost
                # For every inclusive event interval l..r:
                # P_r-r*t_r <= B + min_l(P_(l-1)-r*t_l).
                envelopes &= prefix-rate*t <= burst+min_prior
                previous_send,previous_response=send,event["response_ns"]
            accepted[pub]=sum(e["status"]==200 for e in events)
            check(f"{policy}/{pub}: every interval satisfies source token envelope",envelopes)
            check(f"{policy}/{pub}: activation, expiry and ordering",times)
            check(f"{policy}/{pub}: at most one HTTP message outstanding",serial)
            check(f"{policy}/{pub}: accepted count matches trace",accepted[pub]==stats[pub]["accepted"])
            check(f"{policy}/{pub}: fixed message cost matches workload",
                  all(e["payload_bytes"]==record["source_payload_bytes_per_message"] for e in events))
            check(f"{policy}/{pub}: demand respected",rate<=200000)
        totals[policy]=sum(accepted.values())*record["source_payload_bytes_per_message"]
        for q in config["queues"]:
            name=q["name"]
            def val(key): return F(q.get(key,0))
            initial=(val("observed_bytes")+val("measurement_uncertainty_bytes")+
                     val("in_flight_bytes")+val("old_burst_bytes")+
                     val("old_ingress_bps")*(val("age_seconds")+val("actuation_seconds")))
            pubs={p["name"]:p for p in config["publishers"]}
            burst=val("background_burst_bytes")+sum(F(a)*F(pubs[p]["burst_bytes"])
                                                      for p,a in q["routes"].items())
            ingress=val("background_bps")+sum(F(a)*rates[p] for p,a in q["routes"].items())
            mu,latency=val("service_floor_bps"),val("service_latency_seconds")
            # Deliberately evaluate the candidate times, not rate_cap or
            # peak_growth from the implementation under test.
            growth=max(ingress*t-mu*max(F(0),t-latency)
                       for t in [F(0),min(latency,horizon),horizon])
            peak=initial+burst+growth
            protected=val("capacity_bytes")-val("reserve_bytes")
            d=new[name]
            is_archive="archive" in name
            prefill_count=16 if is_archive else 0
            expected_count=prefill_count+sum(accepted[p] for p in q["routes"])
            check(name+": actual starting occupancy covered",old[name]["msgSpoolUsage"]<=initial)
            check(name+": ACK fanout exactly matches raw broker counter",d["spooledMsgCount"]==expected_count)
            check(name+": queue has no egress or TTL release",
                  not d["egressEnabled"] and not d["respectTtlEnabled"]
                  and d["deletedMsgCount"]==0 and d["bindSuccessCount"]==0)
            check(name+": final usage equals peak",d["msgSpoolUsage"]==d["msgSpoolPeakUsage"])
            payload=(prefill_count*65536+
                     sum(accepted[p] for p in q["routes"])*record["source_payload_bytes_per_message"])
            check(name+": observed accounting fits reserved expansion",
                  d["msgSpoolUsage"]<=payload*F(record["accounting_expansion_exact"]))
            if policy!="unregulated":
                check(name+": actual assigned rates satisfy protected mathematical bound",peak<=protected)
                check(name+": measured peak fits independently recomputed bound",d["msgSpoolPeakUsage"]<=peak)
        failed=sum(e["status"]!=200 for events in streams.values() for e in events)
        check(policy+": expected rejection behavior",failed>0 if policy=="unregulated" else failed==0)
        if policy=="unregulated":
            check("unregulated failures are quota-related HTTP 503 responses",
                  all(e["status"]==503 and "quota" in e.get("error_body","").lower()
                      for events in streams.values() for e in events if e["status"]!=200))
    ratio=totals["fanout_aware"]/totals["global_throttle"]
    check("gain recomputed from successful raw publications",
          ratio==record["accepted_payload_gain_over_global_throttle"])
    return {"passed":all(c["passed"] for c in checks),"checks":checks,
            "number_of_checks":len(checks),"accepted_payload_bytes":totals,
            "accepted_payload_gain_over_global_throttle":ratio}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder",type=Path)
    args=parser.parse_args()
    result=audit(args.folder)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["passed"] else 1)
