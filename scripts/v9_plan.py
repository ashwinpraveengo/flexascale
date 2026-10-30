#!/usr/bin/env python3
"""
Write the pre-registered v9 run plans (docs/POLICY_V9.md §3, §5) as JSON. Same designs as v7
(scripts/v7_plan.py), re-run on the Windows/GPU laptop with their own labels and order seeds, so no
run of the earlier laptop can be mixed in.

    python scripts/v9_plan.py calibration                       -> reports/v9/calibration_plan.json (4 targets x 2, seed 9)
    python scripts/v9_plan.py evaluation --arms reports/v9/arms.json -> reports/v9/evaluation_plan.json (12 blocks, seed 2910+block)

Each entry is the body of POST /api/lab/experiments; scripts/run_plan.py executes a plan.
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v7_plan import CAL_TARGETS, CAL_WINDOW_S, COMMON, SCENARIOS  # noqa: E402  (identical settings)


def calibration() -> list:
    order = [t for t in CAL_TARGETS for _ in range(2)]
    random.Random(9).shuffle(order)
    return [{**COMMON, "controller": "hpa_tuned", "scenario": "calibration_steady", "hpa_cpu_target_pct": t,
             "hpa_scale_down_window_s": CAL_WINDOW_S, "block": f"v9cal-{t}"} for t in order]


def evaluation(arms: dict) -> list:
    plan, block = [], 0
    for _repeat in (1, 2):
        for scenario in SCENARIOS:
            block += 1
            names = list(arms)
            random.Random(2910 + block).shuffle(names)
            for name in names:
                plan.append({**COMMON, **arms[name], "scenario": scenario, "block": f"v9-b{block:02d}-{name}"[:64]})
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("which", choices=["calibration", "evaluation"])
    ap.add_argument("--arms", help="evaluation: JSON file mapping arm name -> request fields")
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.which == "calibration":
        plan, out = calibration(), args.out or "reports/v9/calibration_plan.json"
    else:
        if not args.arms:
            ap.error("evaluation needs --arms")
        plan, out = evaluation(json.loads(Path(args.arms).read_text(encoding="utf-8"))), args.out or "reports/v9/evaluation_plan.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(plan)} runs")
    for i, p in enumerate(plan, 1):
        print(f"  {i:2d} {p['scenario']:20s} {p['controller']:10s} {p.get('policy_variant') or '':14s} "
              f"{p.get('hpa_cpu_target_pct') or '':>4} {p['block']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
