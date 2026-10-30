#!/usr/bin/env python3
"""
Execute a pre-registered run plan (JSON list of POST /api/lab/experiments bodies) through the lab API.

One run at a time, in plan order. Progress is kept in <plan>.progress.json, so an interrupted batch
resumes where it stopped. Before each run the script waits while the laptop is on battery (on battery
the CPU slows down ~4x and the run would be invalid anyway, docs/POLICY_V6.md §5.2). Validity is
checked afterwards with scripts/check_host_load.py; nothing here looks at outcomes. With
``--pause-file``, no new run starts while that file exists (CPU-heavy work such as model training
creates it, so it cannot overlap a run and count as host load). With ``--suspend``, processes whose
command line matches the pattern are frozen (SIGSTOP) while a run's load is on and resumed (SIGCONT)
when it ends, so CPU-heavy work can use the 5.5-minute settle waits between runs without becoming
host load in the measured window.

    systemd-inhibit --what=sleep:idle:handle-lid-switch python scripts/run_plan.py reports/v7/calibration_plan.json
"""

import argparse
import atexit
import glob
import json
import os
import signal
import subprocess
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


def keep_awake() -> None:
    """Windows: ask the OS not to sleep while this runner lives (the equivalent of the systemd-inhibit wrapper
    used on Linux). Changes no setting; the request ends with the process.

    ES_DISPLAY_REQUIRED is essential on Modern Standby (S0 low-power idle) laptops: there the display timing
    out *is* entering standby, which ES_SYSTEM_REQUIRED alone does not prevent. Measured 2026-10-29: with only
    ES_SYSTEM_REQUIRED the laptop entered Modern Standby 21 s into a calibration run's load window
    (System log, Kernel-Power 506 at 00:00:50, 507 at 00:39:11; docs/POLICY_V9.md §8)."""
    if sys.platform != "win32":
        return
    import ctypes

    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
    if ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED):
        log("Windows: sleep and display-off (Modern Standby) inhibited while the plan runs")


def on_battery() -> bool:
    try:  # cross-platform (Windows has no /sys/class/power_supply)
        import psutil

        bat = psutil.sensors_battery()
        if bat is not None and bat.power_plugged is not None:
            return not bat.power_plugged
    except Exception:
        pass
    for f in glob.glob("/sys/class/power_supply/BAT*/status"):
        try:
            if Path(f).read_text(encoding="utf-8").strip() == "Discharging":
                return True
        except OSError:
            pass
    return False


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


FROZEN = set()


def matching_pids(pattern):
    """PIDs whose full command line matches the regex (like `pgrep -f`), never this process. psutil, so it
    also works on Windows, where there is no pgrep and no SIGSTOP/SIGCONT."""
    if not pattern:
        return []
    import re

    import psutil

    rx = re.compile(pattern)
    out = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
        except (psutil.Error, TypeError):
            continue
        if proc.info["pid"] != os.getpid() and cmd and rx.search(cmd):
            out.append(proc.info["pid"])
    return out


def freeze(pattern):
    import psutil

    for pid in matching_pids(pattern):
        try:
            psutil.Process(pid).suspend()  # SIGSTOP on POSIX, NtSuspendProcess on Windows
            FROZEN.add(pid)
        except psutil.Error:
            pass


def thaw():
    import psutil

    for pid in list(FROZEN):
        try:
            psutil.Process(pid).resume()
        except psutil.Error:
            pass
        FROZEN.discard(pid)


atexit.register(thaw)


def wait_for(run_id, timeout, suspend=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        active = (call("GET", "/api/lab/experiments/active") or {}).get("active") or {}
        state = active.get("state")
        if active.get("id") == run_id and state in ("completed", "stopped", "failed", "interrupted"):
            thaw()
            return active
        if suspend and active.get("id") == run_id:
            # freeze from the end of the replica reset (last 15 s of preparation) until the run ends
            events = active.get("events") or []
            settling = any("Comparable start" in (e.get("message") or "") or "start not fully settled" in (e.get("message") or "")
                           for e in events)
            if state in ("running", "stopping") or settling:
                if not FROZEN:
                    log(f"freezing processes matching '{suspend}' for the load window")
                freeze(suspend)
            elif FROZEN:
                thaw()
        time.sleep(2 if suspend else 10)
    raise TimeoutError(run_id)


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--base-url", default=BASE)
    ap.add_argument("--pause-file", default=".runtime/pause_live_runs",
                    help="do not start a run while this file exists (default: %(default)s)")
    ap.add_argument("--suspend", default=None,
                    help="command-line pattern of processes to freeze while a run's load is on (e.g. scripts/train_v7.py)")
    args = ap.parse_args()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(1))  # atexit resumes anything frozen
    BASE = args.base_url.rstrip("/")
    keep_awake()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    prog_path = Path(args.plan).with_suffix(".progress.json")
    progress = json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.exists() else {}
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
        final = wait_for(started["id"], timeout=body.get("duration", 300) + 1200, suspend=args.suspend)
        s = final.get("summary") or {}
        w, r = s.get("workload") or {}, s.get("resources") or {}
        progress[key] = {"id": started["id"], "state": final["state"], "block": body.get("block")}
        prog_path.write_text(json.dumps(progress, indent=1), encoding="utf-8")
        log(f"[{i + 1}/{len(plan)}] {final['state']} {started['id']} p95={w.get('p95_ms')} mean={w.get('mean_latency_ms') and round(w['mean_latency_ms'], 1)} "
            f"fail%={w.get('failure_rate_pct') and round(w['failure_rate_pct'], 3)} replica_h={r.get('replica_hours')} "
            f"safe={(final.get('cleanup') or {}).get('safe')} error={final.get('error')}")
    log("plan complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
