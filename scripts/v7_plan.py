#!/usr/bin/env python3
"""
Write the pre-registered run plans of docs/POLICY_V7.md as JSON (deterministic, seeds from the document).

    python scripts/v7_plan.py calibration   -> reports/v7/calibration_plan.json  (§2.1: 4 CPU targets x 2 runs, seed 7)
    python scripts/v7_plan.py evaluation    -> reports/v7/evaluation_plan.json   (§3.3: 12 blocks, arm order seed 2610+block)
    python scripts/v7_plan.py spike         -> reports/v7/spike_plan.json        (§3.6: flash_sale, 10 blocks, seed 2710+block)
    python scripts/v7_plan.py replication   -> reports/v7/replication_plan.json  (§3.7: 12 blocks, 4 arms, seed 2810+block)

Each entry is the body of POST /api/lab/experiments; scripts/run_plan.py executes a plan.
"""

import argparse
import json
import random
import sys
from pathlib import Path

COMMON = {"app": "shopping", "users": 25, "spawn_rate": 5.0, "duration": 300, "reset_replicas": True, "shadow": True}
SCENARIOS = ["steady_browsing", "checkout_heavy", "payment_degradation", "flash_sale", "gradual_ramp", "traffic_drop"]
CAL_TARGETS = [70, 150, 250, 350]
CAL_WINDOW_S = 60
SPIKE_ARMS = ("hpa_tuned", "rl", "heuristic")
SPIKE_BLOCKS = 10
REPLICATION_ARMS = ("hpa_tuned", "rl", "auto", "heuristic")


def calibration() -> list:
    order = [t for t in CAL_TARGETS for _ in range(2)]
    random.Random(7).shuffle(order)
    return [{**COMMON, "controller": "hpa_tuned", "scenario": "calibration_steady", "hpa_cpu_target_pct": t,
             "hpa_scale_down_window_s": CAL_WINDOW_S, "block": f"cal-{t}"} for t in order]


def evaluation(arms: dict) -> list:
    """arms: name -> request fields (controller, policy_variant, ...), in the §3.2 order."""
    plan, block = [], 0
    for repeat in (1, 2):
        for scenario in SCENARIOS:
            block += 1
            names = list(arms)
            random.Random(2610 + block).shuffle(names)
            for name in names:
                plan.append({**COMMON, **arms[name], "scenario": scenario, "block": f"v7-b{block:02d}-{name}"[:64]})
    return plan


def spike(arms: dict) -> list:
    """§3.6: flash_sale only; HPA-tuned, FlexaScale-RL and the heuristic arm in each block."""
    plan = []
    for block in range(1, SPIKE_BLOCKS + 1):
        names = [a for a in arms if a in SPIKE_ARMS]
        random.Random(2710 + block).shuffle(names)
        for name in names:
            plan.append({**COMMON, **arms[name], "scenario": "flash_sale", "block": f"v7s-b{block:02d}-{name}"})
    return plan


def replication(arms: dict) -> list:
    """§3.7: the §3.3 design (6 scenarios x 2 repeats) without HPA-default, a new order seed, labels v7r-bNN-<arm>."""
    plan, block = [], 0
    for repeat in (1, 2):
        for scenario in SCENARIOS:
            block += 1
            names = [a for a in arms if a in REPLICATION_ARMS]
            random.Random(2810 + block).shuffle(names)
            for name in names:
                plan.append({**COMMON, **arms[name], "scenario": scenario, "block": f"v7r-b{block:02d}-{name}"})
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("which", choices=["calibration", "evaluation", "spike", "replication"])
    ap.add_argument("--arms", help="evaluation: JSON file mapping arm name -> request fields")
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.which == "calibration":
        plan, out = calibration(), args.out or "reports/v7/calibration_plan.json"
    else:
        if not args.arms:
            ap.error(f"{args.which} needs --arms")
        arms = json.loads(Path(args.arms).read_text(encoding="utf-8"))
        build = {"evaluation": evaluation, "spike": spike, "replication": replication}[args.which]
        plan, out = build(arms), args.out or f"reports/v7/{args.which}_plan.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(plan)} runs")
    for i, p in enumerate(plan, 1):
        print(f"  {i:2d} {p['scenario']:20s} {p['controller']:10s} {p.get('policy_variant') or '':14s} "
              f"{p.get('hpa_cpu_target_pct') or '':>4} {p['block']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
