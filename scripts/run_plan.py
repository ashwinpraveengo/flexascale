#!/usr/bin/env python3
"""
Execute a pre-registered run plan (JSON list of POST /api/lab/experiments bodies) through the lab API.

One run at a time, in plan order. Progress is kept in <plan>.progress.json, so an interrupted batch
resumes where it stopped. Before each run the script waits while the laptop is on battery (on battery
the CPU slows down ~4x and the run would be invalid anyway, docs/POLICY_V6.md §5.2). Validity is
checked afterwards with scripts/check_host_load.py; nothing here looks at outcomes. With
``--pause-file``, no new run starts while that file exists (CPU-heavy work such as model training
creates it, so it cannot overlap a run and count as host load).

    systemd-inhibit --what=sleep:idle:handle-lid-switch python scripts/run_plan.py reports/v7/calibration_plan.json
"""

import argparse
import glob
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8090"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def on_battery() -> bool:
    for f in glob.glob("/sys/class/power_supply/BAT*/status"):
        try:
            if Path(f).read_text().strip() == "Discharging":
                return True
        except OSError:
            pass
    return False


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def wait_for(run_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        active = (call("GET", "/api/lab/experiments/active") or {}).get("active") or {}
        if active.get("id") == run_id and active.get("state") in ("completed", "stopped", "failed", "interrupted"):
            return active
        time.sleep(10)
    raise TimeoutError(run_id)


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--base-url", default=BASE)
    ap.add_argument("--pause-file", default=".runtime/pause_live_runs",
                    help="do not start a run while this file exists (default: %(default)s)")
    args = ap.parse_args()
    BASE = args.base_url.rstrip("/")
    plan = json.loads(Path(args.plan).read_text())
    prog_path = Path(args.plan).with_suffix(".progress.json")
    progress = json.loads(prog_path.read_text()) if prog_path.exists() else {}
    log(f"plan {args.plan}: {len(plan)} runs, {len(progress)} already done")
    for i, body in enumerate(plan):
        key = str(i)
        if key in progress:
            continue
        while on_battery() or Path(args.pause_file).exists():
            log("on battery: waiting for AC power before the next run" if on_battery()
                else f"paused by {args.pause_file} (CPU-heavy work running); waiting")
            time.sleep(60)
        while True:
            try:
                started = call("POST", "/api/lab/experiments", body)
                break
            except urllib.error.HTTPError as exc:
                text = exc.read().decode()[:300]
                if exc.code == 409:  # another run still finishing: wait, never interfere
                    log(f"lab busy ({text}); retrying in 60 s")
                    time.sleep(60)
                    continue
                log(f"run {i + 1} refused ({exc.code}): {text}")
                return 1
        log(f"[{i + 1}/{len(plan)}] started {started['id']} ({body['controller']}, {body['scenario']}, block {body.get('block')})")
        final = wait_for(started["id"], timeout=body.get("duration", 300) + 1200)
        s = final.get("summary") or {}
        w, r = s.get("workload") or {}, s.get("resources") or {}
        progress[key] = {"id": started["id"], "state": final["state"], "block": body.get("block")}
        prog_path.write_text(json.dumps(progress, indent=1))
        log(f"[{i + 1}/{len(plan)}] {final['state']} {started['id']} p95={w.get('p95_ms')} mean={w.get('mean_latency_ms') and round(w['mean_latency_ms'], 1)} "
            f"fail%={w.get('failure_rate_pct') and round(w['failure_rate_pct'], 3)} replica_h={r.get('replica_hours')} "
            f"safe={(final.get('cleanup') or {}).get('safe')} error={final.get('error')}")
    log("plan complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
