#!/usr/bin/env python3
"""
Idle host baseline for the host-load validity rule on Windows/Docker Desktop (docs/POLICY_V9.md §4).

Run with the lab, port-forwards and tunnel up and **no experiment or other work running**. Samples the
whole machine's busy CPU (psutil, includes the WSL2 VM that runs Minikube) every 5 s and, over the same
window, the CPU of all Kubernetes containers (Prometheus, pod-level fallback). Writes
reports/v9/host_baseline.json with ``idle_outside_cores`` = mean(host) - k8s and
``limit_cores`` = idle_outside_cores + 2.0, which scripts/check_host_load.py uses for runs that carry
psutil host samples.

    python scripts/measure_host_baseline.py [--seconds 180]
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import psutil

K8S = ('sum(increase(container_cpu_usage_seconds_total{{container!="",pod!=""}}[{w}s]))'
       ' or sum(increase(container_cpu_usage_seconds_total{{container="",pod!=""}}[{w}s]))')
MARGIN_CORES = 2.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--prometheus-url", default="http://localhost:9090")
    ap.add_argument("--out", default="reports/v9/host_baseline.json")
    args = ap.parse_args()
    psutil.cpu_percent(None)
    t0 = time.time()
    cores = []
    while time.time() - t0 < args.seconds:
        time.sleep(5)
        cores.append(psutil.cpu_percent(None) / 100.0 * psutil.cpu_count())
    t1 = time.time()
    w = int(t1 - t0)
    url = args.prometheus_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": K8S.format(w=w), "time": f"{t1:.3f}"})
    res = json.load(urllib.request.urlopen(url, timeout=20))["data"]["result"]
    k8s = float(res[0]["value"][1]) / w if res else None
    host = sum(cores) / len(cores)
    bat = psutil.sensors_battery()
    out = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": w, "samples": len(cores),
        "host_cores_mean": round(host, 3), "host_cores_max": round(max(cores), 3), "k8s_cores": None if k8s is None else round(k8s, 3),
        "idle_outside_cores": None if k8s is None else round(host - k8s, 3),
        "limit_cores": None if k8s is None else round(host - k8s + MARGIN_CORES, 3),
        "on_ac": bat.power_plugged if bat else None, "logical_cpus": psutil.cpu_count(),
        "rule": "docs/POLICY_V9.md §4: host-affected if mean(host) - k8s over the load window > limit_cores",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if k8s is not None else 1


if __name__ == "__main__":
    sys.exit(main())
