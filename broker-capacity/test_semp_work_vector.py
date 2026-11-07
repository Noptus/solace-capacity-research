from fractions import Fraction as F
import unittest
from semp_work_vector import work_vector,legacy_pressure


def vpn(n=0,b=0,g=0):
    return dict(msgVpnName='v',dataRxMsgCount=n,dataRxByteCount=b,msgSpoolRxMsgCount=g)


def queue(n=0,b=0,name='q'):
    return dict(msgVpnName='v',queueName=name,spooledMsgCount=n,spooledByteCount=b)


class WorkVectorTests(unittest.TestCase):
    def test_exact_counter_rates(self):
        r=work_vector(vpn(),vpn(10,3500,10),[queue()],[queue(30,9000)],3*10**9)
        self.assertEqual(r['rates_per_second']['source_data_messages'],F(10,3))
        self.assertEqual(r['per_source_data_message']['selected_queue_copies'],3)
        self.assertEqual(r['per_source_data_message']['selected_queue_spooled_bytes'],900)
        self.assertIsNone(r['peak_messages_per_second'])

    def test_reset_or_membership_change_rejected(self):
        with self.assertRaises(ValueError):work_vector(vpn(2),vpn(1),[],[],10**9)
        with self.assertRaises(ValueError):work_vector(vpn(),vpn(),[],[queue()],10**9)
        with self.assertRaises(ValueError):work_vector(vpn(),vpn(),[queue(),queue()],[queue()],10**9)
        with self.assertRaises(ValueError):work_vector(vpn(),vpn(),[],[],0)

    def test_no_traffic_has_no_per_message_estimate(self):
        r=work_vector(vpn(),vpn(),[],[],10**9)
        self.assertIsNone(r['per_source_data_message'])
        self.assertFalse(r['queue_scope_complete_asserted_by_caller'])

    def test_pipeline_stage_delta_mismatch_is_visible(self):
        r=work_vector(vpn(),vpn(10,100,12),[],[],10**9)
        self.assertEqual(r['guaranteed_minus_source_interval_count'],2)
        self.assertTrue(r['warnings'])

    def test_size_fanout_dependence_is_preserved(self):
        # Same source sizes (1,9) and fanouts (1,9); different pairings.
        # Selected queue copy counts total 10 in both cases. Copy bytes differ.
        anti=work_vector(vpn(),vpn(2,10,2),[queue()],[queue(10,18)],10**9)
        mono=work_vector(vpn(),vpn(2,10,2),[queue()],[queue(10,82)],10**9)
        a=anti['per_source_data_message'];m=mono['per_source_data_message']
        self.assertEqual(a['source_data_bytes'],m['source_data_bytes'])
        self.assertEqual(a['selected_queue_copies'],m['selected_queue_copies'])
        self.assertEqual(a['selected_queue_spooled_bytes'],9)
        self.assertEqual(m['selected_queue_spooled_bytes'],41)

    def test_legacy_cache_and_cpu_fields(self):
        s='<rpc-reply><current-cache-usage>9.96</current-cache-usage><max-cache-usage>10</max-cache-usage><disk-messages-currently-spooled>12</disk-messages-currently-spooled></rpc-reply>'
        p='<rpc-reply><processes><process><process-id>1</process-id><command>data</command><cpu-usage>6.0</cpu-usage><cpu-time>1:00</cpu-time></process></processes></rpc-reply>'
        r=legacy_pressure(s,p)
        self.assertEqual(r['cache_fraction_of_reported_limit'],F(249,250))
        self.assertEqual(r['disk_messages_currently_spooled'],12)
        self.assertEqual(r['process_cpu_usage_reported'][0]['cpu_usage_raw'],'6.0')


if __name__=='__main__':unittest.main()
