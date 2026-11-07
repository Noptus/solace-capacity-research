"""Audit retained SDKPerf logs and SEMP counters without importing the runner."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def audit(folder,allow_prefix=False):
    checks=[]
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
    env=json.loads((folder/'environment.json').read_text())
    design_bytes=(folder/'design.json').read_bytes()
    design=json.loads(design_bytes)
    complete=(folder/'completed.json').exists()
    if not complete and not allow_prefix:raise ValueError('Study incomplete; use --allow-prefix to audit only accepted completed cases')
    terminal=json.loads((folder/('completed.json' if complete else 'failure.json')).read_text())
    full_design=design
    if not complete:design=design[:len(terminal['completed'])]
    check('design_hash',hashlib.sha256(design_bytes).hexdigest()==env['design_sha256'])
    check('terminal_all_cases',terminal['completed']==[c['id'] for c in design])
    check('at_least_one_accepted_case',len(design)>0)
    total=0
    summaries=[]
    for c in design:
        name=c['id']
        r=json.loads((folder/(name+'.json')).read_text())
        check(name+':case_matches_design',r['case']==c)
        check(name+':accepted_integrity_record',r['all_integrity_checks_passed'])
        expected=c['target_rate']*c['duration_seconds']
        def count(log,label,delimiter='='):
            matches=re.findall(r'^\s*'+re.escape(label)+r'\s*'+re.escape(delimiter)+r'\s*([0-9,]+)',log,re.M)
            if not matches:raise ValueError('Missing '+label+' in '+name)
            return int(matches[-1].replace(',',''))
        pubs=[(folder/f'{name}-publisher-{i}.log').read_text() for i in range(c['publishers'])]
        consumer=(folder/f'{name}-consumer-0.log').read_text()
        transmitted=sum(count(p,'Total Messages transmitted') for p in pubs)
        check(name+':expected_transmitted',transmitted==expected)
        check(name+':expected_acked',sum(count(p,'Total ACKED Messages') for p in pubs)==expected)
        check(name+':no_nacks',sum(count(p,'Total NACK Events') for p in pubs)==0)
        check(name+':received',count(consumer,'Total Messages received across all subscribers')==expected)
        check(name+':all_crc_ok',count(consumer,'Total Messages with OK')==expected)
        check(name+':no_crc_errors',count(consumer,'Total Messages with ERRORS')==0)
        check(name+':all_order_checked',count(consumer,'Total Msgs Order Checked',':')==expected)
        for label in ['Total Out of Order Msgs','Total Missing Msgs','Total Duplicate Msgs','Total Redelivered Msgs']:
            check(name+':'+label,count(consumer,label,':')==0)
        before=r['before_vpn']['data']['msgSpoolRxMsgCount']
        after=r['after_vpn']['data']['msgSpoolRxMsgCount']
        check(name+':broker_attempts_equal_expected',after-before==expected)
        q=r['final_queue']
        check(name+':drained',q['msgSpoolUsage']==0 and q['txUnackedMsgCount']==0)
        check(name+':queue_received',q['spooledMsgCount']==expected)
        check(name+':returncodes',r['publisher_returncodes']==[0]*c['publishers'])
        samples=[s for s in r['samples'] if 10<=s['elapsed_seconds']<=50]
        check(name+':enough_interior_samples',len(samples)>=10)
        t=[s['elapsed_seconds'] for s in samples]
        check(name+':strict_sample_times',all(b>a for a,b in zip(t,t[1:])))
        ingress=(samples[-1]['vpn']['data']['msgSpoolRxMsgCount']-samples[0]['vpn']['data']['msgSpoolRxMsgCount'])/(t[-1]-t[0])
        check(name+':interior_rate_recomputed',abs(ingress-r['telemetry_summary']['interior_ingress_messages_per_second'])<1e-8)
        # Record independently computed rates, without requiring a requested
        # load to be feasible; infeasibility is a legitimate study result.
        summaries.append({'case':name,'size':c['size'],'target_rate':c['target_rate'],
                          'interior_ingress_rate':ingress,'source_messages':expected})
        total+=expected
    return {'study':str(folder),'study_completed':complete,'designed_cases':len(full_design),
            'audited_accepted_cases':len(design),'excluded_or_unrun_cases':[c['id'] for c in full_design[len(design):]],
            'checks':checks,'check_count':len(checks),
            'all_passed':all(c['passed'] for c in checks),'source_messages':total,
            'consumer_receipts':total,'case_summaries':summaries,
            'scope':'Evidence integrity and counter/rate recomputation; not a general broker-capacity certificate.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--allow-prefix',action='store_true',help='Audit accepted cases before a recorded failure; never labels the study complete')
    args=p.parse_args()
    result=audit(args.folder,args.allow_prefix)
    output=args.output or args.folder/'independent-audit.json'
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='checks'},indent=2))
    raise SystemExit(0 if result['all_passed'] else 1)
