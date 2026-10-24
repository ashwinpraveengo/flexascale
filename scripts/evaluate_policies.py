#!/usr/bin/env python3
"""
Held-out simulation evaluation of FlexaScale policies.

Every policy is run on the *same* episodes (same seeds -> same sampled
services, demand scaling and initial replicas) from the held-out test split,
so differences are paired. The validation split was used only for checkpoint
selection during training; the test split is never seen during training.

Policies:
    ppo_v2_best   models/flexascale_v2/best_model/best_model.zip
    ppo_v2_final  models/flexascale_v2/ppo_flexascale_final.zip
    ppo_v3_best   models/flexascale_v3/best_model/best_model.zip (reward + 0.5 x allocation cost)
    ppo_v3_final  models/flexascale_v3/ppo_flexascale_final.zip
    ppo_legacy    models/best_model/best_model.zip (trained on fraction-unit data)
    hpa_rule      scale up if CPU > 77%, down if < 63% (HPA-like, target 70%)
    hold          never scale
    random        uniform random actions

Outputs reports/simulation_evaluation.json and reports/simulation_evaluation.md.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

from flexascale.config.env_config import EnvConfig
from flexascale.simulator.flexascale_env import FlexaScaleEnv


COST_WEIGHT = 0.5
"""Cost weight used by the v3 training reward; reported as a second reward definition."""


def hpa_rule(obs: np.ndarray, n: int) -> list[int]:
    return [2 if obs[i * 5] > 77 else (0 if obs[i * 5] < 63 else 1) for i in range(n)]


def make_model_policy(path: str):
    from stable_baselines3 import PPO

    model = PPO.load(path, device="cpu")
    low, high = model.observation_space.low, model.observation_space.high

    def act(obs: np.ndarray, n: int) -> list[int]:
        a, _ = model.predict(np.clip(obs, low, high), deterministic=True)
        return [int(x) for x in np.asarray(a).flatten()]

    return act, int(getattr(model, "num_timesteps", 0))


def run_episode(env: FlexaScaleEnv, policy, seed: int, rng: np.random.Generator) -> dict:
    obs, _ = env.reset(seed=seed)
    n = env.num_services
    total = total_cost_aware = 0.0
    steps = slo_viol = scale_actions = changes = 0
    reps = cpu = 0.0
    target = env.config.latency_target_ms
    while True:
        action = policy(obs, n) if policy is not None else list(rng.integers(0, 3, n))
        scale_actions += sum(1 for a in action if a != 1)
        obs, reward, term, _, info = env.step(action)
        if term:
            break
        comp = info["reward_components"]
        base = comp["slo"] + 0.3 * comp["efficiency"] + 0.1 * comp["stability"]
        total += base
        total_cost_aware += base + COST_WEIGHT * comp["cost"]
        changes += int(-comp["stability"] * n > 0)
        steps += 1
        o = obs.reshape(n, 5)
        slo_viol += int((o[:, 4] > target).sum())
        reps += float(o[:, 2].mean())
        cpu += float(o[:, 0].mean())
    return {
        "reward": total,
        "reward_cost_aware": total_cost_aware,
        "slo_violation_rate": slo_viol / max(1, steps * n),
        "avg_replicas": reps / max(1, steps),
        "avg_cpu_pct": cpu / max(1, steps),
        "scale_actions_per_step": scale_actions / max(1, steps),
    }


def summarize(rows: list[dict]) -> dict:
    out = {}
    for key in rows[0]:
        vals = np.array([r[key] for r in rows], dtype=float)
        out[key] = {"mean": float(vals.mean()), "std": float(vals.std(ddof=1)),
                    "ci95": float(1.96 * vals.std(ddof=1) / math.sqrt(len(vals)))}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default="reports/simulation_evaluation")
    args = ap.parse_args()

    cfg = EnvConfig(split=args.split, service_sampling="random", demand_model="normalized",
                    max_replicas=10, randomize_initial_replicas=True)
    env = FlexaScaleEnv(cfg)

    policies = {}
    for name, path in (("ppo_v2_best", "models/flexascale_v2/best_model/best_model.zip"),
                       ("ppo_v2_final", "models/flexascale_v2/ppo_flexascale_final.zip"),
                       ("ppo_v3_best", "models/flexascale_v3/best_model/best_model.zip"),
                       ("ppo_v3_final", "models/flexascale_v3/ppo_flexascale_final.zip"),
                       ("ppo_legacy", "models/best_model/best_model.zip")):
        if Path(path).is_file():
            act, steps = make_model_policy(path)
            policies[name] = {"fn": act, "path": path, "timesteps": steps}
    policies["hpa_rule"] = {"fn": hpa_rule}
    policies["hold"] = {"fn": lambda o, n: [1] * n}
    policies["random"] = {"fn": None}

    seeds = list(range(10_000, 10_000 + args.episodes))
    results = {}
    per_episode = {}
    started = time.time()
    for name, spec in policies.items():
        rng = np.random.default_rng(0)
        rows = [run_episode(env, spec["fn"], s, rng) for s in seeds]
        per_episode[name] = [r["reward"] for r in rows]
        results[name] = {"summary": summarize(rows), **{k: v for k, v in spec.items() if k != "fn"}}
        print(f"{name:<13} reward {results[name]['summary']['reward']['mean']:+.3f} "
              f"+/- {results[name]['summary']['reward']['ci95']:.3f}")

    paired = {}
    base = np.array(per_episode["hpa_rule"])
    for name, rewards in per_episode.items():
        if name == "hpa_rule":
            continue
        diff = np.array(rewards) - base
        paired[name] = {"mean_diff_vs_hpa_rule": float(diff.mean()),
                        "ci95": float(1.96 * diff.std(ddof=1) / math.sqrt(len(diff))),
                        "win_rate": float((diff > 0).mean())}

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "episodes": args.episodes,
        "split": args.split,
        "seeds": [seeds[0], seeds[-1]],
        "env": {"service_sampling": "random", "demand_model": "normalized", "max_replicas": 10,
                "randomize_initial_replicas": True, "num_services": cfg.num_services,
                "episode_steps": env.episode_length - 1, "latency_target_ms": cfg.latency_target_ms,
                "cpu_target_pct": cfg.cpu_target_pct, "reward_weights": cfg.reward_weights},
        "results": results,
        "paired_vs_hpa_rule": paired,
        "runtime_seconds": round(time.time() - started, 1),
    }
    Path(args.out + ".json").write_text(json.dumps(report, indent=2))

    lines = [
        "# Held-out Simulation Evaluation",
        "",
        f"Generated {report['generated_at']} by `scripts/evaluate_policies.py`. "
        f"{args.episodes} paired episodes on the **{args.split}** split (never used for training or checkpoint selection).",
        "",
        "Environment: 4 services sampled at random per episode from the Alibaba v2021 trace, normalized demand model "
        "(replica range 1-10), random initial replicas. Original reward = SLO + 0.3 x CPU-efficiency + 0.1 x stability; "
        "cost-aware reward adds 0.5 x (-replicas/max_replicas) "
        f"(latency target {cfg.latency_target_ms:.0f} ms, CPU target {cfg.cpu_target_pct:.0f}%).",
        "",
        "| Policy | Reward (original) | Reward (+0.5 x cost) | Latency-SLO violation rate | Avg replicas | Avg CPU % | Scale actions / step |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, r in results.items():
        s = r["summary"]
        lines.append(
            f"| {name} | {s['reward']['mean']:+.3f} +/- {s['reward']['ci95']:.3f} | "
            f"{s['reward_cost_aware']['mean']:+.3f} +/- {s['reward_cost_aware']['ci95']:.3f} | {100 * s['slo_violation_rate']['mean']:.1f}% | "
            f"{s['avg_replicas']['mean']:.2f} | {s['avg_cpu_pct']['mean']:.1f} | {s['scale_actions_per_step']['mean']:.2f} |"
        )
    lines += ["", "Paired difference in episode reward versus the HPA-like rule (positive = better than the rule):", "",
              "| Policy | Mean difference (95% CI) | Episodes better than rule |", "| :--- | ---: | ---: |"]
    for name, p in paired.items():
        lines.append(f"| {name} | {p['mean_diff_vs_hpa_rule']:+.3f} +/- {p['ci95']:.3f} | {100 * p['win_rate']:.0f}% |")
    lines += [
        "",
        "Notes:",
        "- v2 was trained on the original reward, v3 on the cost-aware reward; both are shown under both definitions. "
        "Avg replicas and SLO violations are reward-independent and are the fairer comparison.",
        "- `ppo_legacy` was trained on data whose CPU/memory columns were fractions (0-1) instead of percent and on a "
        "50-replica range; it is shown for transparency only.",
        "- The simulator uses an M/M/1-style latency model over trace demand. Simulation results do not prove live performance; "
        "see the live experiment reports for that.",
    ]
    Path(args.out + ".md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {args.out}.json and {args.out}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
