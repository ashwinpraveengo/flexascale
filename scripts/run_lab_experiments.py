#!/usr/bin/env python3
"""
Run a batch of comparable live experiments through the Live Lab API.

Uses exactly the path the dashboard uses (POST /api/lab/experiments), one run
at a time, alternating controllers per scenario, so HPA and FlexaScale runs of
the same scenario are adjacent in time. The lab server must be running
(./scripts/start_review.sh).

    python scripts/run_lab_experiments.py --scenarios flash_sale,steady_browsing --users 40 --duration 300
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8090"


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def wait_for(run_id: str, timeout: float) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        active = call("GET", "/api/lab/experiments/active").get("active") or {}
        if active.get("id") == run_id and active.get("state") in ("completed", "stopped", "failed", "interrupted"):
            return active
        time.sleep(10)
    raise TimeoutError(run_id)


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", default="shopping")
    ap.add_argument("--scenarios", default="flash_sale,steady_browsing,gradual_ramp,checkout_heavy,traffic_drop")
    ap.add_argument("--controllers", default="hpa,flexascale")
    ap.add_argument("--users", type=int, default=40)
    ap.add_argument("--spawn-rate", type=float, default=5.0)
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--base-url", default=BASE)
    args = ap.parse_args()
    BASE = args.base_url.rstrip("/")

    results = []
    for scenario in args.scenarios.split(","):
        for controller in args.controllers.split(","):
            body = {"app": args.app, "controller": controller, "scenario": scenario, "users": args.users,
                    "spawn_rate": args.spawn_rate, "duration": args.duration, "reset_replicas": True,
                    "shadow": True}
            try:
                started = call("POST", "/api/lab/experiments", body)
            except urllib.error.HTTPError as exc:
                print(f"{scenario}/{controller}: refused ({exc.code}) {exc.read().decode()[:200]}", flush=True)
                return 1
            print(f"{time.strftime('%H:%M:%S')} started {started['id']}", flush=True)
            final = wait_for(started["id"], timeout=args.duration + 900)
            s = final.get("summary") or {}
            w = s.get("workload") or {}
            r = s.get("resources") or {}
            print(f"{time.strftime('%H:%M:%S')} {final['state']:<9} {started['id']}  req/s={w.get('throughput_rps')} "
                  f"p95={w.get('p95_ms')} fail%={w.get('failure_rate_pct')} replica_h={r.get('replica_hours')} "
                  f"safe={((final.get('cleanup') or {}).get('safe'))} error={final.get('error')}", flush=True)
            results.append(started["id"])
    print("RUNS " + ",".join(results), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
