"""v9 against v7 on the held-out twin test sets (descriptive; added 2026-10-30 after the v9 evaluation).

The gate (scripts/v9_gate.py) compared them on the validation set v9 was selected on, which favours v9.
Here both models run the test sets T1-T3 of scripts/train_v7.py (seeds 40000+, 50000+, 60000+, never used for
training or selection of either model) with the same operator loop, guards and reward, on this laptop's twin
(shopping_v9.json, v9's training twin) and on the first laptop's (shopping.json, v7's). Paired by episode,
Δ = v9 − v7, 95% t-intervals. No verdict and no rule: v9 is already the RL arm by the gate.

    python scripts/analysis/v9_vs_v7.py   # writes reports/v9/v9_vs_v7.{md,json}
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import flexascale.rl  # noqa: F401,E402  (Windows checkpoint loading)
from stable_baselines3 import PPO  # noqa: E402
from train_v7 import ModelPolicy, agg, episodes_test, run_set  # noqa: E402

from flexascale.lab.benchmark import mean_ci  # noqa: E402
from flexascale.simulator.twin_control import V7_GUARDS, OperatorLoop  # noqa: E402
from flexascale.simulator.twin_env import RewardConfig, load_shop  # noqa: E402

REPORT = ROOT / "reports/v9"
TWINS = {"this laptop (v9 twin)": ROOT / "config/twin/shopping_v9.json", "first laptop (v7 twin)": ROOT / "config/twin/shopping.json"}
MODELS = {"v9": ROOT / "models/flexascale_v9/best_model/best_model.zip", "v7": ROOT / "models/flexascale_v7/best_model/best_model.zip"}
KEYS = (("reward", "reward", "{:+.3f}"), ("replica_hours", "replica-h", "{:+.4f}"), ("p95_ms", "p95 ms", "{:+.1f}"),
        ("slo_violation_s", "SLO violation s", "{:+.2f}"))


def main() -> int:
    cfg = RewardConfig()
    models = {n: PPO.load(str(p), device="cpu") for n, p in MODELS.items()}
    out = {"models": {n: str(p.relative_to(ROOT)) for n, p in MODELS.items()}, "twins": {}}
    lines = ["# v9 against v7 on the held-out twin test sets (descriptive)", "",
             "Added after the v9 evaluation; not pre-registered and not a gate. Both deployed models "
             f"(`{out['models']['v9']}`, `{out['models']['v7']}`) run the test sets of `scripts/train_v7.py` (never used to train or "
             "select either) with the same operator loop, guards (V7_GUARDS) and v7 reward, on each laptop's twin. "
             "Δ = v9 − v7 per episode; 95% t-intervals. Reward: higher is better; replica-h, p95 and SLO violation: lower is better.", ""]
    for tname, tpath in TWINS.items():
        app, cal = load_shop(str(tpath))
        sets = episodes_test(app, cal)
        out["twins"][tname] = {}
        lines += [f"## {tname}", "", "| Test set | episodes | v9 reward | v7 reward | " + " | ".join(f"Δ {h} [95% CI]" for _, h, _ in KEYS) + " |",
                  "| :--- | ---: | ---: | ---: | " + " | ".join(":---" for _ in KEYS) + " |"]
        for sname, eps in sets.items():
            rows = {n: run_set(eps, lambda m=m: OperatorLoop(ModelPolicy(m), V7_GUARDS), cfg) for n, m in models.items()}
            res = {"aggregate": {n: agg(r) for n, r in rows.items()}, "delta": {}}
            cells = []
            for k, _, f in KEYS:
                c = mean_ci([a[k] - b[k] for a, b in zip(rows["v9"], rows["v7"])])
                res["delta"][k] = c
                lo, hi = c["ci95"]
                cells.append(f"{f.format(c['mean'])} [{f.format(lo)} … {f.format(hi)}]")
            out["twins"][tname][sname] = res
            lines.append(f"| {sname} | {len(eps)} | {res['aggregate']['v9']['reward']:.3f} | {res['aggregate']['v7']['reward']:.3f} | "
                         + " | ".join(cells) + " |")
            print(lines[-1], flush=True)
        lines.append("")
    (REPORT / "v9_vs_v7.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    (REPORT / "v9_vs_v7.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", REPORT / "v9_vs_v7.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
