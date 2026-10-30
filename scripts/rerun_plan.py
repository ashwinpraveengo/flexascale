#!/usr/bin/env python3
"""
Invalid runs of a finished plan and their one rerun (docs/POLICY_V7.md §3.4).

Reads <plan>.json and <plan>.progress.json (scripts/run_plan.py) and the host-load flags of
scripts/check_host_load.py (run that first). A run is invalid if it did not complete >= 95% of its
duration, did not start settled, or was host-affected; no outcome metric is used. Each invalid run is
moved to reports/experiments_invalid/ and its plan entry is written, in plan order, to
<plan>.reruns.json, which scripts/run_plan.py then runs once. Reruns are never rerun.

    python scripts/check_host_load.py && python scripts/rerun_plan.py reports/v7/calibration_plan.json
"""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invalid_reason(run: dict, flags: dict) -> str:
    s = run.get("summary") or {}
    why = []
    if run.get("state") != "completed" or not s.get("complete"):
        why.append(f"state {run.get('state')}")
    if s.get("settled_start") is False or s.get("reset_check_passed") is False:
        why.append("start not settled")
    hf = flags.get(run["id"])
    if hf is None:
        why.append("no host-load record")
    elif hf[0] == "True":
        why.append(f"host-affected: {hf[1]}")
    return "; ".join(why)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--results", default=str(ROOT / "reports" / "experiments"))
    ap.add_argument("--invalid", default=str(ROOT / "reports" / "experiments_invalid"))
    ap.add_argument("--host-load", default=str(ROOT / "reports" / "host_load_by_run.csv"))
    args = ap.parse_args()
    plan_path = Path(args.plan)
    if plan_path.stem.endswith(".reruns"):
        print("reruns are never rerun (§3.4)", file=sys.stderr)
        return 2
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    progress = json.loads(plan_path.with_suffix(".progress.json").read_text(encoding="utf-8"))
    if len(progress) < len(plan):
        print(f"plan not finished: {len(progress)}/{len(plan)} runs", file=sys.stderr)
        return 2
    flags = {}
    with open(args.host_load, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            flags[row["run"]] = (row.get("host_affected"), row.get("reason") or "")
    results, invalid = Path(args.results), Path(args.invalid)
    reruns = []
    for i, body in enumerate(plan):
        rid = progress[str(i)]["id"]
        src = results / rid if (results / rid).exists() else invalid / rid
        reason = invalid_reason(json.loads((src / "run.json").read_text(encoding="utf-8")), flags)
        if flags.get(rid, ("",))[0] not in ("True", "False"):
            print(f"warning: {rid}: host load unknown (no Prometheus data?); counted as the analyses count it", file=sys.stderr)
        if not reason:
            continue
        if reason == "no host-load record":
            print(f"{rid}: no host-load record; run scripts/check_host_load.py first", file=sys.stderr)
            return 2
        if src.parent == results:
            invalid.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(invalid / rid))
        reruns.append(dict(body, rerun_of=rid))
        print(f"[{i + 1}/{len(plan)}] {rid} ({body.get('block')}): invalid, {reason}; rerun once")
    out = plan_path.with_name(plan_path.stem + ".reruns.json")
    out.write_text(json.dumps(reruns, indent=1), encoding="utf-8")
    print(f"{len(reruns)} rerun(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
