"""Monotonic-clock byte shaper with a fixed activation and expiry.

One bucket belongs to one publisher stream. Calls must be serialized by its
owner. It is a scheduling primitive, not an interceptor for arbitrary clients.
"""
from fractions import Fraction as F

from spoolguard import number

NANOSECONDS = 1_000_000_000


class ExpiringBucket:
    def __init__(self, rate_bps, burst_bytes, start_ns, expiry_ns):
        self.rate = number(rate_bps, "rate_bps")
        self.capacity = number(burst_bytes, "burst_bytes")
        if type(start_ns) is not int or type(expiry_ns) is not int:
            raise ValueError("start and expiry must be integer monotonic nanoseconds")
        if start_ns < 0 or expiry_ns <= start_ns:
            raise ValueError("expiry must be after a nonnegative activation time")
        self.start_ns, self.expiry_ns = start_ns, expiry_ns
        self.last_ns = start_ns
        self.tokens = self.capacity

    def _advance(self, now_ns):
        if type(now_ns) is not int:
            raise ValueError("time must be integer monotonic nanoseconds")
        if now_ns < self.start_ns:
            return False
        if now_ns < self.last_ns:
            raise ValueError("clock moved backwards")
        self.tokens = min(self.capacity,
                          self.tokens + self.rate * F(now_ns-self.last_ns, NANOSECONDS))
        self.last_ns = now_ns
        return now_ns < self.expiry_ns

    def acquire(self, cost_bytes, now_ns):
        """Spend tokens only if active, unexpired, and sufficiently funded."""
        cost = number(cost_bytes, "cost_bytes")
        if cost <= 0 or cost > self.capacity:
            raise ValueError("message cost must be positive and fit the burst capacity")
        if not self._advance(now_ns) or self.tokens < cost:
            return False
        self.tokens -= cost
        return True

    def wait_ns(self, cost_bytes, now_ns):
        """Nanoseconds until eligible, or None if impossible before expiry."""
        cost = number(cost_bytes, "cost_bytes")
        if cost <= 0 or cost > self.capacity:
            raise ValueError("message cost must be positive and fit the burst capacity")
        if now_ns < self.start_ns:
            return self.start_ns-now_ns
        if not self._advance(now_ns):
            return None
        deficit = max(F(0),cost-self.tokens)
        if deficit and not self.rate:
            return None
        exact_wait = deficit*NANOSECONDS/self.rate if deficit else F(0)
        wait = -(-exact_wait.numerator//exact_wait.denominator)
        return wait if now_ns+wait < self.expiry_ns else None


def audit_events(events, rate_bps, burst_bytes, start_ns, expiry_ns):
    """Recheck a recorded send trace against the same exact traffic contract.

    Each event supplies send_ns and payload_bytes. This audits source sends;
    it does not prove a broker-arrival envelope or complete instrumentation.
    """
    bucket = ExpiringBucket(rate_bps,burst_bytes,start_ns,expiry_ns)
    total = 0
    for i,event in enumerate(events):
        if not bucket.acquire(event["payload_bytes"],event["send_ns"]):
            raise ValueError(f"event {i} violates the source contract")
        total += event["payload_bytes"]
    return total
