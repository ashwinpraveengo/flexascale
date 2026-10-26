#!/usr/bin/env python3
"""
Fit the application twin (src/flexascale/simulator/twin.py) to the live runs of the 16-service shop.

Uses every completed 16-service run in reports/experiments (any controller: these are properties of
the application, not of the controller) and writes config/twin/shopping.json:

* per service: CPU-seconds per request and idle cores per replica (least squares on
  cpu_cores = idle x ready + c x request_rate), low-load mean latency (median at < 15% of the
  CPU limit), CPU limit/request from the policy's Deployments, ``serial`` if a request costs
  more than 50 ms of CPU (bcrypt login);
* edges from the policy topology; fan-out weight of each edge = callee rate / sum of its
  callers' rates (capped at 1);
* per scenario: end-to-end requests per user per second and each service's rate as a fraction
  of the end-to-end rate (medians over samples after the first minute).

    python scripts/fit_twin.py [--out config/twin/shopping.json]
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
sys.path.insert(0, str(ROOT / "src"))

from twin_data import load_runs  # noqa: E402

from flexascale.simulator.twin import AppSpec, ServiceSpec  # noqa: E402

CPU_LIMIT, CPU_REQUEST = 0.5, 0.1   # every HPA'd shop Deployment (kubectl get deploy), checked in the output
CLASS_SERVICES = {  # Locust request classes -> services whose excess latency they inherit
    "login": ["user-service"],
    "checkout": ["order-service"],
    "orders_view": ["order-service"],
    "cart": ["cart-service"],
    "browse": ["catalog-service", "search-service", "review-service", "recommendation-service", "wishlist-service"],
}


def endpoint_class(name: str) -> str:
    if name == "POST /api/users/login":
        return "login"
    if name.startswith("POST /api/orders/checkout"):
        return "checkout"
    if name.startswith("GET /api/orders/user"):
        return "orders_view"
    if "/api/cart" in name:
        return "cart"
    return "browse"


def locust_classes(run_dir: Path):
    """Per class: (requests, request-weighted mean latency ms, request-weighted p95 ms) from locust_stats.csv."""
    import csv
    out = defaultdict(lambda: [0.0, 0.0, 0.0])
    with open(run_dir / "locust_stats.csv") as f:
        for row in csv.DictReader(f):
            if row["Name"] == "Aggregated" or not row.get("Request Count"):
                continue
            n = float(row["Request Count"])
            if n <= 0:
                continue
            c = out[endpoint_class(row["Name"])]
            c[0] += n
            c[1] += n * float(row["Average Response Time"])
            c[2] += n * float(row["95%"] or 0)
    return {k: (v[0], v[1] / v[0], v[2] / v[0]) for k, v in out.items() if v[0] > 0}




def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "config" / "twin" / "shopping.json"))
    ap.add_argument("--policy", default=str(ROOT / "config" / "apps" / "shopping.yaml"))
    args = ap.parse_args()

    samples = defaultdict(list)          # svc -> (rps, ready, cores, lat)
    ratios = defaultdict(lambda: defaultdict(list))
    per_user = defaultdict(list)
    cls_obs = defaultdict(lambda: defaultdict(list))   # scenario -> class -> [(share, mean, p95)]
    n_runs = 0
    for run, rows in load_runs(str(ROOT / "reports" / "experiments")):
        n_runs += 1
        sc = run["request"]["scenario"]
        lc = locust_classes(ROOT / "reports" / "experiments" / run["id"])
        tot = sum(v[0] for v in lc.values())
        for k, (n, mean, p95) in lc.items():
            cls_obs[sc][k].append((n / tot, mean, p95))
        for row in rows:
            for s, v in row["services"].items():
                if None in (v["request_rate"], v["cpu_cores"], v["ready"]) or v["ready"] < 1:
                    continue
                samples[s].append((v["request_rate"], v["ready"], v["cpu_cores"], v["latency_ms"]))
            if row.get("elapsed") is None or row["elapsed"] < 60 or not row.get("rps") or not row.get("users"):
                continue
            per_user[sc].append(row["rps"] / row["users"])
            for s, v in row["services"].items():
                if v["request_rate"] is not None:
                    ratios[sc][s].append(v["request_rate"] / row["rps"])

    services, fit_report = [], {}
    for s in sorted(samples):
        a = np.array([x[:3] for x in samples[s]], dtype=float)
        rps, ready, cores = a.T
        coef, *_ = np.linalg.lstsq(np.c_[ready, rps], cores, rcond=None)
        idle, c = max(0.0, float(coef[0])), max(1e-5, float(coef[1]))
        pred = idle * ready + c * rps
        r2 = 1 - ((cores - pred) ** 2).sum() / ((cores - cores.mean()) ** 2).sum()
        lat = np.array([(x[2] / (x[1] * CPU_LIMIT), x[3]) for x in samples[s] if x[3] is not None], dtype=float)
        low = lat[lat[:, 0] < 0.15, 1] if len(lat) else np.array([])
        base = float(np.median(low)) if len(low) >= 20 else float(np.median(lat[:, 1])) if len(lat) else 10.0
        serial = c > 0.05
        if serial:
            # A serial handler's measured "low-load" latency still contains burst queueing (a 1-minute CPU rate is low
            # while a login burst queues for seconds). The twin models that queue itself, so its base latency is one
            # request served alone at the CPU limit, plus 30 ms of non-CPU work.
            base = 1000.0 * c / CPU_LIMIT + 30.0
        services.append(ServiceSpec(name=s, cpu_per_req=round(c, 6), idle_cores=round(idle, 5), base_latency_ms=round(base, 2),
                                    cpu_limit=CPU_LIMIT, cpu_request=CPU_REQUEST, serial=serial))
        fit_report[s] = {"n": len(samples[s]), "r2": round(float(r2), 3)}

    policy = yaml.safe_load(Path(args.policy).read_text())
    edges = [tuple(e) for e in policy.get("topology") or []]
    mean_rate = {s: float(np.mean([x[0] for x in samples[s]])) for s in samples}
    callers = defaultdict(list)
    for u, v in edges:
        callers[v].append(u)
    fanout = {}
    for u, v in edges:
        tot = sum(mean_rate.get(x, 0.0) for x in callers[v])
        fanout[f"{u}->{v}"] = round(min(1.0, mean_rate.get(v, 0.0) / tot) if tot > 0 else 0.0, 4)

    user_base = next((x.base_latency_ms for x in services if x.name == "user-service"), 450.0)
    scenarios = {}
    for sc in sorted(per_user):
        classes = {}
        for k, obs in sorted(cls_obs[sc].items()):
            a = np.array(obs)
            share, mean, p95 = (float(np.median(a[:, i])) for i in range(3))
            ratio = max(1.05, p95 / mean) if mean > 0 else 2.8
            # lognormal: p95/mean = exp(1.645 s - s^2/2)  ->  solve for s
            sigma = float(np.clip((1.645 - np.sqrt(max(1.645 ** 2 - 2 * np.log(ratio), 0.0))), 0.05, 1.6))
            if k == "login":  # queueing at bcrypt is simulated; the class base is one login served alone
                mean, sigma = user_base + 20.0, 0.3
            classes[k] = {"share": round(share, 5), "base_ms": round(mean, 1), "sigma": round(sigma, 3),
                          "services": CLASS_SERVICES[k]}
        tot = sum(c["share"] for c in classes.values())
        for c in classes.values():
            c["share"] = round(c["share"] / tot, 5)
        scenarios[sc] = {"rps_per_user": round(float(np.median(per_user[sc])), 4),
                         "ratios": {s: round(float(np.median(v)), 4) for s, v in sorted(ratios[sc].items())},
                         "classes": classes, "samples": len(per_user[sc])}
    # Calibration-only workload (never run before the v7 calibration): the 5:5 mix lies between
    # gradual_ramp (6:4) and checkout_heavy-without-flash-sale; use the mean of gradual_ramp and traffic_drop (both 6:4)
    if "calibration_steady" not in scenarios and {"gradual_ramp", "traffic_drop"} <= set(scenarios):
        g, t = scenarios["gradual_ramp"], scenarios["traffic_drop"]
        scenarios["calibration_steady"] = {
            "rps_per_user": round((g["rps_per_user"] + t["rps_per_user"]) / 2, 4),
            "ratios": {s: round((g["ratios"].get(s, 0) + t["ratios"].get(s, 0)) / 2, 4) for s in g["ratios"]},
            "classes": g["classes"],
            "samples": 0, "note": "approximated from gradual_ramp and traffic_drop (same 6:4 mix family); no live samples"}

    app = AppSpec(name="shopping", services=services, edges=edges, fanout=fanout, entry="api-gateway")
    out = app.to_json()
    out["scenarios"] = scenarios
    out["fit"] = {"runs": n_runs, "services": fit_report, "source": "reports/experiments (16-service runs, 2026-10-25/26)"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {args.out} from {n_runs} runs")
    for s in services:
        print(f"  {s.name:24s} c={1000 * s.cpu_per_req:7.2f} ms  idle={1000 * s.idle_cores:5.1f} m  base={s.base_latency_ms:7.1f} ms"
              f"  serial={s.serial}  R2={fit_report[s.name]['r2']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
