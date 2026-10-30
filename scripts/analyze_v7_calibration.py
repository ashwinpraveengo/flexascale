#!/usr/bin/env python3
"""
Apply the HPA-tuned calibration rule of docs/POLICY_V7.md §2.1 to the calibration runs.

Runs: reports/experiments/*/run.json with controller hpa_tuned, scenario calibration_steady and a
block label "cal-<target>". A run counts only if it completed >= 95% of its duration from a settled
start and was not host-affected (reports/host_load_by_run.csv from scripts/check_host_load.py;
run that first). The rule: HPA-tuned's CPU target is the highest grid value T for which T and every
lower value meet, on the mean of their valid runs, p95 <= 1.10 x p95(70), mean latency <= 1.10 x
mean(70) and failure rate <= failure(70) + 0.10 pp. Writes reports/v7/calibration.{md,json}.

    python scripts/check_host_load.py && python scripts/analyze_v7_calibration.py
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRID = [70, 150, 250, 350]
MARGIN, FAIL_PP = 1.10, 0.10


def host_flags(path: Path) -> dict:
    flags = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                flags[row["run"]] = (row.get("host_affected"), row.get("reason") or "")
    return flags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(ROOT / "reports" / "experiments"))
    ap.add_argument("--host-load", default=str(ROOT / "reports" / "host_load_by_run.csv"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "v7" / "calibration"))
    ap.add_argument("--prefix", default="cal-", help="block-label prefix of the calibration runs (v9 on the second laptop: v9cal-)")
    args = ap.parse_args()
    flags = host_flags(Path(args.host_load))
    runs = {t: [] for t in GRID}
    excluded = []
    for p in sorted(Path(args.results).glob("*/run.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        req = r.get("request") or {}
        if req.get("controller") != "hpa_tuned" or req.get("scenario") != "calibration_steady":
            continue
        if not str(req.get("block") or "").startswith(args.prefix):
            continue
        t = int(req.get("hpa_cpu_target_pct") or 0)
        s = r.get("summary") or {}
        why = []
        if r.get("state") != "completed" or not s.get("complete"):
            why.append(f"state {r.get('state')}")
        if s.get("settled_start") is False or s.get("reset_check_passed") is False:
            why.append("start not settled")
        hf = flags.get(r["id"])
        if hf is None:
            why.append("no host-load record (run scripts/check_host_load.py)")
        elif hf[0] == "True":
            why.append(f"host-affected: {hf[1]}")
        w = s.get("workload") or {}
        row = {"run": r["id"], "target": t, "p95_ms": w.get("p95_ms"), "mean_ms": w.get("mean_latency_ms"),
               "failure_pct": w.get("failure_rate_pct"), "replica_hours": (s.get("resources") or {}).get("replica_hours"),
               "throughput_rps": w.get("throughput_rps")}
        if why:
            excluded.append({**row, "reason": "; ".join(why)})
        elif t in runs:
            runs[t].append(row)

    means = {}
    for t, rows in runs.items():
        if rows:
            means[t] = {k: sum(x[k] for x in rows) / len(rows) for k in ("p95_ms", "mean_ms", "failure_pct", "replica_hours", "throughput_rps")}
            means[t]["n"] = len(rows)
    lines = ["# HPA-tuned calibration (docs/POLICY_V7.md §2.1)", "",
             "Rule, fixed before any calibration run: HPA-tuned's CPU target is the highest grid value T for which T and every "
             f"lower value meet, on the mean of their valid runs, p95 ≤ {MARGIN:.2f} × p95(70%), mean latency ≤ {MARGIN:.2f} × "
             f"mean(70%) and failure rate ≤ failure(70%) + {FAIL_PP:.2f} pp. Scale-down window 60 s for every value.", "",
             "| CPU target (% of request) | valid runs | p95 ms | mean ms | failures % | replica-h | throughput req/s | meets rule |",
             "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"]
    selected, ok_so_far, missing = 70, True, []
    base = means.get(70)
    for t in GRID:
        m = means.get(t)
        if m is None or m["n"] < 2:
            missing.append(t)
        if not m or not base:
            lines.append(f"| {t} | {m['n'] if m else 0} | – | – | – | – | – | not enough runs |")
            ok_so_far = False
            continue
        meets = (m["p95_ms"] <= MARGIN * base["p95_ms"] and m["mean_ms"] <= MARGIN * base["mean_ms"]
                 and m["failure_pct"] <= base["failure_pct"] + FAIL_PP)
        if t == 70:
            meets = True
        if ok_so_far and meets:
            selected = t
        else:
            ok_so_far = False
        lines.append(f"| {t} | {m['n']} | {m['p95_ms']:.0f} | {m['mean_ms']:.1f} | {m['failure_pct']:.3f} | {m['replica_hours']:.3f} | "
                     f"{m['throughput_rps']:.2f} | {'yes' if meets else 'no'} |")
    lines += ["", f"**Selected HPA-tuned CPU target: {selected}% of request** (scale-down window 60 s)."
              + (f" Values with fewer than 2 valid runs: {missing} (rerun once before the evaluation)." if missing else ""), ""]
    lines += ["Runs used:", ""] + [f"* `{r['run']}` ({r['target']}%)" for t in GRID for r in runs[t]]
    if excluded:
        lines += ["", "Excluded runs:", ""] + [f"* `{r['run']}` ({r['target']}%): {r['reason']}" for r in excluded]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps({"selected_cpu_target_pct": selected, "scale_down_window_s": 60,
                                                    "means": means, "runs": runs, "excluded": excluded,
                                                    "incomplete_targets": missing}, indent=1), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
