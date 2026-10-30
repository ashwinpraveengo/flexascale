#!/usr/bin/env python3
"""
Select and evaluate the v5 FlexaScale policy (protocol: docs/POLICY_V5.md).

1. Selection: every candidate under models/flexascale_v5/<run>/ (warm start,
   best and final checkpoint) runs the same 200 validation-service episodes as
   v4's selection. Highest mean reward per step -> models/flexascale_v5/best_model/.
2. Test: the selected model and the baselines run 300 episodes on the test
   services with fresh seeds 30000-30299 (v4's test used 20000-20299). Run once.

Baselines: hpa_rule, ppo_v4, the threshold rule chosen on validation
(up > 77 / down < 45), hold. "ppo_v5_no_neighbours" is the selected model
with the three neighbour slots replaced by a fixed neutral vector: if it
scores lower than ppo_v5, the policy uses dependency information.

    python scripts/evaluate_v5.py [--select-only] [--episodes 300]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_v4 import WEIGHTS, evaluate, hpa_rule, make_env, mean_ci, model_policy  # noqa: E402

V5_DIR = Path("models/flexascale_v5")
V4_MODEL = "models/flexascale_v4/best_model/best_model.zip"
NEUTRAL = np.array([0.5, 0.3, 0.2, 1.0, 0.5], dtype=np.float32)  # mid CPU, idle-ish, flat trend, half the SLO


def tuned_rule(obs, info):
    return [2 if c > 77 else (0 if c < 45 else 1) for c in info["raw"]["cpu_pct"]]


def no_neighbours(policy):
    def act(obs, info):
        o = np.asarray(obs, dtype=np.float32).copy()
        o[5:] = np.tile(NEUTRAL, (len(o) - 5) // 5)
        return policy(o, info)
    return act


def select() -> dict:
    env = make_env("val")
    seeds = list(range(10_000, 10_200))
    cands = []
    for d in sorted(p for p in V5_DIR.iterdir() if (p / "model_card.json").is_file() and p.name != "best_model"):
        for name, path in (("warm_start", d / "warm_start.zip"), ("best", d / "best_model" / "best_model.zip"),
                           ("final", d / "ppo_flexascale_final.zip")):
            if path.is_file():
                rows = evaluate(env, model_policy(str(path)), seeds, f"{d.name}/{name}")
                cands.append({"candidate": f"{d.name}/{name}", "path": str(path), "seed_dir": str(d),
                              "val_reward": round(float(np.mean([r["reward"] for r in rows])), 4),
                              "val_slo_violation_rate": round(float(np.mean([r["slo_violation_rate"] for r in rows])), 4),
                              "val_avg_replicas": round(float(np.mean([r["avg_replicas"] for r in rows])), 3)})
    if not cands:
        raise SystemExit("no v5 candidates under models/flexascale_v5/")
    best = max(cands, key=lambda c: c["val_reward"])
    out = V5_DIR / "best_model"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(best["path"], out / "best_model.zip")
    card = json.loads((Path(best["seed_dir"]) / "model_card.json").read_text(encoding="utf-8"))
    card["selection"] = {"protocol": "highest mean reward per step on 200 fixed validation-service episodes",
                         "selected": best["candidate"], "candidates": cands}
    (out / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    (V5_DIR / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(f"selected {best['candidate']} -> {out}/best_model.zip")
    return card["selection"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--select-only", action="store_true")
    ap.add_argument("--episodes", type=int, default=300)
    args = ap.parse_args()

    print("Selection on validation services:")
    selection = select()
    if args.select_only:
        return 0

    env = make_env("test")
    seeds = list(range(30_000, 30_000 + args.episodes))
    print(f"Test services, {len(seeds)} paired episodes (fresh seeds):")
    v5 = model_policy(str(V5_DIR / "best_model" / "best_model.zip"))
    policies = {
        "ppo_v5": v5,
        "ppo_v5_no_neighbours": no_neighbours(v5),
        "hpa_rule": hpa_rule,
        "tuned_rule_77_45": tuned_rule,
        "ppo_v4": model_policy(V4_MODEL),
        "hold": lambda o, i: [1] * len(i["raw"]["cpu_pct"]),
    }
    results = {name: evaluate(env, pol, seeds, name) for name, pol in policies.items()}

    metrics = ["reward", "slo_violation_rate", "avg_replicas", "avg_cpu_pct", "replica_changes_per_step"]
    summary = {name: {m: mean_ci([r[m] for r in rows]) for m in metrics} for name, rows in results.items()}
    paired = {other: {m: mean_ci([a[m] - b[m] for a, b in zip(results["ppo_v5"], results[other])]) for m in metrics}
              for other in ("hpa_rule", "tuned_rule_77_45", "ppo_v4", "ppo_v5_no_neighbours")}
    better = {other: float(np.mean([a["reward"] > b["reward"] for a, b in zip(results["ppo_v5"], results[other])]))
              for other in paired}
    groups = {}
    for key in ("event", "bottleneck"):
        for val in sorted({str(r[key]) for r in results["ppo_v5"]}):
            idx = [i for i, r in enumerate(results["ppo_v5"]) if str(r[key]) == val]
            groups[f"{key}={val}"] = {
                name: {m: float(np.mean([results[name][i][m] for i in idx])) for m in metrics}
                for name in ("ppo_v5", "hpa_rule", "tuned_rule_77_45")
            } | {"episodes": len(idx)}

    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "episodes": len(seeds), "seeds": [seeds[0], seeds[-1]],
           "reward_weights": WEIGHTS, "selection": selection, "summary": summary, "paired_v5_minus": paired,
           "episodes_v5_better": better, "groups": groups}
    Path("reports/simulation_evaluation_v5.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    f = lambda mc, d=3: f"{mc[0]:.{d}f} ± {mc[1]:.{d}f}"
    L = ["# Simulation Evaluation: v5 policy (HPA-imitation warm start + PPO)", "",
         f"Generated {out['generated_at']} by `scripts/evaluate_v5.py`. {len(seeds)} paired episodes on the **test services** "
         f"(seeds {seeds[0]}-{seeds[-1]}, fresh; the services were also used for v4's test), 30 one-minute steps each. "
         "Same simulator, reward and scoring as v4. ± is a 95% confidence half-width.", "",
         f"Selected model: `{selection['selected']}` (highest validation reward of {len(selection['candidates'])} candidates, "
         "200 validation-service episodes each).", "",
         "| Policy | Reward / step | SLO violation rate | Avg replicas | Avg CPU % | Replica changes / step |",
         "| :--- | ---: | ---: | ---: | ---: | ---: |"]
    for name, s in summary.items():
        L.append(f"| {name} | {f(s['reward'])} | {f(s['slo_violation_rate'])} | {f(s['avg_replicas'], 2)} | "
                 f"{f(s['avg_cpu_pct'], 1)} | {f(s['replica_changes_per_step'], 2)} |")
    L += ["", "## Paired differences (v5 minus baseline, same episodes)", "",
          "| Baseline | Δ reward | Δ SLO violation rate | Δ avg replicas | Episodes v5 better |",
          "| :--- | ---: | ---: | ---: | ---: |"]
    for other, d in paired.items():
        L.append(f"| {other} | {f(d['reward'])} | {f(d['slo_violation_rate'])} | {f(d['avg_replicas'], 2)} | {better[other]:.0%} |")
    L += ["", "`ppo_v5_no_neighbours`: the same model with its three dependency-graph neighbours replaced by a fixed neutral "
          "vector. A positive Δ reward against it means the policy's decisions use its neighbours' state.", "",
          "## By scenario", "", "| Group | Episodes | v5 reward | HPA reward | tuned-rule reward | v5 replicas | HPA replicas |",
          "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for g, d in groups.items():
        L.append(f"| {g} | {d['episodes']} | {d['ppo_v5']['reward']:+.3f} | {d['hpa_rule']['reward']:+.3f} | "
                 f"{d['tuned_rule_77_45']['reward']:+.3f} | {d['ppo_v5']['avg_replicas']:.2f} | {d['hpa_rule']['avg_replicas']:.2f} |")
    L += ["", "Reward weights: " + ", ".join(f"{k} {v}" for k, v in WEIGHTS.items()) +
          ". The simulator is a model; live results are in reports/live_benchmark_report.md."]
    Path("reports/simulation_evaluation_v5.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("Wrote reports/simulation_evaluation_v5.{md,json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
