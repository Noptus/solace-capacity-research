"""Fixed-design live Solace study with held-out size/fanout combinations.

All endpoints bind to localhost. Retains raw SEMP observations and supplemental
container CPU data; only an explicitly created disposable broker is removed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.request import urlopen

from capacity_probe import Broker,Client,IMAGE,docker


def design():
    cases=[]
    # Declare the holdout before measuring. Random order is fixed and does not
    # depend on observed performance. Training includes no test sizes/fanouts.
    grid=[(32768,4),(256,1),(4096,4),(131072,1),
          (256,4),(32768,1),(131072,4),(4096,1)]
    cases.extend({"id":f"train-{size}-{fanout}","size":size,"fanout":fanout,
                  "publishers":4,"app_window":255,"sdk_window":255,"split":"train"}
                 for size,fanout in grid)
    cases.extend({"id":f"test-{size}-{fanout}","size":size,"fanout":fanout,
                  "publishers":4,"app_window":255,"sdk_window":255,"split":"test"}
                 for size,fanout in [(8192,2),(65536,3)])
    # Repeat one calibration point to expose drift, without using it as test.
    cases.append({"id":"repeat-256-1","size":256,"fanout":1,"publishers":4,
                  "app_window":255,"sdk_window":255,"split":"repeat"})
    for c in cases:c["completion_window"]=2048
    cases.append({"id":"credit-control-256-1","size":256,"fanout":1,"publishers":4,
                  "app_window":255,"sdk_window":255,"split":"control","completion_window":4096})
    return cases


def cpu_snapshot(container):
    raw=docker("exec",container,"cat","/sys/fs/cgroup/cpu.stat")
    return {k:int(v) for k,v in (line.split() for line in raw.splitlines())}


def steady_rate(results):
    # Fixed 5..25 second interior window excludes startup and final drain.
    rates=[]
    for result in results:
        samples=[s for s in result["samples"] if 5<s["seconds"]<=25]
        rates.append(sum(s["ack_delta"] for s in samples)/sum(s["interval_seconds"] for s in samples))
    return sum(rates)


def start_client(config,args,readiness_errors,event_callback=None):
    # During initial configuration, the health endpoint can precede the
    # default client's guaranteed-messaging service. Retry only this explicit
    # setup rejection, before any publisher is commanded to start.
    deadline=time.monotonic()+60
    while True:
        try:return Client(config,args.node_modules,event_callback)
        except RuntimeError as error:
            if "GM_UNAVAILABLE" not in str(error) or time.monotonic()>=deadline:raise
            readiness_errors.append(str(error));time.sleep(2)


def run_case(case,broker,container,args,records):
    active=[]
    stop=threading.Event()
    samples=[]
    errors=[]
    readiness_errors=[]
    sampler=None
    credit_lock=threading.RLock()
    completed=[0]*case["fanout"]
    publishers=[]
    last_credit=[case["completion_window"]//case["publishers"]]
    def progress(i,message):
        if message.get("type")!="progress":return
        with credit_lock:
            completed[i]=message["received"]
            limit=(min(completed)+case["completion_window"])//case["publishers"]
            if limit<=last_credit[0]:return
            last_credit[0]=limit
            for p in publishers:
                if p.finished.is_set():continue
                try:p.command("credit",limit=limit)
                except (BrokenPipeError,OSError) as error:
                    if not p.finished.is_set():errors.append("credit feedback: "+str(error))
    queues=[case["id"]+f"-q{i}" for i in range(case["fanout"])]
    try:
        for q in queues:
            broker.create_queue(q,300)
            broker.semp("PATCH","msgVpns/default/queues/"+q,{"egressEnabled":True})
            broker.subscribe(q,"capacity/probe")
        config={"size":case["size"],"window":case["app_window"],
                "sdk_window":case["sdk_window"],"duration_seconds":30}
        consumers=[]
        for i,q in enumerate(queues):
            c=start_client(dict(config,role="consumer",queue=q,report_progress=True),
                           args,readiness_errors,lambda m,i=i:progress(i,m))
            active.append(c);consumers.append(c)
        for _ in range(case["publishers"]):
            p=start_client(dict(config,role="publisher",initial_credit=last_credit[0]),args,readiness_errors)
            active.append(p);publishers.append(p)
        before=broker.semp("GET","msgVpns/default",api="monitor")
        cpu_before=cpu_snapshot(container)
        def monitor():
            while not stop.is_set():
                try:
                    begin=time.monotonic_ns()
                    vpn=broker.semp("GET","msgVpns/default",api="monitor")
                    end=time.monotonic_ns()
                    samples.append({"request_begin_ns":begin,"response_end_ns":end,
                                    "vpn":vpn,"container_cpu":cpu_snapshot(container)})
                except Exception as error:
                    errors.append(str(error));stop.set();return
                stop.wait(2)
        sampler=threading.Thread(target=monitor,daemon=True)
        sampler.start()
        for c in consumers:c.command("start")
        begin=time.monotonic_ns()
        for p in publishers:p.command("start")
        with ThreadPoolExecutor(max_workers=len(publishers)) as pool:
            pub_results=list(pool.map(lambda p:p.wait("result",50),publishers))
        accepted=sum(r["acknowledged"] for r in pub_results)
        drain_deadline=time.monotonic()+60
        while min(completed)<accepted:
            if time.monotonic()>=drain_deadline:raise RuntimeError("consumer drain timed out")
            time.sleep(.1)
        time.sleep(2)
        for c in consumers:c.command("stop")
        con_results=[c.wait("result",10) for c in consumers]
        end=time.monotonic_ns()
        stop.set();sampler.join(12)
        after=broker.semp("GET","msgVpns/default",api="monitor")
        qsnapshot=broker.semp("GET","msgVpns/default/queues?count=100",api="monitor")
        by_name={q["queueName"]:q for q in qsnapshot["data"]}
        sent=sum(r["sent"] for r in pub_results)
        nacks=sum(r["rejected"] for r in pub_results)
        rx_delta=after["data"]["msgSpoolRxMsgCount"]-before["data"]["msgSpoolRxMsgCount"]
        clean=(not errors and sent==accepted and nacks==0 and rx_delta==sent
               and all(r["received"]==accepted for r in con_results)
               and all(by_name[q]["spooledMsgCount"]==accepted
                       and by_name[q]["msgSpoolUsage"]==0 for q in queues))
        if sampler.is_alive():clean=False;errors.append("sampler did not stop")
        record={"case":case,"controller_begin_ns":begin,"controller_end_ns":end,
                "publishers":pub_results,"consumers":con_results,
                "before_vpn":before,"after_vpn":after,"queue_snapshot":qsnapshot,
                "cpu_before":cpu_before,"cpu_after":cpu_snapshot(container),
                "monitor_samples":samples,"monitor_errors":errors,
                "setup_readiness_retries":readiness_errors,
                "accepted_messages":accepted,"nacks":nacks,
                "guaranteed_ingress_delta":rx_delta,"all_accounting_checks_passed":clean,
                "steady_ack_messages_per_second":steady_rate(pub_results),
                "scope":"measured Standard-edition pipeline; unrestricted broker peak not established"}
        records.append(record)
        (args.output/(case["id"]+".json")).write_text(json.dumps(record,indent=2)+"\n")
        print(json.dumps({"case":case["id"],"rate":record["steady_ack_messages_per_second"],
              "clean":clean,"ingress_delta":rx_delta,"accepted":accepted}),flush=True)
        if not clean:raise RuntimeError("accounting or monitoring check failed; inspect retained case record")
    finally:
        stop.set()
        if sampler is not None:sampler.join(12)
        (args.output/(case["id"]+"-client-events.json")).write_text(json.dumps({
            "client_events":[c.history for c in active],"monitor_errors":errors,
            "setup_readiness_retries":readiness_errors},indent=2)+"\n")
        for c in active:c.close()
        # Remove only per-case queues created above, after all clients stop.
        for q in queues:
            try:broker.semp("DELETE","msgVpns/default/queues/"+q)
            except Exception:pass


def run(args):
    args.output.mkdir(parents=True,exist_ok=True)
    args.work_dir.mkdir(parents=True,exist_ok=True)
    cases=design()
    if args.limit:cases=cases[:args.limit]
    raw=json.dumps(cases,sort_keys=True).encode()
    (args.output/"design.json").write_bytes(raw)
    name="capacity-matrix-"+secrets.token_hex(4)
    password=secrets.token_urlsafe(24)
    env_file=args.work_dir/(name+".env")
    env_file.write_text("username_admin_globalaccesslevel=admin\nusername_admin_password="+password+"\n")
    env_file.chmod(0o600)
    owned=False
    records=[]
    try:
        docker("create","--name",name,"--label","codex.task=broker-capacity-matrix",
               "--memory","3g","--cpus","2","--shm-size","1g","--ulimit","nofile=2448:1048576",
               "-p","127.0.0.1:18080:8080","-p","127.0.0.1:15555:55555",
               "-p","127.0.0.1:15550:5550","--env-file",str(env_file),IMAGE)
        owned=True;docker("start",name)
        broker=Broker(password)
        deadline=time.monotonic()+180
        while True:
            try:
                with urlopen("http://127.0.0.1:15550/health-check/guaranteed-active",timeout=3) as r:
                    if r.status!=200:raise RuntimeError("spool unavailable")
                vpn=broker.semp("GET","msgVpns/default")["data"]
                if not vpn["enabled"]:raise RuntimeError("VPN unavailable")
                break
            except Exception:
                if time.monotonic()>deadline:raise
                time.sleep(2)
        version=broker.semp("GET","spec")["info"]["version"]
        (args.output/"environment.json").write_text(json.dumps({"image":IMAGE,
            "broker_version":version,"sdk_version":"10.18.3","cpu_quota":2,"memory_GiB":3,
            "container":name,"design_sha256":hashlib.sha256(raw).hexdigest(),
            "known_edition_limit":"Standard: documented 10000 messages/s ingress",
            "utilization_source":"container cgroup CPU: supplemental validation, not SEMP"},indent=2)+"\n")
        source_dir=args.output/"run-source"
        source_dir.mkdir(exist_ok=True)
        for source in [Path(__file__),Path(__file__).with_name("capacity_probe.py"),Path(__file__).with_name("smf_load.js")]:
            (source_dir/source.name).write_bytes(source.read_bytes())
        for case in cases:
            print("Starting "+case["id"],flush=True)
            run_case(case,broker,name,args,records)
        (args.output/"completed.json").write_text(json.dumps({"cases":len(records),"all_passed":True},indent=2)+"\n")
    except Exception as error:
        (args.output/"failure.json").write_text(json.dumps({"error":str(error),"completed_cases":len(records)},indent=2)+"\n")
        raise
    finally:
        if owned:docker("rm","-f","-v",name)
        env_file.unlink(missing_ok=True)
        print("Disposable matrix broker removed",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path(__file__).parent/"matrix-evidence")
    parser.add_argument("--work-dir",type=Path,default=Path("work/capacity-matrix"))
    parser.add_argument("--node-modules",type=Path,default=Path("work/capacity-node/node_modules"))
    parser.add_argument("--limit",type=int)
    run(parser.parse_args())
