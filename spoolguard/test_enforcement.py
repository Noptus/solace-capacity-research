import unittest
from fractions import Fraction as F

from enforcement import ExpiringBucket, audit_events


class Enforcement(unittest.TestCase):
    def test_fractional_rate_never_rounds_early(self):
        b=ExpiringBucket("1/3",1,0,10_000_000_000)
        self.assertTrue(b.acquire(1,0))
        self.assertFalse(b.acquire(1,2_999_999_999))
        self.assertEqual(b.wait_ns(1,2_999_999_999),1)
        self.assertTrue(b.acquire(1,3_000_000_000))

    def test_exact_expiry_denies_even_a_funded_message(self):
        b=ExpiringBucket(100,100,100,200)
        self.assertFalse(b.acquire(1,99))
        self.assertTrue(b.acquire(1,100))
        self.assertFalse(b.acquire(1,200))
        self.assertIsNone(b.wait_ns(1,200))

    def test_wait_before_activation(self):
        b=ExpiringBucket(1,1,100,200)
        self.assertEqual(b.wait_ns(1,50),50)

    def test_idle_time_cannot_accumulate_unbounded_bursts(self):
        b=ExpiringBucket(10,10,0,100_000_000_001)
        self.assertTrue(b.acquire(10,100_000_000_000))
        self.assertFalse(b.acquire(1,100_000_000_000))

    def test_zero_rate_spends_only_initial_burst(self):
        b=ExpiringBucket(0,10,0,100_000_000_000)
        self.assertTrue(b.acquire(10,0))
        self.assertIsNone(b.wait_ns(1,1))
        self.assertFalse(b.acquire(1,99_000_000_000))

    def test_next_message_cannot_be_scheduled_at_or_after_expiry(self):
        b=ExpiringBucket(1,1,0,1_000_000_000)
        b.acquire(1,0)
        self.assertIsNone(b.wait_ns(1,0))

    def test_backwards_clock_fails(self):
        b=ExpiringBucket(1,1,0,100)
        b.acquire(1,50)
        with self.assertRaises(ValueError): b.acquire(1,49)

    def test_invalid_message_cost_and_clock(self):
        b=ExpiringBucket(1,1,0,100)
        for cost in [0,2,-1,True]:
            with self.assertRaises(ValueError): b.acquire(cost,0)
        with self.assertRaises(ValueError): b.acquire(1,1.5)

    def test_audit_rejects_forged_trace(self):
        events=[{"send_ns":0,"payload_bytes":10},
                {"send_ns":1_000_000_000,"payload_bytes":10}]
        self.assertEqual(audit_events(events,10,10,0,2_000_000_000),20)
        events[1]["send_ns"]-=1
        with self.assertRaises(ValueError): audit_events(events,10,10,0,2_000_000_000)

    def test_all_intervals_of_admitted_trace(self):
        # Independent pairwise envelope check, including idle refill limits.
        b=ExpiringBucket("13/7",3,0,50_000_000_000)
        events=[]
        for t in range(500):
            now=t*100_000_000
            if b.acquire(1,now): events.append(now)
        for i,left in enumerate(events):
            for j in range(i,len(events)):
                self.assertLessEqual(j-i+1,F(3)+F(13,7)*F(events[j]-left,1_000_000_000))


if __name__ == "__main__":
    unittest.main()
