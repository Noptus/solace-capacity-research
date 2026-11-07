import sys,subprocess,secrets,time,signal,json,os
from pathlib import Path
from urllib.request import urlopen
ROOT=Path('/Users/raphaelcaillon/Documents/Codex/2026-11-07/go')
sys.path.insert(0,str(ROOT/'outputs/broker-capacity'))
from capacity_probe import Broker,IMAGE,docker
work=ROOT/'work/sdkperf'
java=work/'jdk-17.0.21+9-jre/Contents/Home/bin/java'
tool=work/'sdkperf-jcsmp-10.30.3'
base=[str(java),'-Xms64m','-Xmx256m','-cp',':'.join(str(tool/p) for p in ['lib/*','lib/optional/*','lib/optional']),
      'com.solacesystems.pubsub.sdkperf.SDKPerf_java','-cip=127.0.0.1:15555','-cu=default@default','-apw=255','-apa=5000']
name='sdkperf-pilot-'+secrets.token_hex(4)
password=secrets.token_urlsafe(24)
env=work/(name+'.env')
env.write_text('username_admin_globalaccesslevel=admin\nusername_admin_password='+password+'\n')
env.chmod(0o600)
active=[]
owned=False
try:
    docker('create','--name',name,'--label','codex.task=sdkperf-pilot','--memory','3g','--cpus','2','--shm-size','1g',
           '--ulimit','nofile=2448:1048576','-p','127.0.0.1:18080:8080','-p','127.0.0.1:15555:55555',
           '-p','127.0.0.1:15550:5550','--env-file',str(env),IMAGE)
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
    broker.create_queue('sdkperf-pilot-q',100)
    broker.semp('PATCH','msgVpns/default/queues/sdkperf-pilot-q',{'egressEnabled':True})
    broker.subscribe('sdkperf-pilot-q','capacity/probe')
    for role,extra in [('consumer',['-sql=sdkperf-pilot-q','-crc','-oc']),
                       ('publisher',['-ptl=capacity/probe','-mt=persistent','-msa=256','-mn=200','-mr=100','-crc','-oc'])]:
        f=(work/(role+'.log')).open('w')
        p=subprocess.Popen(base+['-cn='+role+'-pilot']+extra,stdout=f,stderr=subprocess.STDOUT,
                           stdin=subprocess.PIPE,start_new_session=True)
        active.append((p,f))
        if role=='consumer':time.sleep(5)
    active[-1][0].wait(30)
    time.sleep(3)
    active[0][0].send_signal(signal.SIGINT)
    active[0][0].wait(10)
    (work/'pilot-monitor.json').write_text(json.dumps(broker.semp('GET','msgVpns/default/queues?count=100',api='monitor'),indent=2))
    print('pilot finished',flush=True)
finally:
    for p,f in active:
        if p.poll() is None:
            p.terminate()
            try:p.wait(3)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        f.close()
    if owned:docker('rm','-f','-v',name)
    env.unlink(missing_ok=True)
