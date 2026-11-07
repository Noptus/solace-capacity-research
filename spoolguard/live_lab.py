"""Run a disposable localhost Solace outage experiment (about two minutes).

Uses the exact image digest recorded below; Docker and that image are required.
No production endpoints are accepted. The created container is removed on exit.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction as F
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import subprocess
import time
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from enforcement import ExpiringBucket, audit_events
from spoolguard import plan

IMAGE = "solace/solace-pubsub-standard@sha256:adbdf6c060abafb0e30dac3d46e335c1e5ea56a7ff02804f9f64b08d84b7b00e"
PAYLOAD = 4096
HORIZON = 30
SOURCE_BURST = 2*PAYLOAD
# One additional packet per sequential publisher reserves a message crossing
# any broker-arrival interval boundary. Each stream has at most one in flight.
ARRIVAL_BURST = SOURCE_BURST+PAYLOAD
EXPANSION = F(5,4)
POLICIES = ["unregulated", "global_throttle", "fanout_aware"]
PUBS = ["orders", "analytics", "payments"]


def docker(*args):
    result = subprocess.run(["docker", *args],text=True,capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


class Broker:
    def __init__(self, password):
        self.auth="Basic "+base64.b64encode(("admin:"+password).encode()).decode()

    def semp(self, method, path, body=None, api="config"):
        request=Request("http://127.0.0.1:18080/SEMP/v2/"+api+"/"+path,
                        method=method,
                        data=json.dumps(body).encode() if body is not None else None,
                        headers={"Authorization":self.auth,"Content-Type":"application/json"})
        try:
            with urlopen(request,timeout=10) as response:
                return json.load(response)
        except HTTPError as error:
            detail=error.read().decode(errors="replace")
            raise RuntimeError(f"SEMP {method} {path}: HTTP {error.code}: {detail}") from None

    def create_queue(self, name, quota_mb):
        return self.semp("POST","msgVpns/default/queues",{
            "queueName":name,"maxMsgSpoolUsage":quota_mb,
            "ingressEnabled":True,"egressEnabled":False,"permission":"consume",
            "respectTtlEnabled":False,"rejectMsgToSenderOnDiscardBehavior":"always"})

    def subscribe(self, queue, topic):
        return self.semp("POST","msgVpns/default/queues/"+quote(queue,safe="")+"/subscriptions",
                         {"subscriptionTopic":topic})


def publish(connection, destination, payload):
    connection.request("POST",destination,body=payload,
                       headers={"Solace-Delivery-Mode":"persistent",
                                "Content-Type":"application/octet-stream"})
    response=connection.getresponse()
    body=response.read()
    return response.status,body[:500].decode(errors="replace")


def calibrate(broker):
    measurements={}
    for size in [256,4096,65536]:
        name=f"lab-cal-{size}"
        broker.create_queue(name,2)
        connection=http.client.HTTPConnection("127.0.0.1",19000,timeout=5)
        for _ in range(20):
            status,_=publish(connection,"/QUEUE/"+name,b"x"*size)
            if status != 200:
                raise RuntimeError(f"calibration publication failed: {status}")
        connection.close()
    # Query each new queue once; never poll it repeatedly during this phase.
    # Thirty seconds allows statistics to settle without aggressive polling.
    time.sleep(30)
    for size in [256,4096,65536]:
        response=broker.semp("GET",f"msgVpns/default/queues/lab-cal-{size}",api="monitor")
        actual=response["data"]["msgSpoolUsage"]
        measurements[str(size)]={"messages":20,"payload_bytes_per_message":size,
            "observed_spool_bytes":actual,"observed_bytes_per_message":str(F(actual,20)),
            "observed_overhead_per_message":str(F(actual,20)-size),"raw_monitor":response}
        if actual > 20*size*EXPANSION:
            raise RuntimeError("configured byte expansion fails empirical calibration")
    return measurements


def setup(broker):
    topology={}
    for policy in POLICIES:
        queues={role:f"lab-{policy}-{role}" for role in ["archive","orders","payments"]}
        for role,name in queues.items():
            broker.create_queue(name,3 if role=="archive" else 12)
        for pub in PUBS:
            topic=f"lab/{policy}/{pub}"
            broker.subscribe(queues["payments" if pub=="payments" else "archive"],topic)
            if pub=="orders": broker.subscribe(queues["orders"],topic)
        connection=http.client.HTTPConnection("127.0.0.1",19000,timeout=5)
        for _ in range(16):
            status,_=publish(connection,"/QUEUE/"+queues["archive"],b"p"*65536)
            if status!=200: raise RuntimeError("prefill failed")
        connection.close()
        topology[policy]=queues
    time.sleep(2)
    snapshot=broker.semp("GET","msgVpns/default/queues?count=100",api="monitor")
    if snapshot.get("meta",{}).get("paging",{}).get("nextPageUri"):
        raise RuntimeError("unexpected pagination in isolated lab")
    by_name={q["queueName"]:q for q in snapshot["data"]}
    configs,plans,rates={},{},{}
    for policy,queues in topology.items():
        config={"horizon_seconds":HORIZON,"publishers":[{
            "name":pub,"demand_bps":200000,"burst_bytes":ARRIVAL_BURST,
            "weight":1 if pub=="analytics" else 2} for pub in PUBS],"queues":[]}
        for role,name in queues.items():
            measured=by_name[name]["msgSpoolUsage"]
            prefill_upper=F(16*65536)*EXPANSION if role=="archive" else F(0)
            if measured>prefill_upper: raise RuntimeError("prefill exceeds accounted-byte envelope")
            route_pubs=(["orders","analytics"] if role=="archive" else [role])
            config["queues"].append({"name":name,
                "capacity_bytes":3000000 if role=="archive" else 12000000,
                "reserve_bytes":300000 if role=="archive" else 1200000,
                "observed_bytes":measured,
                "measurement_uncertainty_bytes":str(prefill_upper-measured),
                "age_seconds":2,"actuation_seconds":2,
                "old_ingress_bps":0,"old_burst_bytes":0,"in_flight_bytes":0,
                "service_floor_bps":0,"routes":{pub:str(EXPANSION) for pub in route_pubs}})
        result=plan(config)
        if result["status"]!="certified_under_assumptions": raise RuntimeError(result)
        if policy=="fanout_aware":
            policy_rates={pub:F(rate) for pub,rate in result["rates_bps_exact"].items()}
        elif policy=="unregulated": policy_rates={pub:F(200000) for pub in PUBS}
        else:
            multiplier=F(1)
            for q,cert in zip(config["queues"],result["certificates"]):
                offered=sum(F(a)*200000 for a in q["routes"].values())
                multiplier=min(multiplier,F(cert["admissible_ingress_bps_exact"])/offered)
            policy_rates={pub:F(200000)*multiplier for pub in PUBS}
        configs[policy],plans[policy],rates[policy]=config,result,policy_rates
    return topology,snapshot,configs,plans,rates


def producer(policy, pub, rate, start_ns, expiry_ns):
    connection=http.client.HTTPConnection("127.0.0.1",19000,timeout=5)
    bucket=ExpiringBucket(rate,SOURCE_BURST,start_ns,expiry_ns)
    events=[]
    try:
        while True:
            now=time.monotonic_ns()
            wait=bucket.wait_ns(PAYLOAD,now)
            if wait is None: break
            if wait:
                time.sleep(wait/1e9)
                continue
            admitted_ns=time.monotonic_ns()
            if not bucket.acquire(PAYLOAD,admitted_ns): continue
            status,body=publish(connection,f"/TOPIC/lab/{policy}/{pub}",b"x"*PAYLOAD)
            event={"send_ns":admitted_ns,"response_ns":time.monotonic_ns(),
                   "payload_bytes":PAYLOAD,"status":status}
            if status!=200: event["error_body"]=body
            events.append(event)
    finally:
        connection.close()
    audit_events(events,rate,SOURCE_BURST,start_ns,expiry_ns)
    return events


def experiment(broker, output):
    output.mkdir(parents=True,exist_ok=True)
    print("Calibrating REST message accounting",flush=True)
    calibration=calibrate(broker)
    print("Creating three isolated copies of the outage topology",flush=True)
    topology,before,configs,plans,rates=setup(broker)
    start_ns=time.monotonic_ns()+2_000_000_000
    expiry_ns=start_ns+HORIZON*1_000_000_000
    print("Running all three policies for 30 seconds",flush=True)
    with ThreadPoolExecutor(max_workers=9) as pool:
        futures={(policy,pub):pool.submit(producer,policy,pub,rates[policy][pub],start_ns,expiry_ns)
                 for policy in POLICIES for pub in PUBS}
        traces={policy:{pub:futures[policy,pub].result() for pub in PUBS} for policy in POLICIES}
    # Snapshot requests are separated by >=30 seconds for the queue collection.
    # With no releases, final occupancy equals peak occupancy after all sends.
    time.sleep(2)
    after=broker.semp("GET","msgVpns/default/queues?count=100",api="monitor")
    by_name={q["queueName"]:q for q in after["data"]}
    outcomes={}
    assertions=[]
    for policy in POLICIES:
        stats={}
        for pub,events in traces[policy].items():
            accepted=sum(e["status"]==200 for e in events)
            statuses={str(s):sum(e["status"]==s for e in events) for s in sorted({e["status"] for e in events})}
            stats[pub]={"attempts":len(events),"accepted":accepted,
                        "accepted_payload_bytes":accepted*PAYLOAD,"http_status_counts":statuses,
                        "assigned_rate_bps_exact":str(rates[policy][pub]),
                        "source_contract_audit":"passed"}
        measurements=[]
        for q,cert in zip(configs[policy]["queues"],plans[policy]["certificates"]):
            d=by_name[q["name"]]
            accepted=sum(stats[pub]["accepted"] for pub in q["routes"])
            prefill=16 if q["name"]==topology[policy]["archive"] else 0
            expected=accepted+prefill
            actual_count=d["spooledMsgCount"]
            accounted_payload=(accepted*PAYLOAD+prefill*65536)
            within_expansion=d["msgSpoolUsage"] <= accounted_payload*EXPANSION
            within_protected=d["msgSpoolUsage"] <= F(cert["protected_capacity_bytes_exact"])
            measurements.append({"queue":q["name"],"observed_spool_bytes":d["msgSpoolUsage"],
                "observed_peak_bytes":d["msgSpoolPeakUsage"],
                "certificate_peak_bytes_exact":cert["peak_bound_bytes_exact"],
                "protected_capacity_bytes_exact":cert["protected_capacity_bytes_exact"],
                "spooled_messages":actual_count,"expected_from_publisher_acks":expected,
                "within_empirical_expansion":within_expansion,"within_protected_capacity":within_protected})
            assertions.append({"check":f"{q['name']}: ACKs match all matching queues",
                               "passed":actual_count==expected})
            assertions.append({"check":f"{q['name']}: accounted bytes fit expansion envelope",
                               "passed":bool(within_expansion)})
            if policy!="unregulated":
                assertions.append({"check":f"{q['name']}: measured peak fits certificate",
                    "passed":d["msgSpoolPeakUsage"]<=F(cert["peak_bound_bytes_exact"])})
        failures=sum(row["attempts"]-row["accepted"] for row in stats.values())
        assertions.append({"check":policy+": expected rejection outcome",
                           "passed":failures>0 if policy=="unregulated" else failures==0})
        outcomes[policy]={"publishers":stats,"queues":measurements,
            "accepted_payload_bytes":sum(x["accepted_payload_bytes"] for x in stats.values()),
            "failed_publications":failures}
    gain=outcomes["fanout_aware"]["accepted_payload_bytes"]/outcomes["global_throttle"]["accepted_payload_bytes"]
    assertions.append({"check":"fanout-aware admits more than uniform global throttling","passed":gain>1})
    record={"image":IMAGE,"broker_version":broker.semp("GET","spec")["info"]["version"],
        "experiment":"localhost REST persistent publication; every queue egress disabled",
        "duration_seconds":HORIZON,"activation_ns":start_ns,"expiry_ns":expiry_ns,
        "source_payload_bytes_per_message":PAYLOAD,"source_burst_bytes":SOURCE_BURST,
        "queue_arrival_burst_bytes_per_publisher":ARRIVAL_BURST,
        "accounting_expansion_exact":str(EXPANSION),"calibration":calibration,
        "configs":configs,"plans":plans,"outcomes":outcomes,
        "accepted_payload_gain_over_global_throttle":gain,"assertions":assertions,
        "all_assertions_passed":all(a["passed"] for a in assertions)}
    for name,data in [("live-results.json",record),("send-traces.json",traces),
                      ("snapshot-before.json",before),("snapshot-after.json",after)]:
        (output/name).write_text(json.dumps(data,indent=2)+"\n")
    print(json.dumps({"all_assertions_passed":record["all_assertions_passed"],
        "accepted_payload_gain_over_global_throttle":gain,
        "outcomes":{p:{k:v for k,v in o.items() if k not in ["publishers","queues"]} for p,o in outcomes.items()}},indent=2),flush=True)
    if not record["all_assertions_passed"]: raise RuntimeError("live experiment assertion failed; inspect live-results.json")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path(__file__).parent/"live-evidence")
    parser.add_argument("--work-dir",type=Path,default=Path("work/spoolguard-live"))
    parser.add_argument("--attach-container",help="Attach only to a running, task-labelled disposable lab")
    parser.add_argument("--env-file",type=Path,help="Required only with --attach-container")
    args=parser.parse_args()
    container=args.attach_container or "spoolguard-"+secrets.token_hex(4)
    owned=False
    env_file=None
    try:
        if args.attach_container:
            if args.env_file is None: parser.error("--env-file is required with --attach-container")
            info=json.loads(docker("inspect",container))[0]
            if info["Config"].get("Labels",{}).get("codex.task")!="spoolguard-validation" or not info["State"]["Running"]:
                raise RuntimeError("only an active task-labelled disposable broker may be attached")
            if info["Image"]!=docker("image","inspect",IMAGE,"--format","{{.Id}}"):
                raise RuntimeError("attached image does not match the pinned experiment image")
            env=dict(line.split("=",1) for line in args.env_file.read_text().splitlines())
            password=env["username_admin_password"]
            owned=True
        else:
            docker("image","inspect",IMAGE,"--format","{{.Id}}")
            args.work_dir.mkdir(parents=True,exist_ok=True)
            password=secrets.token_urlsafe(24)
            env_file=args.work_dir/(container+".env")
            env_file.write_text("username_admin_globalaccesslevel=admin\nusername_admin_password="+password+"\n")
            env_file.chmod(0o600)
            docker("create","--name",container,"--label","codex.task=spoolguard-validation",
                   "--memory","3g","--cpus","2","--shm-size","1g","--ulimit","nofile=2448:1048576",
                   "-p","127.0.0.1:18080:8080","-p","127.0.0.1:19000:9000",
                   "-p","127.0.0.1:15550:5550",
                   "--env-file",str(env_file),IMAGE)
            owned=True
            docker("start",container)
        broker=Broker(password)
        limit=time.monotonic()+180
        while True:
            try:
                broker.semp("GET","about")
                vpn=broker.semp("GET","msgVpns/default")["data"]
                if not (vpn["enabled"] and vpn["maxMsgSpoolUsage"]>0
                        and vpn["serviceRestIncomingPlainTextEnabled"]):
                    raise RuntimeError("default VPN is not ready for persistent REST traffic")
                if not args.attach_container:
                    with urlopen("http://127.0.0.1:15550/health-check/guaranteed-active",timeout=3) as response:
                        if response.status!=200: raise RuntimeError("message spool is not ready")
                break
            except Exception:
                if time.monotonic()>limit: raise
                time.sleep(2)
        args.output.mkdir(parents=True,exist_ok=True)
        for api in ["config","monitor"]:
            spec=broker.semp("GET","spec",api=api)
            raw=json.dumps(spec,sort_keys=True).encode()
            (args.output/(api+"-spec.sha256")).write_text(hashlib.sha256(raw).hexdigest()+"\n")
        experiment(broker,args.output)
    except Exception as error:
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/"failure.json").write_text(json.dumps({"error":str(error)},indent=2)+"\n")
        raise
    finally:
        if owned:
            # The only destructive operation targets the disposable lab we
            # created or explicitly adopted after label and image checks.
            docker("rm","-f","-v",container)
            print("Disposable broker removed",flush=True)
        if env_file: env_file.unlink(missing_ok=True)


if __name__=="__main__":
    main()
