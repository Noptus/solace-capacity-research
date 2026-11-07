import copy
import json
import random
import unittest
from fractions import Fraction as F
from pathlib import Path

from spoolguard import number, peak_growth, plan, progressive_fill, rate_cap, read_semp_snapshot


def config(capacity=100, observed=0, service=0, latency=0, horizon=10):
    return {"horizon_seconds": horizon,
            "publishers": [{"name": "p", "demand_bps": 100, "burst_bytes": 0}],
            "queues": [{"name": "q", "capacity_bytes": capacity,
                        "observed_bytes": observed, "reserve_bytes": 0,
                        "age_seconds": 0, "actuation_seconds": 0,
                        "old_ingress_bps": 0, "old_burst_bytes": 0,
                        "measurement_uncertainty_bytes": 0, "in_flight_bytes": 0,
                        "service_floor_bps": service, "service_latency_seconds": latency,
                        "routes": {"p": 1}}]}


class Bounds(unittest.TestCase):
    def test_zero_service_outage(self):
        c = config(observed=60)
        self.assertEqual(plan(c)["rates_bps_exact"]["p"], "4")

    def test_stale_data_actuation_and_bursts(self):
        c = config()
        q = c["queues"][0]
        q.update(age_seconds=2, actuation_seconds=1, old_ingress_bps=10,
                 old_burst_bytes=5, in_flight_bytes=3, measurement_uncertainty_bytes=2)
        c["publishers"][0]["burst_bytes"] = 10
        self.assertEqual(plan(c)["rates_bps_exact"]["p"], "5")

    def test_peak_before_horizon(self):
        # At u=5 the initial service stall fills the entire available 10 bytes.
        # Checking only u=10 would wrongly permit 51 bytes/second.
        self.assertEqual(rate_cap(F(10), F(100), F(5), F(10)), F(2))

    def test_service_exceeds_arrival_and_can_release_initial_backlog(self):
        c = config(observed=90, service=100, latency=0)
        self.assertEqual(plan(c)["rates_bps_exact"]["p"], "100")

    def test_latency_beyond_horizon_gives_no_service_credit(self):
        self.assertEqual(rate_cap(F(100), F(1000), F(20), F(10)), F(10))

    def test_infeasible_burst_is_not_silently_clamped(self):
        c = config(observed=95)
        c["publishers"][0]["burst_bytes"] = 6
        self.assertEqual(plan(c)["status"], "uncertified")

    def test_zero_headroom_can_admit_immediate_service_only(self):
        self.assertEqual(rate_cap(F(0), F(10), F(0), F(10)), F(10))
        self.assertEqual(rate_cap(F(0), F(10), F(1), F(10)), F(0))

    def test_background_traffic_reserves_capacity(self):
        c = config()
        c["queues"][0].update(background_bps=2, background_burst_bytes=10)
        self.assertEqual(plan(c)["rates_bps_exact"]["p"], "7")
        c["queues"][0]["background_bps"] = 10
        self.assertEqual(plan(c)["status"], "uncertified")

    def test_random_exact_inverse_and_tightness(self):
        rng = random.Random(7001)
        for _ in range(2000):
            head, mu, latency, horizon = map(F, [rng.randrange(10000),
                rng.randrange(1000), rng.randrange(100), rng.randrange(1, 100)])
            cap = rate_cap(head, mu, latency, horizon)
            self.assertEqual(peak_growth(cap, mu, latency, horizon), head)
            self.assertGreater(peak_growth(cap + F(1, 1000000), mu, latency, horizon), head)
            # Independent dense grid verifies the analytic endpoint maximum.
            grid = max(cap * horizon * k / 100 - mu * max(F(0), horizon*k/100-latency)
                       for k in range(101))
            self.assertLessEqual(grid, head)

    def test_random_token_bucket_queue_trajectories(self):
        # Independent event simulation: bursts at integer times, latency starts
        # on each new busy period, then constant work-conserving release.
        rng = random.Random(7003)
        for _ in range(500):
            horizon = 30
            initial, burst, mu, latency = map(F, [rng.randrange(100),
                rng.randrange(1,100), rng.randrange(20), rng.randrange(10)])
            head = F(rng.randrange(100))
            rate = rate_cap(head, mu, latency, F(horizon)) * F(rng.randrange(101),100)
            ceiling = initial + burst + head
            backlog, tokens, wait = initial, burst, latency
            for t in range(horizon+1):
                if t:
                    tokens = min(burst, tokens+rate)
                arrival = tokens * F(rng.randrange(101),100)
                tokens -= arrival
                if backlog == 0 and arrival > 0:
                    wait = latency
                backlog += arrival
                self.assertLessEqual(backlog, ceiling)
                available = F(1) - min(F(1),wait)
                wait = max(F(0),wait-1)
                backlog = max(F(0),backlog-mu*available)


class Allocation(unittest.TestCase):
    def test_weighted_fairness_and_isolation(self):
        rates = progressive_fill([F(100)]*3, [F(2), F(1), F(1)],
                                 [[F(1), F(1), F(0)]], [F(30)])
        self.assertEqual(rates, [F(20), F(10), F(100)])

    def test_multiple_bottlenecks_and_demand_limit(self):
        rates = progressive_fill([F(3), F(100), F(100)], [F(1)]*3,
                                 [[F(1),F(1),F(0)], [F(0),F(1),F(1)]], [F(10),F(20)])
        self.assertEqual(rates, [F(3),F(7),F(13)])

    def test_random_network_feasibility_and_pareto_saturation(self):
        rng = random.Random(7002)
        for _ in range(1000):
            n, m = rng.randrange(1, 10), rng.randrange(1, 8)
            rows = [[F(rng.randrange(4)) for j in range(n)] for i in range(m)]
            caps = [F(rng.randrange(200)) for i in range(m)]
            demand = [F(rng.randrange(100)) for j in range(n)]
            weights = [F(rng.randrange(1, 5)) for j in range(n)]
            rates = progressive_fill(demand, weights, rows, caps)
            used = [sum(a*x for a,x in zip(row,rates)) for row in rows]
            self.assertTrue(all(F(0) <= x <= d for x,d in zip(rates,demand)))
            self.assertTrue(all(u <= cap for u,cap in zip(used,caps)))
            for j,x in enumerate(rates):
                if x < demand[j]:
                    self.assertTrue(any(row[j] and u == cap
                                        for row,u,cap in zip(rows,used,caps)))

    def test_nonunit_route_coefficients_cover_overhead(self):
        c = config()
        c["queues"][0]["routes"]["p"] = "3/2"
        self.assertEqual(F(plan(c)["rates_bps_exact"]["p"]), F(20,3))

    def test_sample_certificate(self):
        c = json.loads(Path(__file__).with_name("scenario.json").read_text())
        result = plan(c)
        self.assertEqual(result["rates_bps_exact"]["payments"], "2000000")
        self.assertEqual(F(result["rates_bps_exact"]["orders"]), F(1000000,3))
        self.assertEqual(result["certificates"][0]["peak_bound_bytes_exact"], "90000000")


class Validation(unittest.TestCase):
    def test_invalid_numbers(self):
        for value in [True, float("inf"), float("nan"), -1, "1/0"]:
            with self.assertRaises(ValueError):
                number(value)

    def test_missing_blind_rate_is_rejected(self):
        c = config()
        del c["queues"][0]["old_ingress_bps"]
        with self.assertRaises(ValueError):
            plan(c)

    def test_uncovered_publisher_and_unknown_route(self):
        for routes in [{}, {"typo": 1}]:
            c = config()
            c["queues"][0]["routes"] = routes
            with self.assertRaises(ValueError):
                plan(c)

    def test_duplicate_names_and_invalid_horizon(self):
        c = config()
        c["publishers"].append(copy.deepcopy(c["publishers"][0]))
        with self.assertRaises(ValueError): plan(c)
        for horizon in [0,-1]:
            with self.assertRaises(ValueError): plan(config(horizon=horizon))

    def test_semp_uses_documented_field_and_never_credits_transmission(self):
        result = read_semp_snapshot({"data": {"queueName":"q", "msgSpoolUsage":42,
                                   "maxMsgSpoolUsage":10, "txByteRate":999999}})
        self.assertEqual(result["measurements"][0]["observed_bytes"], "42")
        self.assertEqual(result["measurements"][0]["service_floor_bps"], "0")

    def test_semp_last_value_missing_occupancy_and_pagination(self):
        for snapshot in [{"data":{"maxMsgSpoolUsage":0}},
                         {"data":{"maxMsgSpoolUsage":1}},
                         {"meta":{"responseCode":500}, "data":[]},
                         {"meta":{"paging":{"nextPageUri":"next"}}, "data":[]}]:
            with self.assertRaises(ValueError): read_semp_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
