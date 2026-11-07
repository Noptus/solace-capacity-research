"""Build a compact traffic-demand vector from two SEMP observations.

This measures traffic, not remaining capacity. Rates and ratios are exact with
respect to supplied counters/timestamps. Caller must delimit the observation
scope and calibration class; percentages are not silently converted to cores.
"""
from fractions import Fraction
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

VPN_COUNTERS=('dataRxMsgCount','dataRxByteCount','msgSpoolRxMsgCount')
QUEUE_COUNTERS=('spooledMsgCount','spooledByteCount')


def counter_delta(before, after, key):
    a,b=before[key],after[key]
    if isinstance(a,bool) or isinstance(b,bool) or not isinstance(a,int) or not isinstance(b,int):
        raise ValueError('Counter must be an integer: '+key)
    if a<0 or b<a:
        raise ValueError('Negative/reset counter: '+key)
    return b-a


def indexed(queues):
    result={}
    for q in queues:
        key=(q['msgVpnName'],q['queueName'])
        if key in result:raise ValueError('Duplicate queue observation')
        result[key]=q
    return result


def work_vector(before_vpn,after_vpn,before_queues,after_queues,elapsed_ns,*,queue_scope_complete=False):
    if not isinstance(elapsed_ns,int) or elapsed_ns<=0:raise ValueError('Positive integer elapsed_ns required')
    if before_vpn['msgVpnName']!=after_vpn['msgVpnName']:raise ValueError('VPN changed')
    delta={k:counter_delta(before_vpn,after_vpn,k) for k in VPN_COUNTERS}
    source=delta['dataRxMsgCount']
    guaranteed=delta['msgSpoolRxMsgCount']
    # These counters can update at different pipeline stages. Even coherent
    # snapshots can have different interval deltas as in-flight work changes.
    warnings=[]
    if guaranteed>source:
        warnings.append('Guaranteed-stage delta exceeds source-data delta; stage timing or changing in-flight work prevents interpreting normalized counters as exact per-message costs.')
    b,a=indexed(before_queues),indexed(after_queues)
    if set(b)!=set(a):raise ValueError('Queue membership changed; require a closed observation scope')
    if any(vpn!=before_vpn['msgVpnName'] for vpn,_ in a):raise ValueError('Queue belongs to another VPN')
    qdelta={k:sum(counter_delta(b[q],a[q],k) for q in a) for k in QUEUE_COUNTERS}
    counts={
        'source_data_messages':source,
        'source_data_bytes':delta['dataRxByteCount'],
        'guaranteed_ingress_attempts':guaranteed,
        'selected_queue_copies':qdelta['spooledMsgCount'],
        'selected_queue_spooled_bytes':qdelta['spooledByteCount'],
    }
    seconds=Fraction(elapsed_ns,10**9)
    rates={k:Fraction(v,1)/seconds for k,v in counts.items()}
    normalized={k:Fraction(v,source) for k,v in counts.items()} if source else None
    return {
        'counts':counts,'rates_per_second':rates,'per_source_data_message':normalized,
        'guaranteed_minus_source_interval_count':guaranteed-source,'warnings':warnings,
        'elapsed_ns':elapsed_ns,'selected_queues':sorted(a),
        'queue_scope_complete_asserted_by_caller':bool(queue_scope_complete),
        'queue_scope_label':'all asserted queues' if queue_scope_complete else 'selected queues only',
        'peak_messages_per_second':None,
        'interpretation':(
            'Traffic demand only. Queue ingress copies are not consumer deliveries; '
            'spool ingress can include rejected attempts or retransmissions. '
            'dataRxByteCount includes broker-counted data-message bytes, not a pure payload size. '
            'No peak inference without calibrated resource/service constraints and saturation checks.'),
    }


def legacy_pressure(spool_xml,process_xml=None):
    root=ET.fromstring(spool_xml)
    def scalar(name):
        nodes=root.findall('.//'+name)
        if len(nodes)!=1 or nodes[0].text is None:return None
        try:return Fraction(nodes[0].text.strip())
        except ValueError:return None
    current,maximum=scalar('current-cache-usage'),scalar('max-cache-usage')
    result={'cache_usage_reported':current,'cache_limit_reported':maximum,
            'cache_fraction_of_reported_limit':current/maximum if current is not None and maximum else None,
            'disk_messages_currently_spooled':scalar('disk-messages-currently-spooled'),
            'cache_unit_note':'Same-unit ratio; do not interpret reported cache usage as MB.'}
    if process_xml:
        proc=ET.fromstring(process_xml)
        result['process_cpu_usage_reported']=[
            {'process_id':p.findtext('process-id'),'command':p.findtext('command'),
             'cpu_usage_raw':p.findtext('cpu-usage'),'cpu_time_raw':p.findtext('cpu-time')}
            for p in proc.findall('.//processes/process')]
        cpu=proc.find('.//cpus/cpu')
        result['system_cpu_fields_raw']={e.tag:e.text for e in cpu} if cpu is not None else None
        result['cpu_scope_note']='Legacy top-style fields; host/container denominator and sampling interval require separate validation. No automatic utilization-to-capacity conversion.'
    return result


def encode(value):
    if isinstance(value,Fraction):
        return {'numerator':value.numerator,'denominator':value.denominator,'decimal':float(value)}
    raise TypeError(type(value).__name__)


def from_sdkperf_record(record):
    samples=[s for s in record['samples'] if 10<=s['elapsed_seconds']<=50]
    if len(samples)<2:raise ValueError('Need two interior samples')
    first,last=samples[0],samples[-1]
    result=work_vector(first['vpn']['data'],last['vpn']['data'],
        first['queues']['data'],last['queues']['data'],
        round((last['elapsed_seconds']-first['elapsed_seconds'])*10**9),queue_scope_complete=True)
    result['case']=record['case']
    process_sample=next((s for s in reversed(samples) if s.get('process_xml')),None)
    result['pressure_at_last_interior_sample']=legacy_pressure(last['spool_xml'],process_sample.get('process_xml') if process_sample else None)
    if process_sample:
        result['process_cpu_observation_seconds']=process_sample['process_probe_begin_seconds']
    result['class_note']='Persistent SMF, one queue; SDKPerf CRC/order metadata; no TLS/replay/HA in this lab. Do not transfer calibration to other feature classes.'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('record',type=Path,help='Retained sdkperf_crosscheck case JSON')
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    result=from_sdkperf_record(json.loads(args.record.read_text()))
    serialized=json.dumps(result,default=encode,indent=2)+'\n'
    if args.output:args.output.write_text(serialized)
    else:print(serialized,end='')
