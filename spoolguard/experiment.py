"""Reproduce a fluid-model comparison; no broker or third-party packages needed."""
import json
from fractions import Fraction as F
from pathlib import Path

from spoolguard import plan


def run(config):
    result = plan(config)
    if result["status"] != "certified_under_assumptions":
        raise ValueError(result)
    horizon = F(config["horizon_seconds"])
    pubs = config["publishers"]
    names = [p["name"] for p in pubs]
    demand = {p["name"]: F(p["demand_bps"]) for p in pubs}
    controlled = {n: F(x) for n,x in result["rates_bps_exact"].items()}
    scale = F(1)
    for q,cert in zip(config["queues"], result["certificates"]):
        offered = sum(F(a)*demand[n] for n,a in q["routes"].items())
        budget = F(cert["admissible_ingress_bps_exact"]) - F(q.get("background_bps", 0))
        if offered:
            scale = min(scale, budget/offered)
    policies = {"unregulated": demand,
                "global_throttle": {n:x*scale for n,x in demand.items()},
                "fanout_aware": controlled}
    comparison = {}
    traces = {}
    for policy,rates in policies.items():
        peaks, row_traces = {}, {}
        for q,cert in zip(config["queues"], result["certificates"]):
            initial = F(cert["initial_upper_bound_bytes_exact"])
            burst = F(cert["burst_bytes_exact"])
            ingress = F(q.get("background_bps",0)) + sum(
                F(a)*rates[n] for n,a in q["routes"].items())
            # Scenario uses zero release service, so this trace is an admissible
            # outage trajectory, with the full reserved burst at activation.
            if F(q.get("service_floor_bps",0)) != 0:
                raise ValueError("this experiment specifically models a zero-service outage")
            trace = [initial+burst+ingress*horizon*k/120 for k in range(121)]
            peaks[q["name"]] = {"virtual_peak_bytes": float(max(trace)),
                "excess_over_physical_quota_bytes": float(max(F(0),max(trace)-F(q["capacity_bytes"])))}
            row_traces[q["name"]] = [float(x)/1e6 for x in trace]
        comparison[policy] = {"rates_bps": {n:float(x) for n,x in rates.items()},
                              "aggregate_rate_bps": float(sum(rates.values())),
                              "queue_peaks": peaks}
        traces[policy] = row_traces
    return {"model":"synthetic fluid outage; no live broker measurements",
            "horizon_seconds":float(horizon), "comparison":comparison,
            "gain_over_global_throttle": comparison["fanout_aware"]["aggregate_rate_bps"] /
                                          comparison["global_throttle"]["aggregate_rate_bps"],
            "traces_MB":traces, "certificate":result}


def svg_plot(result):
    """Standalone static research figure; units are decimal MB."""
    colors = {"unregulated":"#c4473a", "global_throttle":"#7b6ab1", "fanout_aware":"#187f72"}
    labels = {"unregulated":"Unregulated", "global_throttle":"Global throttle", "fanout_aware":"Fanout aware"}
    width, height = 900, 470
    bits = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
            '<title id="title">Archive queue during a 30-second consumer outage</title>',
            '<desc id="desc">Synthetic fluid simulation. Fanout-aware and global controls protect the archive quota, while fanout-aware admission preserves the unrelated payments publisher at full demand.</desc>',
            '<rect width="900" height="470" fill="#ffffff"/>',
            '<g font-family="sans-serif" font-size="14" fill="#242424">',
            '<text x="70" y="30" font-size="20">Archive queue during a consumer outage</text>',
            '<text x="70" y="53">Synthetic model · worst-case initial occupancy and full burst</text>']
    def x(t): return 75+float(t)/30*760
    def y(v): return 370-float(v)/210*270
    for v in [0,50,100,150,200]:
        bits += [f'<line x1="75" y1="{y(v)}" x2="835" y2="{y(v)}" stroke="#e0e0e0"/>',
                 f'<text x="60" y="{y(v)+5}" text-anchor="end">{v}</text>']
    for t in [0,5,10,15,20,25,30]:
        bits.append(f'<text x="{x(t)}" y="395" text-anchor="middle">{t}</text>')
    bits += ['<text x="75" y="88">Queue occupancy (MB)</text>', '<text x="835" y="420" text-anchor="end">Seconds after control takes effect</text>']
    for v,label,dash in [(100,"Physical quota 100 MB","6 4"),(90,"Protected ceiling 90 MB","2 4")]:
        bits += [f'<line x1="75" x2="835" y1="{y(v)}" y2="{y(v)}" stroke="#555555" stroke-dasharray="{dash}"/>',
                 f'<text x="830" y="{y(v)-7}" text-anchor="end">{label}</text>']
    for i,policy in enumerate(colors):
        values = result["traces_MB"][policy]["archive"]
        points = ' '.join(f'{x(k/120*30):.2f},{y(v):.2f}' for k,v in enumerate(values))
        dash = ' stroke-dasharray="7 4"' if policy == "global_throttle" else ''
        bits.append(f'<polyline points="{points}" fill="none" stroke="{colors[policy]}" stroke-width="2.5"{dash}/>')
        px=75+i*240
        bits += [f'<line x1="{px}" x2="{px+25}" y1="450" y2="450" stroke="{colors[policy]}" stroke-width="3"{dash}/>',
                 f'<text x="{px+33}" y="455">{labels[policy]}</text>']
    return '\n'.join(bits+['</g></svg>'])


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    config = json.loads((root/"scenario.json").read_text())
    result = run(config)
    (root/"results.json").write_text(json.dumps(result, indent=2)+"\n")
    (root/"queue-outage.svg").write_text(svg_plot(result)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ["traces_MB", "certificate"]}, indent=2))
