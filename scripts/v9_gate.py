#!/usr/bin/env python3
"""
The v9 gate (docs/POLICY_V9.md §5): does the v9 model selected on validation beat v7 on the twin fitted
to this laptop? Both are run on the same 40 validation workloads with the same operator loop, guards and
reward (functions of scripts/train_v7.py); the higher mean validation reward becomes the RL arm.
Writes reports/v9/gate.json. Uses no live result.

    python scripts/v9_gate.py [--training reports/v9/training_v7.json] [--twin config/twin/shopping_v9.json]
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--training", default=str(ROOT / "reports" / "v9" / "training_v7.json"))
    ap.add_argument("--twin", default=str(ROOT / "config" / "twin" / "shopping_v9.json"))
    ap.add_argument("--models-dir", default=str(ROOT / "models" / "flexascale_v9"))
    ap.add_argument("--v7", default=str(ROOT / "models" / "flexascale_v7" / "best_model" / "best_model.zip"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "v9" / "gate.json"))
    args = ap.parse_args()

    import flexascale.rl  # noqa: F401  (Windows checkpoint loading)
    from stable_baselines3 import PPO
    from train_v7 import ModelPolicy, agg, episodes_validation, run_set
    from flexascale.simulator.twin_control import V7_GUARDS, NativeHPA, OperatorLoop  # noqa: F401
    from flexascale.simulator.twin_env import RewardConfig, load_shop

    tr = json.loads(Path(args.training).read_text(encoding="utf-8"))
    sel = tr.get("selected")
    if not sel:
        print("no selected v9 run in", args.training)
        return 1
    app, cal = load_shop(args.twin)
    val = episodes_validation(app, cal)
    cfg = RewardConfig()
    out = {"twin": args.twin, "validation_workloads": len(val), "created": time.strftime("%Y-%m-%d %H:%M:%S"), "candidates": {}}
    for name, path in ((f"v9 ({sel})", Path(args.models_dir) / sel / "best_model.zip"), ("v7 (deployed graph policy)", Path(args.v7))):
        model = PPO.load(str(path), device="cpu")
        a = agg(run_set(val, lambda m=model: OperatorLoop(ModelPolicy(m), V7_GUARDS), cfg))
        out["candidates"][name] = {"path": str(path.relative_to(ROOT)), **a}
        print(f"{name:32s} reward {a['reward']:9.2f} repl-h {a['replica_hours']:.3f} p95 {a['p95_ms']:6.0f} slo {a['slo_violation_s']:5.1f}", flush=True)
    (v9_name, v9), (v7_name, v7) = list(out["candidates"].items())
    out["passed"] = v9["reward"] > v7["reward"]
    out["rl_arm_model"] = v9["path"] if out["passed"] else v7["path"]
    out["rule"] = "docs/POLICY_V9.md §5: v9 becomes the RL arm only if its validation reward beats v7's on the refitted twin"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"gate {'PASSED' if out['passed'] else 'NOT passed'}: RL arm = {out['rl_arm_model']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
