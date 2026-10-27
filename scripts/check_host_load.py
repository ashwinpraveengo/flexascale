#!/usr/bin/env python3
"""
Host conditions during each live run's load window (docs/POLICY_V6.md §5.2, host-load criterion).

For every completed run in the given result folders, reports the mean host CPU used outside the
Kubernetes containers (Prometheus: node CPU busy minus the container CPU of all pods) and how long
the laptop was on battery during the load window (upower charge history). A run is host-affected
if it was on battery for any part of its load window or the outside load averaged more than 2.0
cores. No outcome metric is used. Also reports the mean CPU clock (node-exporter) of each load window, which
is descriptive (it mostly counts busy cores), and the application's CPU-seconds per Locust request, which shows how
fast the application ran (docs/POLICY_V7.md §3.7). Writes reports/host_load_by_run.csv.

    python scripts/check_host_load.py [--results reports/experiments reports/experiments_invalid ...]
"""

import argparse
import csv
import glob
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Tuple

OUTSIDE_LIMIT_CORES = 2.0
HOST_BUSY = 'sum(increase(node_cpu_seconds_total{{mode!~"idle|iowait|steal"}}[{w}s]))'
K8S_BUSY = 'sum(increase(container_cpu_usage_seconds_total{{container!="",pod!=""}}[{w}s]))'
# mean CPU clock over the load window (descriptive; arms must not differ in it, docs/POLICY_V7.md §5 2026-10-27 19:19)
CPU_MHZ = 'avg(avg_over_time(node_cpu_scaling_frequency_hertz[{w}s])) / 1e6'
# the application's own CPU-seconds in the load window; per Locust request it shows how fast the shop ran (§3.7 parity)
APP_CPU = 'sum(increase(container_cpu_usage_seconds_total{{namespace="{ns}",container!=""}}[{w}s]))'


def battery_intervals(path: Optional[str]) -> Optional[List[Tuple[float, float]]]:
    """Discharging periods from an upower history-charge file (lines: epoch, charge, state)."""
    if not path or not os.path.exists(path):
        return None
    out, start = [], None
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        ts, state = float(parts[0]), parts[2]
        if state == "discharging" and start is None:
            start = ts
        elif state != "discharging" and start is not None:
            out.append((start, ts))
            start = None
    if start is not None:
        out.append((start, float("inf")))
    return out


def default_battery_history() -> Optional[str]:
    # The laptop battery's file; peripherals (Bluetooth MAC in the name) and generic_id are skipped.
    files = [f for f in glob.glob("/var/lib/upower/history-charge-*.dat") if ":" not in f and "generic_id" not in f]
    return max(files, key=os.path.getsize) if files else None


def overlap_s(a: float, b: float, intervals: List[Tuple[float, float]]) -> float:
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in intervals)


def classify(outside_cores: Optional[float], battery_s: Optional[float], limit: float = OUTSIDE_LIMIT_CORES) -> Tuple[Optional[bool], str]:
    reasons = []
    if battery_s:
        reasons.append(f"on battery {battery_s:.0f} s")
    if outside_cores is not None and outside_cores > limit:
        reasons.append(f"{outside_cores:.1f} cores outside Kubernetes")
    if reasons:
        return True, "; ".join(reasons)
    if outside_cores is None or battery_s is None:
        return None, "unknown (no " + ("host CPU data" if outside_cores is None else "battery history") + ")"
    return False, ""


def locust_requests(run_dir: Path) -> Optional[int]:
    try:
        with open(run_dir / "locust_stats.csv") as f:
            return sum(int(r["Request Count"]) for r in csv.DictReader(f) if r.get("Name") != "Aggregated")
    except (OSError, ValueError, KeyError):
        return None


def prometheus_query(url: str) -> Callable[[str, float], Optional[float]]:
    def q(expr: str, at: float) -> Optional[float]:
        full = url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": expr, "time": f"{at:.3f}"})
        try:
            res = json.load(urllib.request.urlopen(full, timeout=20))["data"]["result"]
        except (OSError, ValueError, KeyError):
            return None
        return float(res[0]["value"][1]) if res else None
    return q


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", nargs="+", default=["reports/experiments", "reports/experiments_invalid", "reports/experiments_demo"])
    ap.add_argument("--prometheus-url", default="http://localhost:9090")
    ap.add_argument("--battery-history", default=default_battery_history())
    ap.add_argument("--since", default="", help="only runs whose id starts at or after this prefix (default: all)")
    ap.add_argument("--out", default="reports/host_load_by_run.csv")
    args = ap.parse_args()

    q = prometheus_query(args.prometheus_url)
    battery = battery_intervals(args.battery_history)
    rows = []
    for base in args.results:
        for path in sorted(Path(base).glob("*/run.json")):
            if path.parent.name < args.since:
                continue
            run = json.loads(path.read_text())
            a, b = run.get("started_at"), run.get("ended_at")
            if run.get("state") != "completed" or not a or not b:
                continue
            w = max(1, int(b - a))
            host, k8s = q(HOST_BUSY.format(w=w), b), q(K8S_BUSY.format(w=w), b)
            mhz = q(CPU_MHZ.format(w=w), b)
            app_cpu = q(APP_CPU.format(ns=run.get("namespace") or "flexascale-apps", w=w), b)
            reqs = locust_requests(path.parent)
            outside = (host - k8s) / w if host is not None and k8s is not None else None
            bat = overlap_s(a, b, battery) if battery is not None else None
            affected, reason = classify(outside, bat)
            rows.append({
                "run": run["id"], "folder": base, "controller": run["request"]["controller"], "scenario": run["request"]["scenario"],
                "load_start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(a)), "load_end": time.strftime("%H:%M:%S", time.localtime(b)),
                "host_cores": None if host is None else round(host / w, 2), "k8s_cores": None if k8s is None else round(k8s / w, 2),
                "outside_cores": None if outside is None else round(outside, 2), "battery_s": None if bat is None else round(bat),
                "host_affected": affected, "reason": reason, "cpu_mhz": None if mhz is None else round(mhz),
                "app_cpu_ms_per_request": round(1000 * app_cpu / reqs, 2) if app_cpu is not None and reqs else None,
            })
    rows.sort(key=lambda r: r["load_start"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["run"])
        w.writeheader()
        w.writerows(rows)
    flagged = [r for r in rows if r["host_affected"]]
    unknown = [r for r in rows if r["host_affected"] is None]
    print(f"Wrote {args.out}: {len(rows)} runs, {len(flagged)} host-affected, {len(unknown)} unknown "
          f"(limit {OUTSIDE_LIMIT_CORES} cores outside Kubernetes; battery history: {args.battery_history or 'none'})")
    for r in flagged + unknown:
        print(f"  {r['run']:54s} {r['folder']:28s} {r['reason']}")


if __name__ == "__main__":
    main()
