#!/usr/bin/env python3
"""
Select and evaluate the v4 FlexaScale policy on the dependency-aware simulator.

Protocol (fixed before any v4 result was seen):

The policy controls slot 0 (the caller at the top of a 4-service chain) and is
scored on slot 0; slots 1-3 follow the same HPA-like background rule with
random deviations for every policy ('focal' control, as used live).

1. Selection: every candidate (best and final checkpoint of each seed in
   models/flexascale_v4/seed_*) runs the same 200 episodes on the *validation*
   services. The highest mean reward per step is selected and copied to
   models/flexascale_v4/best_model/ with its model card.
2. Test: the selected model and the baselines run the same 300 episodes on the
   *test* services (disjoint from training and validation services, full
   30-minute episodes). Run once; results are written as produced.

Baselines: hpa_rule (scale up above 77% CPU, down below 63%: native HPA's 70%
target with its 10% tolerance), ppo_v3 (previous deployed model, fed raw-unit
inputs), hold, always_up and random.

    python scripts/evaluate_v4.py [--select-only] [--episodes 300]
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from pathlib import Path

import numpy as np

from flexascale.config.env_config import EnvConfig
from flexascale.simulator.dependency_env import FlexaScaleEnvV2

V4_DIR = Path("models/flexascale_v4")
V3_MODEL = "models/flexascale_v3/best_model/best_model.zip"
WEIGHTS = {"slo": 1.0, "efficiency": 0.3, "stability": 0.1, "cost": 1.0}


def make_env(split: str) -> FlexaScaleEnvV2:
    return FlexaScaleEnvV2(EnvConfig(
        dataset_path="data/processed/alibaba_service_state.csv", split=split, split_method="service",
        service_sampling="random", demand_model="normalized", randomize_initial_replicas=True,
        max_replicas=10, peak_replicas_low=1, peak_replicas_high=4, reward_weights=WEIGHTS, control="focal",
    ))


def model_policy(path: str):
    from stable_baselines3 import PPO

    model = PPO.load(path, device="cpu")
    lo, hi = model.observation_space.low, model.observation_space.high

    def act(obs, info):
        a, _ = model.predict(np.clip(obs, lo, hi), deterministic=True)
        return [int(x) for x in np.asarray(a).flatten()]
    return act


def v3_policy():
    """The previous model, given the raw-unit observation it was trained on."""
    inner = model_policy(V3_MODEL)

    def act(obs, info):
        r = info["raw"]
        v1 = np.concatenate([[r["cpu_pct"][i], r["memory_pct"][i], r["replicas"][i], r["rps"][i], r["latency_ms"][i]]
                             for i in range(len(r["cpu_pct"]))]).astype(np.float32)
        return inner(v1, info)
    return act


def hpa_rule(obs, info):
    return [2 if c > 77 else (0 if c < 63 else 1) for c in info["raw"]["cpu_pct"]]


def run(env: FlexaScaleEnvV2, policy, seed: int, rng: np.random.Generator) -> dict:
    obs, info = env.reset(seed=seed)
    n = env.num_services
    reward = viol = reps = changes = cpu = 0.0
    steps = 0
    event, bottleneck = info["raw"]["traffic_event"], info["raw"]["bottleneck"]
    while True:
        action = policy(obs, info) if policy is not None else list(rng.integers(0, 3, n))
        obs, r, term, _, info = env.step(action)
        if term:
            break
        raw = info["raw"]
        reward += r
        viol += float(info["focal_violation"])
        reps += float(raw["replicas"][0])
        cpu += float(raw["cpu_pct"][0])
        changes += -info["reward_components"]["stability"]
        steps += 1
    return {"seed": seed, "event": event, "bottleneck": bottleneck, "reward": reward / steps,
            "slo_violation_rate": viol / steps, "avg_replicas": reps / steps, "avg_cpu_pct": cpu / steps,
            "replica_changes_per_step": changes / steps}


def evaluate(env, policy, seeds, label):
    rng = np.random.default_rng(0)
    t = time.time()
    rows = [run(env, policy, s, rng) for s in seeds]
    print(f"  {label:<16} {np.mean([r['reward'] for r in rows]):+.4f}  ({time.time() - t:.0f}s)")
    return rows


def mean_ci(x):
    x = np.asarray(x, dtype=float)
    m = float(x.mean())
    half = 1.96 * float(x.std(ddof=1)) / math.sqrt(len(x)) if len(x) > 1 else float("nan")
    return m, half


def select() -> dict:
    env = make_env("val")
    seeds = list(range(10_000, 10_200))
    cands = []
    for d in sorted(p for p in V4_DIR.iterdir() if (p / "model_card.json").is_file() and p.name != "best_model"):
        for name, path in (("best", d / "best_model" / "best_model.zip"), ("final", d / "ppo_flexascale_final.zip")):
            if path.is_file():
                rows = evaluate(env, model_policy(str(path)), seeds, f"{d.name}/{name}")
                cands.append({"candidate": f"{d.name}/{name}", "path": str(path), "seed_dir": str(d),
                              "val_reward": round(float(np.mean([r["reward"] for r in rows])), 4),
                              "val_slo_violation_rate": round(float(np.mean([r["slo_violation_rate"] for r in rows])), 4),
                              "val_avg_replicas": round(float(np.mean([r["avg_replicas"] for r in rows])), 3)})
    if not cands:
        raise SystemExit("no v4 candidates under models/flexascale_v4/")
    best = max(cands, key=lambda c: c["val_reward"])
    out = V4_DIR / "best_model"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(best["path"], out / "best_model.zip")
    card = json.loads((Path(best["seed_dir"]) / "model_card.json").read_text(encoding="utf-8"))
    card["selection"] = {"protocol": "highest mean reward per step on 200 fixed validation-service episodes",
                         "selected": best["candidate"], "candidates": cands}
    (out / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    (V4_DIR / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")  # listed by the dashboard
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
    seeds = list(range(20_000, 20_000 + args.episodes))
    print(f"Test services, {len(seeds)} paired episodes:")
    policies = {
        "ppo_v4": model_policy(str(V4_DIR / "best_model" / "best_model.zip")),
        "hpa_rule": hpa_rule,
        "ppo_v3": v3_policy(),
        "hold": lambda o, i: [1] * len(i["raw"]["cpu_pct"]),
        "always_up": lambda o, i: [2] * len(i["raw"]["cpu_pct"]),
        "random": None,
    }
    results = {name: evaluate(env, pol, seeds, name) for name, pol in policies.items()}

    metrics = ["reward", "slo_violation_rate", "avg_replicas", "avg_cpu_pct", "replica_changes_per_step"]
    summary = {name: {m: mean_ci([r[m] for r in rows]) for m in metrics} for name, rows in results.items()}
    paired = {}
    for other in ("hpa_rule", "ppo_v3"):
        paired[other] = {m: mean_ci([a[m] - b[m] for a, b in zip(results["ppo_v4"], results[other])]) for m in metrics}
    groups = {}
    for key in ("event", "bottleneck"):
        for val in sorted({str(r[key]) for r in results["ppo_v4"]}):
            idx = [i for i, r in enumerate(results["ppo_v4"]) if str(r[key]) == val]
            groups[f"{key}={val}"] = {
                name: {m: float(np.mean([results[name][i][m] for i in idx])) for m in metrics}
                for name in ("ppo_v4", "hpa_rule", "ppo_v3")
            } | {"episodes": len(idx)}

    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "episodes": len(seeds), "reward_weights": WEIGHTS,
           "selection": selection, "summary": summary, "paired_v4_minus": paired, "groups": groups}
    Path("reports").mkdir(exist_ok=True)
    Path("reports/simulation_evaluation_v4.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    f = lambda mc, d=3: f"{mc[0]:.{d}f} ± {mc[1]:.{d}f}"
    L = ["# Simulation Evaluation: v4 policy (dependency-aware simulator)", "",
         f"Generated {out['generated_at']} by `scripts/evaluate_v4.py`. {len(seeds)} paired episodes on the **test services** "
         "(never seen in training or selection), 30 one-minute steps each. Each policy controls the top service of a 4-service "
         "call chain and is scored on it; the downstream services follow the same HPA-like rule with random deviations in "
         "every run. ± is a 95% confidence half-width.", "",
         f"Selected model: `{selection['selected']}` (highest validation reward of {len(selection['candidates'])} candidates, "
         "200 validation-service episodes each).", "",
         "| Policy | Reward / step | SLO violation rate | Avg replicas | Avg CPU % | Replica changes / step |",
         "| :--- | ---: | ---: | ---: | ---: | ---: |"]
    for name, s in summary.items():
        L.append(f"| {name} | {f(s['reward'])} | {f(s['slo_violation_rate'])} | {f(s['avg_replicas'], 2)} | "
                 f"{f(s['avg_cpu_pct'], 1)} | {f(s['replica_changes_per_step'], 2)} |")
    L += ["", "## Paired differences (v4 minus baseline, same episodes)", "",
          "| Baseline | Δ reward | Δ SLO violation rate | Δ avg replicas |", "| :--- | ---: | ---: | ---: |"]
    for other, d in paired.items():
        L.append(f"| {other} | {f(d['reward'])} | {f(d['slo_violation_rate'])} | {f(d['avg_replicas'], 2)} |")
    L += ["", "## By scenario", "", "| Group | Episodes | v4 viol. | HPA viol. | v4 replicas | HPA replicas | v4 reward | HPA reward |",
          "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for g, d in groups.items():
        L.append(f"| {g} | {d['episodes']} | {d['ppo_v4']['slo_violation_rate']:.3f} | {d['hpa_rule']['slo_violation_rate']:.3f} | "
                 f"{d['ppo_v4']['avg_replicas']:.2f} | {d['hpa_rule']['avg_replicas']:.2f} | {d['ppo_v4']['reward']:+.3f} | "
                 f"{d['hpa_rule']['reward']:+.3f} |")
    L += ["", "Reward weights: " + ", ".join(f"{k} {v}" for k, v in WEIGHTS.items()) +
          ". The simulator is a model; live results are in reports/live_benchmark_report.md."]
    Path("reports/simulation_evaluation_v4.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("Wrote reports/simulation_evaluation_v4.{md,json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
