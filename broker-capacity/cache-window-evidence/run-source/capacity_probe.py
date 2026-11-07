"""Local sustained SMF/SEMP capacity probe with a client-window sweep.

These measurements characterize a complete test pipeline. They must not be
labelled broker peak without saturation and client-headroom evidence.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time
from urllib.request import urlopen,Request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"spoolguard"))
from live_lab import Broker,IMAGE,docker


class Client:
    def __init__(self,config,node_path,event_callback=None):
        env=dict(os.environ,NODE_PATH=str(node_path.resolve()))
        self.process=subprocess.Popen(["node",str(Path(__file__).with_name("smf_load.js")),json.dumps(config)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        self.messages=queue.Queue()
        self.history=[]
        self.write_lock=threading.Lock()
        self.finished=threading.Event()
        def read():
            for line in self.process.stdout:
                try:message=json.loads(line)
                except ValueError:message={"type":"unparsed","text":line}
                self.history.append(message)
                self.messages.put(message)
                if message.get("type") in ["result","error"]:self.finished.set()
                if event_callback is not None:
                    try:event_callback(message)
                    except Exception as error:
                        self.history.append({"type":"callback-error","error":str(error)})
                        self.messages.put({"type":"error","error":"callback: "+str(error)})
            self.messages.put({"type":"process-ended","returncode":self.process.poll()})
            self.finished.set()
        self.reader=threading.Thread(target=read,daemon=True)
        self.reader.start()
        try:
            self.wait("ready",20)
        except Exception:
            self.close()
            raise

    def wait(self,kind,timeout):
        deadline=time.monotonic()+timeout
        while True:
            message=self.messages.get(timeout=max(.01,deadline-time.monotonic()))
            if message["type"]==kind:return message
            if message["type"] in ["error","process-ended"]:raise RuntimeError(message)

    def command(self,action,**extra):
        with self.write_lock:
            self.process.stdin.write(json.dumps(dict(action=action,**extra))+"\n")
            self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()


def run(args):
    output=args.output
    output.mkdir(parents=True,exist_ok=True)
    work=args.work_dir
    work.mkdir(parents=True,exist_ok=True)
    name="capacity-"+secrets.token_hex(4)
    password=secrets.token_urlsafe(24)
    env_file=work/(name+".env")
    env_file.write_text("username_admin_globalaccesslevel=admin\nusername_admin_password="+password+"\n")
    env_file.chmod(0o600)
    owned=False
    clients=[]
    records=[]
    try:
        docker("create","--name",name,"--label","codex.task=broker-capacity",
               "--memory","3g","--cpus","2","--shm-size","1g","--ulimit","nofile=2448:1048576",
               "-p","127.0.0.1:18080:8080","-p","127.0.0.1:15555:55555",
               "-p","127.0.0.1:15550:5550","--env-file",str(env_file),IMAGE)
        owned=True
        docker("start",name)
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
        queues=[f"capacity-q{i}" for i in range(args.fanout)]
        for qname in queues:
            broker.create_queue(qname,100)
            broker.semp("PATCH","msgVpns/default/queues/"+qname,{"egressEnabled":True})
            broker.subscribe(qname,"capacity/probe")
        version=broker.semp("GET","spec")["info"]["version"]
        baseline=broker.semp("GET","msgVpns/default/queues?count=100",api="monitor")
        # Schema discovery and raw replies are retained; unsupported SEMP v1
        # resource commands are recorded as such rather than silently inferred.
        legacy_queries={
            "system_resources":"<rpc><show><system><resources/></system></show></rpc>",
            "stats_system":"<rpc><show><stats><system/></stats></show></rpc>"}
        for label,body in legacy_queries.items():
            request=Request("http://127.0.0.1:18080/SEMP",data=body.encode(),
                            headers={"Authorization":broker.auth,"Content-Type":"application/xml"})
            try:
                raw=urlopen(request,timeout=10).read().decode()
                (output/(label+".xml")).write_text(raw)
            except Exception as e:(output/(label+".txt")).write_text(str(e))
        for window in args.windows:
            print(f"SMF probe: size={args.size}, fanout={args.fanout}, app_window={window}",flush=True)
            config={"window":window,"size":args.size,"duration_seconds":args.duration}
            consumers=[Client(dict(config,role="consumer",queue=q),args.node_modules) for q in queues]
            clients.extend(consumers)
            publisher=Client(dict(config,role="publisher"),args.node_modules)
            clients.append(publisher)
            global_samples=[]
            sampling=True
            def monitor():
                while sampling:
                    begin=time.monotonic()
                    global_samples.append({"monotonic_seconds":begin,
                        "monitor":broker.semp("GET","",api="monitor")})
                    time.sleep(2)
            sampler=threading.Thread(target=monitor,daemon=True)
            sampler.start()
            for c in consumers:c.command("start")
            start=time.monotonic()
            publisher.command("start")
            result=publisher.wait("result",args.duration+20)
            # Allow final consumer ACK batches and queue statistics to settle.
            time.sleep(2)
            for c in consumers:c.command("stop")
            consumer_results=[c.wait("result",10) for c in consumers]
            sampling=False
            sampler.join(5)
            after=broker.semp("GET","msgVpns/default/queues?count=100",api="monitor")
            before_by={q["queueName"]:q for q in baseline["data"]}
            after_by={q["queueName"]:q for q in after["data"]}
            queue_deltas={q:{"spooled_messages":after_by[q]["spooledMsgCount"]-before_by[q]["spooledMsgCount"],
                "remaining_bytes":after_by[q]["msgSpoolUsage"]} for q in queues}
            clean=(result["sent"]==result["acknowledged"] and result["rejected"]==0 and
                   all(c["received"]==result["acknowledged"] for c in consumer_results) and
                   all(d["spooled_messages"]==result["acknowledged"] and d["remaining_bytes"]==0
                       for d in queue_deltas.values()))
            record={"size":args.size,"fanout":args.fanout,"application_window":window,
                    "publisher":result,"consumers":consumer_results,"queue_deltas":queue_deltas,
                    "monitor_samples":global_samples,"snapshot_before":baseline,"snapshot_after":after,
                    "all_messages_accounted_and_drained":clean,
                    "acknowledged_messages_per_second":result["acknowledged"]/result["duration_seconds"],
                    "classification":"end-to-end pipeline measurement; broker peak not established"}
            records.append(record)
            (output/"probe-results.json").write_text(json.dumps({"image":IMAGE,"broker_version":version,
                "broker_cpu_limit":2,"broker_memory_limit_GiB":3,"sdk_version":"10.18.3",
                "records":records},indent=2)+"\n")
            print(json.dumps({"window":window,"msg_per_second":record["acknowledged_messages_per_second"],
                "mean_ack_ms":result["mean_ack_ms"],"client_elu":result["event_loop_utilization"],
                "accounted_and_drained":clean}),flush=True)
            for c in consumers+[publisher]:c.close();clients.remove(c)
            baseline=after
            if not clean:raise RuntimeError("message accounting/drain check failed")
    except Exception as error:
        (output/"failure.json").write_text(json.dumps({"error":str(error)},indent=2)+"\n")
        raise
    finally:
        for c in clients:c.close()
        if owned:docker("rm","-f","-v",name)
        env_file.unlink(missing_ok=True)
        print("Disposable capacity broker removed",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size",type=int,default=256)
    parser.add_argument("--fanout",type=int,default=1)
    parser.add_argument("--duration",type=int,default=30)
    parser.add_argument("--windows",type=lambda s:list(map(int,s.split(','))),default=[1,64,255])
    parser.add_argument("--node-modules",type=Path,default=Path("work/capacity-node/node_modules"))
    parser.add_argument("--work-dir",type=Path,default=Path("work/capacity-probe"))
    parser.add_argument("--output",type=Path,default=Path(__file__).parent/"pilot-evidence")
    args=parser.parse_args()
    if args.duration<30 or args.size<=0 or args.fanout<1 or args.fanout>8:
        parser.error("duration >=30, size >0 and 1<=fanout<=8 required")
    run(args)
