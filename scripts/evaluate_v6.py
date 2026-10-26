#!/usr/bin/env python3
"""
Select and evaluate the v6 FlexaScale policy (protocol: docs/POLICY_V6.md).

Simulator: FlexaScaleEnvV3 (15 s control loop, pod start-up delay, 1-minute
CPU lag, the live operator's guards, native-HPA neighbours).

1. Selection: every candidate under models/flexascale_v6/<run>/ (warm start,
   best and final checkpoint) runs 200 validation-service episodes (seeds
   10000-10199). Highest mean reward per step -> models/flexascale_v6/best_model/.
2. Test: the selected model and the baselines run paired episodes on the test
   services with fresh seeds 40000-40299. Run once.

Baselines:
* native_hpa: slot 0 is scaled by the native HPA algorithm (70% target, 10%
  tolerance, scale-up limit, 5-minute scale-down stabilisation), without the
  operator's guards: the controller FlexaScale replaces on the cluster.
* hpa_ratio_rule: the warm-start teacher (HPA's ratio rule, stateless) under the
  operator's guards.
* ppo_v5: the v5 model, its -1/0/+1 actions mapped onto the same delta set.
* ppo_v6_no_neighbours: the selected model with its three neighbour slots
  replaced by a fixed neutral vector (dependency-information ablation).
* hold.

    python scripts/evaluate_v6.py [--select-only] [--episodes 300]
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from flexascale.config.env_config import EnvConfig  # noqa: E402
from flexascale.rl.imitation import ratio_teacher  # noqa: E402
from flexascale.simulator.control_env import FlexaScaleEnvV3  # noqa: E402

V6_DIR = Path("models/flexascale_v6")
V5_MODEL = "models/flexascale_v5/best_model/best_model.zip"
WEIGHTS = {"slo": 1.0, "efficiency": 0.3, "stability": 0.1, "cost": 1.0}
NEUTRAL = np.array([0.5, 0.3, 0.2, 1.0, 0.5], dtype=np.float32)  # mid CPU, idle-ish, flat trend, half the SLO


def make_env(split: str) -> FlexaScaleEnvV3:
    return FlexaScaleEnvV3(EnvConfig(
        dataset_path="data/processed/alibaba_service_state.csv", split=split, split_method="service",
        service_sampling="random", demand_model="normalized", randomize_initial_replicas=True,
        max_replicas=10, peak_replicas_low=1, peak_replicas_high=4, reward_weights=WEIGHTS, control="focal",
    ))


def model_policy(path: str, deltas):
    """A PPO model as a policy over the env's delta set (models with other deltas are mapped)."""
    from stable_baselines3 import PPO

    model = PPO.load(path, device="cpu")
    lo, hi = model.observation_space.low, model.observation_space.high
    n_actions = int(model.action_space.nvec[0])
    own = list(deltas) if n_actions == len(deltas) else [-1, 0, 1]
    index = {d: i for i, d in enumerate(deltas)}

    def act(obs, env):
        a, _ = model.predict(np.clip(obs, lo, hi), deterministic=True)
        return [index[own[int(x)]] for x in np.asarray(a).flatten()]
    return act


def no_neighbours(policy):
    def act(obs, env):
        o = np.asarray(obs, dtype=np.float32).copy()
        o[5:] = np.tile(NEUTRAL, (len(o) - 5) // 5)
        return policy(o, env)
    return act


def teacher_policy(deltas):
    t = ratio_teacher(deltas, 10)
    return lambda obs, env: [int(x) for x in t(obs)]


def run(env: FlexaScaleEnvV3, policy, seed: int, controller: str = "agent") -> dict:
    obs, info = env.reset(seed=seed, options={"slot0_controller": controller})
    hold = int(np.where(env.deltas == 0)[0][0])
    reward = viol = reps = changes = cpu = blocked = 0.0
    steps = 0
    event, bottleneck = info["raw"]["traffic_event"], info["raw"]["bottleneck"]
    while True:
        action = policy(obs, env) if policy is not None else [hold] * env.num_services
        obs, r, term, _, info = env.step(action)
        if term:
            break
        raw = info["raw"]
        reward += r
        viol += float(info["focal_violation"])
        reps += float(raw["replicas"][0])
        cpu += float(raw["cpu_true"][0])
        changes += -info["reward_components"]["stability"]
        blocked += float(info.get("guard", "accepted") != "accepted")
        steps += 1
    return {"seed": seed, "event": event, "bottleneck": bottleneck, "reward": reward / steps,
            "slo_violation_rate": viol / steps, "avg_replicas": reps / steps, "avg_cpu_pct": cpu / steps,
            "replica_changes_per_step": changes / steps, "guard_blocked_rate": blocked / steps}


def evaluate(env, policy, seeds, label, controller="agent"):
    t = time.time()
    rows = [run(env, policy, s, controller) for s in seeds]
    print(f"  {label:<22} {np.mean([r['reward'] for r in rows]):+.4f}  ({time.time() - t:.0f}s)", flush=True)
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
    for d in sorted(p for p in V6_DIR.iterdir() if (p / "model_card.json").is_file() and p.name != "best_model"):
        for name, path in (("warm_start", d / "warm_start.zip"), ("best", d / "best_model" / "best_model.zip"),
                           ("final", d / "ppo_flexascale_final.zip")):
            if path.is_file():
                rows = evaluate(env, model_policy(str(path), env.deltas), seeds, f"{d.name}/{name}")
                cands.append({"candidate": f"{d.name}/{name}", "path": str(path), "seed_dir": str(d),
                              "val_reward": round(float(np.mean([r["reward"] for r in rows])), 4),
                              "val_slo_violation_rate": round(float(np.mean([r["slo_violation_rate"] for r in rows])), 4),
                              "val_avg_replicas": round(float(np.mean([r["avg_replicas"] for r in rows])), 3)})
    if not cands:
        raise SystemExit("no v6 candidates under models/flexascale_v6/")
    hpa_rows = evaluate(env, None, seeds, "native_hpa (reference)", controller="hpa")
    best = max(cands, key=lambda c: c["val_reward"])
    out = V6_DIR / "best_model"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(best["path"], out / "best_model.zip")
    card = json.loads((Path(best["seed_dir"]) / "model_card.json").read_text())
    card["selection"] = {"protocol": "highest mean reward per step on 200 fixed validation-service episodes (FlexaScaleEnvV3)",
                         "selected": best["candidate"], "candidates": cands,
                         "native_hpa_val_reward": round(float(np.mean([r["reward"] for r in hpa_rows])), 4)}
    (out / "model_card.json").write_text(json.dumps(card, indent=2))
    (V6_DIR / "model_card.json").write_text(json.dumps(card, indent=2))
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
    seeds = list(range(40_000, 40_000 + args.episodes))
    print(f"Test services, {len(seeds)} paired episodes (fresh seeds):")
    v6 = model_policy(str(V6_DIR / "best_model" / "best_model.zip"), env.deltas)
    runs = {
        "ppo_v6": (v6, "agent"),
        "ppo_v6_no_neighbours": (no_neighbours(v6), "agent"),
        "native_hpa": (None, "hpa"),
        "hpa_ratio_rule": (teacher_policy(env.deltas), "agent"),
        "ppo_v5": (model_policy(V5_MODEL, env.deltas), "agent"),
        "hold": (None, "agent"),
    }
    results = {name: evaluate(env, pol, seeds, name, ctrl) for name, (pol, ctrl) in runs.items()}

    metrics = ["reward", "slo_violation_rate", "avg_replicas", "avg_cpu_pct", "replica_changes_per_step", "guard_blocked_rate"]
    summary = {name: {m: mean_ci([r[m] for r in rows]) for m in metrics} for name, rows in results.items()}
    others = ("native_hpa", "hpa_ratio_rule", "ppo_v5", "ppo_v6_no_neighbours")
    paired = {o: {m: mean_ci([a[m] - b[m] for a, b in zip(results["ppo_v6"], results[o])]) for m in metrics} for o in others}
    better = {o: float(np.mean([a["reward"] > b["reward"] for a, b in zip(results["ppo_v6"], results[o])])) for o in others}
    groups = {}
    for key in ("event", "bottleneck"):
        for val in sorted({str(r[key]) for r in results["ppo_v6"]}):
            idx = [i for i, r in enumerate(results["ppo_v6"]) if str(r[key]) == val]
            groups[f"{key}={val}"] = {
                name: {m: float(np.mean([results[name][i][m] for i in idx])) for m in metrics}
                for name in ("ppo_v6", "native_hpa", "ppo_v5")
            } | {"episodes": len(idx)}

    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "episodes": len(seeds), "seeds": [seeds[0], seeds[-1]],
           "reward_weights": WEIGHTS, "selection": selection, "summary": summary, "paired_v6_minus": paired,
           "episodes_v6_better": better, "groups": groups}
    Path("reports/simulation_evaluation_v6.json").write_text(json.dumps(out, indent=2))

    f = lambda mc, d=3: f"{mc[0]:.{d}f} ± {mc[1]:.{d}f}"
    L = ["# Simulation Evaluation: v6 policy (control-loop simulator)", "",
         f"Generated {out['generated_at']} by `scripts/evaluate_v6.py`. {len(seeds)} paired episodes on the **test services** "
         f"(seeds {seeds[0]}-{seeds[-1]}, fresh), 120 decisions of 15 s each (30 minutes of trace). Simulator: "
         "`FlexaScaleEnvV3` (pod start-up delay, 1-minute CPU lag, the operator's guards, native-HPA neighbours). "
         "± is a 95% confidence half-width.", "",
         f"Selected model: `{selection['selected']}` (highest validation reward of {len(selection['candidates'])} candidates, "
         f"200 validation-service episodes each; native HPA on the same episodes: {selection['native_hpa_val_reward']:+.4f}).", "",
         "| Policy | Reward / step | SLO violation rate | Avg replicas | Avg CPU % | Replica changes / step | Guard-blocked / step |",
         "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, s in summary.items():
        L.append(f"| {name} | {f(s['reward'])} | {f(s['slo_violation_rate'])} | {f(s['avg_replicas'], 2)} | "
                 f"{f(s['avg_cpu_pct'], 1)} | {f(s['replica_changes_per_step'], 2)} | {f(s['guard_blocked_rate'], 2)} |")
    L += ["", "## Paired differences (v6 minus baseline, same episodes)", "",
          "| Baseline | Δ reward | Δ SLO violation rate | Δ avg replicas | Episodes v6 better |",
          "| :--- | ---: | ---: | ---: | ---: |"]
    for o, d in paired.items():
        L.append(f"| {o} | {f(d['reward'])} | {f(d['slo_violation_rate'])} | {f(d['avg_replicas'], 2)} | {better[o]:.0%} |")
    L += ["", "`native_hpa` is the Kubernetes HPA algorithm without FlexaScale's guards. `ppo_v6_no_neighbours`: the same "
          "model with its three dependency-graph neighbours replaced by a fixed neutral vector.", "",
          "## By scenario", "", "| Group | Episodes | v6 reward | native HPA reward | v5 reward | v6 replicas | HPA replicas |",
          "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for g, d in groups.items():
        L.append(f"| {g} | {d['episodes']} | {d['ppo_v6']['reward']:+.3f} | {d['native_hpa']['reward']:+.3f} | "
                 f"{d['ppo_v5']['reward']:+.3f} | {d['ppo_v6']['avg_replicas']:.2f} | {d['native_hpa']['avg_replicas']:.2f} |")
    L += ["", "Reward weights: " + ", ".join(f"{k} {v}" for k, v in WEIGHTS.items()) +
          ". The simulator is a model; live results are in reports/live_benchmark_report.md."]
    Path("reports/simulation_evaluation_v6.md").write_text("\n".join(L) + "\n")
    print("Wrote reports/simulation_evaluation_v6.{md,json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
