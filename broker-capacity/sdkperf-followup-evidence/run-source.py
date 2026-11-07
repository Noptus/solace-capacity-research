"""Independent SDKPerf/JCSMP fixed-rate checks on an owned localhost broker.

Download SDKPerf separately; it is not redistributed. Java clients run natively
on the host. These are finite-duration operational checks, not peak estimates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import statistics
import subprocess
import time
from urllib.request import urlopen, Request

from capacity_probe import Broker, IMAGE, docker


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def parse_stats(text):
    """Extract final SDKPerf integer counters; retain every original log."""
    def number(pattern):
        values = re.findall(pattern, text, re.M)
        if not values:
            raise ValueError('Missing SDKPerf counter: ' + pattern)
        return int(values[-1].replace(',', ''))
    return {
        'sent': number(r'^Total Messages transmitted\s*=\s*([\d,]+)'),
        'received': number(r'^Total Messages received across all subscribers\s*=\s*([\d,]+)'),
        'crc_ok': number(r'^Total Messages with OK\s*=\s*([\d,]+)'),
        'crc_error': number(r'^Total Messages with ERRORS\s*=\s*([\d,]+)'),
        'order_checked': number(r'^Total Msgs Order Checked\s*:\s*([\d,]+)'),
        'out_of_order': number(r'^Total Out of Order Msgs\s*:\s*([\d,]+)'),
        'missing': number(r'^Total Missing Msgs\s*:\s*([\d,]+)'),
        'duplicate': number(r'^Total Duplicate Msgs\s*:\s*([\d,]+)'),
        'redelivered': number(r'^Total Redelivered Msgs\s*:\s*([\d,]+)'),
        'acks': int(re.findall(r'^\s*Total ACKED Messages\s*=\s*(\d+)', text, re.M)[-1])
                if 'Total ACKED Messages' in text else None,
        'ack_events': int(re.findall(r'^\s*Total ACK Events\s*=\s*(\d+)', text, re.M)[-1])
                      if 'Total ACK Events' in text else None,
        'nacks': int(re.findall(r'^\s*Total NACK Events\s*=\s*(\d+)', text, re.M)[-1])
                 if 'Total NACK Events' in text else None,
    }


def slope(points):
    xbar = statistics.mean(x for x, _ in points)
    ybar = statistics.mean(y for _, y in points)
    denominator = sum((x-xbar)**2 for x, _ in points)
    return sum((x-xbar)*(y-ybar) for x, y in points)/denominator if denominator else 0.


def summarize_samples(samples, case):
    interior = [s for s in samples if 10 <= s['elapsed_seconds'] <= 50]
    if len(interior) < 10:
        raise ValueError('Too few interior SEMP samples')
    first, last = interior[0], interior[-1]
    delta = last['vpn']['data']['msgSpoolRxMsgCount']-first['vpn']['data']['msgSpoolRxMsgCount']
    seconds = last['elapsed_seconds']-first['elapsed_seconds']
    ingress = delta/seconds
    queue_slope = slope([(s['elapsed_seconds'], s['queues']['data'][0]['msgSpoolUsage']) for s in interior])
    interval_rates = [
        (b['vpn']['data']['msgSpoolRxMsgCount']-a['vpn']['data']['msgSpoolRxMsgCount']) /
        (b['elapsed_seconds']-a['elapsed_seconds']) for a,b in zip(interior,interior[1:])]
    return {
        'window_seconds': [first['elapsed_seconds'], last['elapsed_seconds']],
        'interior_ingress_messages_per_second': ingress,
        'interior_interpoll_rate_min': min(interval_rates),
        'interior_interpoll_rate_max': max(interval_rates),
        'interior_interpoll_rate_cv': statistics.pstdev(interval_rates)/statistics.mean(interval_rates),
        'interior_queue_bytes_per_second_ols': queue_slope,
        'maximum_sampled_queue_bytes': max(s['queues']['data'][0]['msgSpoolUsage'] for s in samples),
        'operational_target_tracking': (
            .95*case['target_rate'] <= ingress <= 1.05*case['target_rate']
            and queue_slope <= .02*case['target_rate']*case['size']),
        'criterion': 'Interior ingress within 5% of target; queue OLS growth <=2% of offered payload bytes/s. Finite-window diagnostic, not a stationarity proof.'
    }


def run_case(case, broker, container, args, base):
    name = case['id']
    q = name+'-q'
    broker.create_queue(q, case.get('queue_quota_mb',300))
    broker.semp('PATCH','msgVpns/default/queues/'+q,{'egressEnabled':True})
    broker.subscribe(q,'capacity/probe')
    processes=[]
    handles=[]
    samples=[]
    paths=[]
    commands=[]
    start=None
    record={}
    try:
        def launch(role,index,extra):
            path=args.output/f'{name}-{role}-{index}.log'
            f=path.open('w'); handles.append(f); paths.append((role,path))
            command=base+['-cn='+f'{name}-{role}-{index}']+extra
            commands.append(command)
            p=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,
                               stdin=subprocess.PIPE,start_new_session=True)
            processes.append(p)
            return p
        consumer=launch('consumer',0,['-sql='+q,'-crc','-oc','-asw=255'])
        deadline=time.monotonic()+30
        while 'Getting ready to start clients.' not in paths[0][1].read_text():
            if consumer.poll() is not None:raise RuntimeError('Consumer exited during setup')
            if time.monotonic()>deadline:raise TimeoutError('Consumer readiness')
            time.sleep(.2)
        # Check the queue has a bound flow, not merely a session, before publishing.
        while True:
            flows=broker.semp('GET',f'msgVpns/default/queues/{q}/txFlows',api='monitor')
            if flows['data']:break
            if time.monotonic()>deadline:raise TimeoutError('Consumer flow readiness')
            time.sleep(.2)
        time.sleep(1)
        before=broker.semp('GET','msgVpns/default',api='monitor')
        per_rate=case['target_rate']//case['publishers']
        assert per_rate*case['publishers']==case['target_rate']
        each_count=per_rate*case['duration_seconds']
        start=time.monotonic()
        pubs=[launch('publisher',i,['-ptl=capacity/probe','-mt=persistent',
              '-msa='+str(case['size']),'-mn='+str(each_count),'-mr='+str(per_rate),
              '-crc','-oc','-psm','-pso='+str(i+1)]) for i in range(case['publishers'])]
        hard_deadline=start+case['duration_seconds']+90
        next_sample=start
        def sample():
            begin=time.monotonic()
            vpn=broker.semp('GET','msgVpns/default',api='monitor')
            queues=broker.semp('GET',f'msgVpns/default/queues/{q}',api='monitor')
            # Normalize single-object response to the list used by summarize.
            queues['data']=[queues['data']]
            request=Request('http://127.0.0.1:18080/SEMP',
                data=b'<rpc><show><message-spool><detail/></message-spool></show></rpc>',
                headers={'Authorization':broker.auth,'Content-Type':'application/xml'})
            spool=urlopen(request,timeout=10).read().decode()
            usage=docker('exec',container,'cat','/sys/fs/cgroup/cpu.stat')
            cpu={k:int(v) for k,v in (line.split() for line in usage.splitlines())}
            end=time.monotonic()
            result={'elapsed_seconds':(begin+end)/2-start,
                            'request_begin_seconds':begin-start,'response_end_seconds':end-start,
                            'vpn':vpn,'queues':queues,'spool_xml':spool,'container_cpu':cpu}
            if case.get('process_diagnostics') and len(samples)%5==0:
                request=Request('http://127.0.0.1:18080/SEMP',
                    data=b'<rpc><show><process/></show></rpc>',
                    headers={'Authorization':broker.auth,'Content-Type':'application/xml'})
                result['process_probe_begin_seconds']=time.monotonic()-start
                result['process_xml']=urlopen(request,timeout=10).read().decode()
                result['process_probe_end_seconds']=time.monotonic()-start
            samples.append(result)
        while any(p.poll() is None for p in pubs):
            if time.monotonic()>hard_deadline:raise TimeoutError('Publisher timeout')
            if consumer.poll() is not None:raise RuntimeError('Consumer stopped')
            if time.monotonic()>=next_sample:
                sample();next_sample=time.monotonic()+2
            time.sleep(.05)
        publisher_exit_seconds=time.monotonic()-start
        if any(p.returncode!=0 for p in pubs):raise RuntimeError('Publisher failure')
        # Drain and flush consumer ACKs before final broker counts.
        deadline=time.monotonic()+30
        while True:
            queue=broker.semp('GET',f'msgVpns/default/queues/{q}',api='monitor')['data']
            if queue['msgSpoolUsage']==0 and queue['txUnackedMsgCount']==0:break
            if time.monotonic()>deadline:raise TimeoutError('Queue did not drain')
            time.sleep(.2)
        consumer.send_signal(signal.SIGINT)
        consumer.wait(12)
        for f in handles:f.flush()
        after=broker.semp('GET','msgVpns/default',api='monitor')
        stats=[{'role':role,'log':path.name,'stats':parse_stats(path.read_text())} for role,path in paths]
        pubstats=[s['stats'] for s in stats if s['role']=='publisher']
        constats=[s['stats'] for s in stats if s['role']=='consumer']
        expected=each_count*case['publishers']
        ingress=after['data']['msgSpoolRxMsgCount']-before['data']['msgSpoolRxMsgCount']
        checks={
            'publisher_exit_zero':all(p.returncode==0 for p in pubs),
            'sent_expected':sum(s['sent'] for s in pubstats)==expected,
            'acked_expected':sum(s['acks'] for s in pubstats)==expected,
            'no_nacks':all(s['nacks']==0 for s in pubstats),
            'broker_ingress_equals_unique_sends':ingress==expected,
            'received_expected':all(s['received']==expected for s in constats),
            'crc_checked_all':all(s['crc_ok']==expected and s['crc_error']==0 for s in constats),
            'order_checked_all':all(s['order_checked']==expected for s in constats),
            'no_missing_duplicate_out_of_order_redelivery':all(
                all(s[k]==0 for k in ['out_of_order','missing','duplicate','redelivered']) for s in constats),
            'queue_drained':queue['msgSpoolUsage']==0 and queue['txUnackedMsgCount']==0,
        }
        record={'case':case,'commands':commands,'client_stats':stats,'before_vpn':before,
                'after_vpn':after,'final_queue':queue,'samples':samples,'checks':checks,
                'publisher_exit_seconds':publisher_exit_seconds,'expected_messages':expected,
                'publisher_returncodes':[p.returncode for p in pubs],
                'consumer_returncode':consumer.returncode,'telemetry_summary':summarize_samples(samples,case),
                'all_integrity_checks_passed':all(checks.values())}
        write(args.output/(name+'.json'),record)
        print(json.dumps({'case':name,'clean':all(checks.values()),**record['telemetry_summary']}),flush=True)
        if not all(checks.values()):raise RuntimeError('Integrity check failed: '+str(checks))
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                try:p.wait(3)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        for f in handles:f.close()
        if not record:
            write(args.output/(name+'-partial.json'),{'case':case,'commands':commands,'samples':samples})
        try:broker.semp('DELETE','msgVpns/default/queues/'+q)
        except Exception:pass


def run(args):
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/'design.json').exists():raise ValueError('Refusing to overwrite prior study')
    cases=json.loads(args.design_file.read_text())
    raw=json.dumps(cases,sort_keys=True).encode()
    (args.output/'design.json').write_bytes(raw)
    (args.output/'run-source.py').write_bytes(Path(__file__).read_bytes())
    base=[str(args.java.resolve()),'-Xms64m','-Xmx256m','-cp',':'.join(str(args.sdkperf.resolve()/p)
          for p in ['lib/*','lib/optional/*','lib/optional']),
          'com.solacesystems.pubsub.sdkperf.SDKPerf_java','-cip=127.0.0.1:15555',
          '-cu=default@default','-apw=255','-apa=5000']
    name='sdkperf-crosscheck-'+secrets.token_hex(4)
    password=secrets.token_urlsafe(24)
    args.work_dir.mkdir(parents=True,exist_ok=True)
    env=args.work_dir/(name+'.env')
    env.write_text('username_admin_globalaccesslevel=admin\nusername_admin_password='+password+'\n')
    env.chmod(0o600)
    owned=False
    completed=[]
    try:
        docker('create','--name',name,'--label','codex.task=sdkperf-crosscheck','--memory','3g','--cpus','2',
               '--shm-size','1g','--ulimit','nofile=2448:1048576',
               '-p','127.0.0.1:18080:8080','-p','127.0.0.1:15555:55555','-p','127.0.0.1:15550:5550',
               '--env-file',str(env),IMAGE)
        owned=True;docker('start',name)
        broker=Broker(password)
        deadline=time.monotonic()+180
        while True:
            try:
                urlopen('http://127.0.0.1:15550/health-check/guaranteed-active',timeout=3).close()
                if not broker.semp('GET','msgVpns/default')['data']['enabled']:raise RuntimeError('VPN')
                break
            except Exception:
                if time.monotonic()>deadline:raise
                time.sleep(2)
        jar=args.sdkperf/'lib/sol-sdkperf-jcsmp-10.30.3.jar'
        write(args.output/'environment.json',{
            'image':IMAGE,'cpu_quota':2,'memory_GiB':3,'shm_GiB':1,'container':name,
            'broker_version':broker.semp('GET','spec')['info']['version'],
            'java_version':subprocess.run([str(args.java),'-version'],capture_output=True,text=True).stderr,
            'sdkperf_jar_sha256':hashlib.sha256(jar.read_bytes()).hexdigest(),
            'sdkperf_version':'10.30.3','design_sha256':hashlib.sha256(raw).hexdigest(),
            'source':'https://products.solace.com/download/SDKPERF_JAVA',
            'java_host':'native macOS ARM64; clients outside broker Docker CPU quota',
            'message_semantics':'persistent SMF; one durable queue; CRC+order metadata enabled; no app credit controller',
            'scope':'Independent client-stack fixed-rate crosscheck, not a matched causal comparison or broker peak proof'})
        for case in cases:
            print('Starting '+case['id'],flush=True)
            run_case(case,broker,name,args,base)
            completed.append(case['id'])
            write(args.output/'progress.json',{'completed':completed})
        write(args.output/'completed.json',{'completed':completed,'all_integrity_checks_passed':True})
    except Exception as error:
        write(args.output/'failure.json',{'error':repr(error),'completed':completed})
        raise
    finally:
        if owned:docker('rm','-f','-v',name)
        env.unlink(missing_ok=True)
        print('Owned SDKPerf broker removed',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--design-file',type=Path,required=True)
    parser.add_argument('--java',type=Path,required=True)
    parser.add_argument('--sdkperf',type=Path,required=True)
    parser.add_argument('--work-dir',type=Path,default=Path('work/sdkperf/run'))
    run(parser.parse_args())
