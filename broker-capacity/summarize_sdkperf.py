"""Create an evidence summary and static figure after SDKPerf runs terminate."""
from pathlib import Path
import csv
import json

ROOT=Path(__file__).resolve().parent
folders=[ROOT/n for n in ['sdkperf-validated-evidence','sdkperf-followup-evidence','sdkperf-drain-evidence']]
rows=[]
studies=[]
for folder in folders:
    complete=(folder/'completed.json').exists()
    terminal=folder/('completed.json' if complete else 'failure.json')
    result=json.loads(terminal.read_text())
    studies.append({'folder':folder.name,'study_completed':complete,'accepted_cases':result['completed']})
    for name in result['completed']:
        r=json.loads((folder/(name+'.json')).read_text())
        if not r['all_integrity_checks_passed']:raise ValueError('Bad accepted record')
        t=r['telemetry_summary'];c=r['case']
        rows.append({'case':name,'payload_bytes':c['size'],'target_messages_per_second':c['target_rate'],
            'interior_ingress_messages_per_second':t['interior_ingress_messages_per_second'],
            'target_tracks':t['operational_target_tracking'],
            'sampled_peak_queue_bytes':t['maximum_sampled_queue_bytes'],
            'interior_queue_growth_bytes_per_second':t['interior_queue_bytes_per_second_ols'],
            'source_messages':r['expected_messages'],
            'publisher_exit_seconds':r['publisher_exit_seconds']})
total=sum(r['source_messages'] for r in rows)
summary={'studies':studies,'clean_cases':len(rows),'source_messages':total,'consumer_receipts':total,
         'cases':rows,'scope':'Finite-duration independent client-stack checks, not a broker peak certificate.'}
(ROOT/'sdkperf-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
with (ROOT/'sdkperf-summary.csv').open('w') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(2,1,figsize=(10,6.6),layout='constrained',sharex=True)
colors=['#1d7b73' if r['target_tracks'] else '#bc604d' for r in rows]
ratios=[r['interior_ingress_messages_per_second']/r['target_messages_per_second'] for r in rows]
axes[0].bar(range(len(rows)),ratios,color=colors,width=.65)
axes[0].axhspan(.95,1.05,color='#315d7e',alpha=.1)
axes[0].axhline(1,color='#315d7e',linestyle='--',linewidth=1)
for i,(ratio,r) in enumerate(zip(ratios,rows)):
    axes[0].text(i,ratio+.025,f"{r['interior_ingress_messages_per_second']:,.0f}/s",ha='center',fontsize=9)
axes[0].set_ylim(0,1.23);axes[0].set_ylabel('Measured ingress / requested rate')
axes[0].set_title('Correct delivery does not establish a sustainable offered rate',loc='left',fontweight='bold')
axes[1].bar(range(len(rows)),[r['sampled_peak_queue_bytes']/1024**2 for r in rows],color=colors,width=.65)
axes[1].set_yscale('log');axes[1].set_ylabel('Maximum sampled queue usage (MiB)')
axes[1].set_xticks(range(len(rows)),[f"{r['payload_bytes']/1024:g} KiB\n{r['target_messages_per_second']:,}/s" for r in rows])
axes[1].set_xlabel('Payload size and requested source rate; repeats shown separately')
for ax in axes:
    ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
fig.text(.01,-.045,'Only integrity-accepted cases shown. Interior: 10-50s. Green = declared finite-window tracking check passed; red = failed.\nDifferent quotas/end delays are recorded in designs. No broker peak, statistical stationarity, or matched client comparison is claimed.',fontsize=8,color='#53616c')
fig.savefig(ROOT/'sdkperf-targets.png',dpi=180,bbox_inches='tight')
plt.close(fig)

lines=['SDKPerf crosscheck: measured results','====================================','',
       f'{len(rows)} integrity-accepted cases; {total:,} source messages and matching consumer receipts.','',
       'Requested rate is not achieved throughput. All cases request 60 seconds of',
       'messages, but backpressured fixed-count publishers can take longer.',
       'The measured interior SEMP statistic spans samples between 10 and 50 seconds.','']
for r in rows:
    lines.append(f"* {r['case']}: target {r['target_messages_per_second']:,}/s; measured {r['interior_ingress_messages_per_second']:,.2f}/s; tracking {'passes' if r['target_tracks'] else 'fails'}; max sampled queue {r['sampled_peak_queue_bytes']/1024**2:.2f} MiB.")
lines+=['','Tracking requires ingress within 5% of the target and queue-byte OLS growth',
        'no greater than 2% of offered payload bytes/s. It is an operational diagnostic,',
        'not a statistical stationarity proof. Green/accepted never means peak.','',
        'Study terminal states','---------------------','']
for s in studies:
    lines.append(f"* {s['folder']}: {'complete' if s['study_completed'] else 'stopped on a retained failure'}; {len(s['accepted_cases'])} accepted cases.")
lines+=['','The first corrected design stopped at a 32 KiB / 1000/s quota overload.',
        'The follow-up stopped at an unresolved 128 KiB / 152/s completion tail.',
        'The separate 60-second drain control ACKed/received all 9120 with CRC/order',
        'checks but recorded 9344 ingress attempts. The 224-attempt surplus is',
        'consistent with retries, not directly identified by an SDK retry counter.',
        'It remains excluded from the zero-surplus clean-calibration set.',
        'The earlier same-stream sequence-check setup failure is also retained.',
        'None of those failed records is silently included as clean calibration.','',
        'Interpretation','--------------','',
        'SDKPerf independently reproduces higher-load limitations in this local setup.',
        'It does not prove a broker-only bottleneck. Different tool versions, metadata,',
        'rate control, ACK timeouts, quotas and end delays preclude a matched causal',
        'comparison with the Node.js study. Standard-edition limits and one Docker',
        'environment do not identify unrestricted Enterprise performance.','',
        'See SDKPERF-SETUP.rst for reproduction and SEMP-WORK-VECTOR.rst for the compact',
        'traffic abstraction, SEMP v1 CPU discovery, and counter semantics under overload.','',
        'The next scientific gate remains calibrated resource/service constraints and',
        'longer randomized stability checks across new features, sizes and fanouts.','']
(ROOT/'SDKPERF-RESULTS.rst').write_text('\n'.join(lines))
print(json.dumps({'clean_cases':len(rows),'source_messages':total,'consumer_receipts':total}))
