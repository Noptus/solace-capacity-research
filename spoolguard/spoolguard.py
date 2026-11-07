"""Finite-horizon, fanout-aware admission planner. Python 3.10+, standard library.

All decisions use rational arithmetic. This is an offline planner; it neither
connects to a broker nor enforces publisher contracts. See RESEARCH.rst.
"""
from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction as F
from pathlib import Path


def number(value, name="value"):
    if isinstance(value, bool):
        raise ValueError(f"{name}: boolean is not a number")
    try:
        result = F(str(value))
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"{name}: expected a finite number") from None
    if result < 0:
        raise ValueError(f"{name}: must be nonnegative")
    return result


def get(obj, key, default=0):
    return number(obj.get(key, default), key)


def peak_growth(rate, service, latency, horizon):
    """sup_{0 <= u <= H} (R*u - mu*max(u-T, 0))."""
    return max(F(0), rate * min(latency, horizon),
               rate * horizon - service * max(F(0), horizon - latency))


def rate_cap(headroom, service, latency, horizon):
    """Exact inverse of peak_growth for nonnegative headroom and H > 0."""
    if headroom < 0 or horizon <= 0:
        raise ValueError("headroom must be nonnegative and horizon positive")
    cap = (headroom + service * max(F(0), horizon - latency)) / horizon
    if latency > 0:
        cap = min(cap, headroom / min(latency, horizon))
    return cap


def progressive_fill(demand, weights, matrix, caps):
    """Weighted max-min rates under nonnegative linear resource constraints.

    Increase every active x_j at speed weight_j. Freeze a demand-limited
    publisher, or all active publishers using a newly saturated resource.
    """
    n = len(demand)
    rates = [F(0)] * n
    active = set(range(n))
    while active:
        step = min((demand[j] - rates[j]) / weights[j] for j in active)
        for row, cap in zip(matrix, caps):
            slope = sum((row[j] * weights[j] for j in active), F(0))
            if slope:
                used = sum((a * x for a, x in zip(row, rates)), F(0))
                step = min(step, (cap - used) / slope)
        if step < 0:
            raise ValueError("infeasible resource constraints")
        for j in active:
            rates[j] += step * weights[j]
        frozen = {j for j in active if rates[j] == demand[j]}
        for row, cap in zip(matrix, caps):
            if sum((a * x for a, x in zip(row, rates)), F(0)) == cap:
                frozen.update(j for j in active if row[j] > 0)
        if not frozen:
            raise ArithmeticError("progressive filling failed to make progress")
        active -= frozen
    return rates


def exact(value):
    return str(value)


def plan(config):
    horizon = get(config, "horizon_seconds")
    if horizon <= 0:
        raise ValueError("horizon_seconds must be positive")
    publishers = config["publishers"]
    queues = config["queues"]
    if not publishers or not queues:
        raise ValueError("at least one publisher and one queue are required")
    names = [p["name"] for p in publishers]
    qnames = [q["name"] for q in queues]
    if len(set(names)) != len(names) or len(set(qnames)) != len(qnames):
        raise ValueError("publisher and queue names must each be unique")
    if any(not isinstance(x, str) or not x for x in names + qnames):
        raise ValueError("names must be nonempty strings")
    for p in publishers:
        for key in ("demand_bps", "burst_bytes"):
            if key not in p:
                raise ValueError(f"{p['name']}: missing {key}")
    demands = [get(p, "demand_bps") for p in publishers]
    weights = [get(p, "weight", 1) for p in publishers]
    bursts = [get(p, "burst_bytes") for p in publishers]
    if any(w <= 0 for w in weights):
        raise ValueError("publisher weights must be positive")
    matrix, caps, state, errors = [], [], [], []
    for q in queues:
        for key in ("capacity_bytes", "observed_bytes", "reserve_bytes", "age_seconds",
                    "actuation_seconds", "old_ingress_bps", "old_burst_bytes",
                    "measurement_uncertainty_bytes", "in_flight_bytes"):
            if key not in q:
                raise ValueError(f"{q['name']}: missing {key}")
        routes = q["routes"]
        unknown = set(routes) - set(names)
        if unknown:
            raise ValueError(f"{q['name']}: unknown publishers {sorted(unknown)}")
        row = [number(routes.get(name, 0), "route coefficient") for name in names]
        matrix.append(row)
        capacity = get(q, "capacity_bytes")
        if capacity <= 0:
            raise ValueError("capacity_bytes must be positive; last-value queues unsupported")
        ceiling = capacity - get(q, "reserve_bytes")
        blind_seconds = get(q, "age_seconds") + get(q, "actuation_seconds")
        initial = (get(q, "observed_bytes") + get(q, "measurement_uncertainty_bytes")
                   + get(q, "in_flight_bytes") + get(q, "old_burst_bytes")
                   + get(q, "old_ingress_bps") * blind_seconds)
        burst = get(q, "background_burst_bytes") + sum(
            (a * b for a, b in zip(row, bursts)), F(0))
        service = get(q, "service_floor_bps")
        latency = get(q, "service_latency_seconds")
        background = get(q, "background_bps")
        headroom = ceiling - initial - burst
        cap = F(0)
        if headroom < 0:
            errors.append(f"{q['name']}: uncertainty, blind traffic and bursts exceed protected capacity")
        else:
            cap = rate_cap(headroom, service, latency, horizon)
            if cap < background:
                errors.append(f"{q['name']}: background traffic alone exceeds the admissible rate")
        caps.append(max(F(0), cap - background))
        state.append((q, ceiling, initial, burst, service, latency, background, cap))
    for j, name in enumerate(names):
        if not any(row[j] > 0 for row in matrix):
            raise ValueError(f"{name}: no modeled destination; routing coverage is required")
    if errors:
        return {"status": "uncertified", "reasons": errors, "rates_bps_exact": None}
    rates = progressive_fill(demands, weights, matrix, caps)
    certificates = []
    for row, item in zip(matrix, state):
        q, ceiling, initial, burst, service, latency, background, cap = item
        ingress = background + sum((a * x for a, x in zip(row, rates)), F(0))
        peak = initial + burst + peak_growth(ingress, service, latency, horizon)
        if peak > ceiling:
            raise ArithmeticError("internal certificate violation")
        certificates.append({
            "queue": q["name"], "protected_capacity_bytes_exact": exact(ceiling),
            "initial_upper_bound_bytes_exact": exact(initial),
            "burst_bytes_exact": exact(burst), "total_ingress_bps_exact": exact(ingress),
            "admissible_ingress_bps_exact": exact(cap),
            "peak_bound_bytes_exact": exact(peak),
            "margin_bytes_exact": exact(ceiling - peak),
        })
    return {
        "status": "certified_under_assumptions", "horizon_seconds_exact": exact(horizon),
        "rates_bps_exact": dict(zip(names, map(exact, rates))),
        "certificates": certificates,
        "scope": "modeled queue quotas only; no broker/VPN physical spool guarantee",
    }


def read_semp_snapshot(snapshot):
    """Extract measured occupancy, without turning observed rates into guarantees.

    Accepts one queue or one collection page. Does not follow pagination.
    Capacity must be supplied separately in the planner's accounted byte units.
    """
    if snapshot.get("meta", {}).get("responseCode", 200) != 200:
        raise ValueError("SEMP response is not successful")
    if snapshot.get("meta", {}).get("paging", {}).get("nextPageUri"):
        raise ValueError("paginated snapshot: collect all pages before importing")
    data = snapshot["data"]
    if isinstance(data, dict):
        data = [data]
    result = []
    for q in data:
        if get(q, "maxMsgSpoolUsage") == 0:
            raise ValueError("last-value queue or missing quota: unsupported")
        if "msgSpoolUsage" not in q:
            raise ValueError("missing msgSpoolUsage")
        result.append({"name": q["queueName"],
                       "observed_bytes": exact(get(q, "msgSpoolUsage")),
                       "service_floor_bps": "0",
                       "reported_quota_MB": exact(get(q, "maxMsgSpoolUsage")),
                       "observed_rx_bps": exact(get(q, "rxByteRate")),
                       "observed_tx_bps": exact(get(q, "txByteRate"))})
    return {"measurements": result,
            "note": "Supply age, capacity in verified byte units, all traffic envelopes and routing; txByteRate is not a release guarantee."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "import-semp"])
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.input.read_text(), parse_float=str)
        result = plan(config) if args.command == "plan" else read_semp_snapshot(config)
    except (ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 2 if result.get("status") == "uncertified" else 0


if __name__ == "__main__":
    sys.exit(main())
