#!/usr/bin/env python3
"""
Run a CPU-heavy command (tests, analyses) without it becoming host load in a live run's load window.

The command runs in its own process group, which is stopped (SIGSTOP) from a lab run's comparable start
until the run ends and continued (SIGCONT) afterwards: the window and the rule of scripts/run_plan.py
--suspend, read from the lab API. Outside load above 2.0 cores makes a run invalid (docs/POLICY_V7.md §3.4).

    python scripts/lab_quiet.py -- python -m pytest -q
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

BASE = os.environ.get("FLEXASCALE_LAB_URL", "http://127.0.0.1:8090")


def in_load_window() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/api/lab/experiments/active", timeout=10) as resp:
            active = (json.loads(resp.read() or b"null") or {}).get("active") or {}
    except OSError:
        return False  # no lab: nothing to protect
    if active.get("state") in ("running", "stopping"):
        return True
    return active.get("state") == "preparing" and any(
        "Comparable start" in (e.get("message") or "") or "start not fully settled" in (e.get("message") or "")
        for e in active.get("events") or [])


def main() -> int:
    cmd = sys.argv[1:]
    if cmd[:1] == ["--"]:
        cmd = cmd[1:]
    if not cmd:
        print(__doc__, file=sys.stderr)
        return 2
    while in_load_window():
        time.sleep(2)
    proc = subprocess.Popen(cmd, start_new_session=True)
    stopped = False
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda s, _: (os.killpg(proc.pid, signal.SIGCONT), os.killpg(proc.pid, s)))
    while proc.poll() is None:
        want = in_load_window()
        if want != stopped:
            os.killpg(proc.pid, signal.SIGSTOP if want else signal.SIGCONT)
            print(f"lab_quiet: {time.strftime('%H:%M:%S')} {'paused for a load window' if want else 'resumed'}", file=sys.stderr, flush=True)
            stopped = want
        time.sleep(1)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
