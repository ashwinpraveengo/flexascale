#!/usr/bin/env python3
"""
Sanity-check script for the FlexaScale RL simulation environment.

Runs a heuristic baseline autoscaling policy across the simulated cluster
and prints per-step diagnostics to verify that the simulator behaves sensibly:

    - Scale up   when CPU exceeds target
    - Scale down when CPU drops below half the target
    - Otherwise  maintain

Usage::

    python scripts/run_sanity_simulation.py
    python scripts/run_sanity_simulation.py --episodes 3 --seed 42
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import numpy as np

# Ensure the src/ directory is importable when running from the repo root.
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from flexascale.config.env_config import EnvConfig
from flexascale.data.schema import VECTOR_DIM
from flexascale.simulator.flexascale_env import (
    ACTION_MAINTAIN,
    ACTION_SCALE_DOWN,
    ACTION_SCALE_UP,
    FlexaScaleEnv,
)


def heuristic_policy(
    obs: np.ndarray,
    cpu_target: float = 70.0,
) -> int:
    """
    Simple rule-based scaling policy for a single service observation.

    Args:
        obs: Current per-service observation vector (VECTOR_FIELDS layout).
        cpu_target: CPU utilisation target (percentage).

    Returns:
        Action integer: 0 (scale down), 1 (maintain), 2 (scale up).
    """
    cpu = float(obs[0])
    if cpu > cpu_target:
        return ACTION_SCALE_UP
    elif cpu < cpu_target / 2.0:
        return ACTION_SCALE_DOWN
    else:
        return ACTION_MAINTAIN


_ACTION_NAMES = {
    ACTION_SCALE_DOWN: "DOWN",
    ACTION_MAINTAIN: "KEEP",
    ACTION_SCALE_UP: "  UP",
}


def run_episode(
    env: FlexaScaleEnv,
    seed: int | None,
    episode_num: int,
) -> dict:
    """Run one full episode and print step-by-step diagnostics."""
    obs, info = env.reset(seed=seed)
    num_services = env.num_services

    print(f"\n{'=' * 82}")
    print(
        f"Episode {episode_num}  |  "
        f"services={num_services}  |  "
        f"trace_steps={env.episode_length}"
    )
    print(f"{'=' * 82}")
    print(
        f"{'step':>4s}  {'actions':>10s}  {'avg_reps':>9s}  "
        f"{'avg_cpu%':>9s}  {'avg_mem%':>9s}  "
        f"{'tot_rps':>9s}  {'avg_lat':>8s}  "
        f"{'reward':>7s}  {'SLO':>5s}"
    )
    print("-" * 82)

    total_reward = 0.0
    slo_violations = 0
    steps = 0

    terminated = False
    truncated = False

    while not (terminated or truncated):
        # Apply heuristic policy to each service
        actions = []
        obs_flat = obs.flatten()
        for i in range(num_services):
            s_obs = obs_flat[i * VECTOR_DIM : (i + 1) * VECTOR_DIM]
            a = heuristic_policy(s_obs, env.config.cpu_target_pct)
            actions.append(a)

        obs, reward, terminated, truncated, info = env.step(np.array(actions, dtype=np.int64))
        steps += 1
        total_reward += reward

        slo_flag = "FAIL" if info.get("slo_violated") else "  ok"
        if info.get("slo_violated"):
            slo_violations += 1

        # Aggregate metrics across services for step logging
        obs_reshaped = obs.reshape(num_services, VECTOR_DIM)
        avg_cpu = float(np.mean(obs_reshaped[:, 0]))
        avg_mem = float(np.mean(obs_reshaped[:, 1]))
        avg_reps = float(np.mean(obs_reshaped[:, 2]))
        tot_rps = float(np.sum(obs_reshaped[:, 3]))
        avg_lat = float(np.mean(obs_reshaped[:, 4]))

        act_str = "".join([_ACTION_NAMES[a][0] for a in actions])  # e.g. "KKUK"

        if steps <= 15 or steps % 50 == 0 or terminated:
            print(
                f"{steps:>4d}  {act_str:>10s}  "
                f"{avg_reps:>9.1f}  "
                f"{avg_cpu:>9.2f}  {avg_mem:>9.2f}  "
                f"{tot_rps:>9.1f}  {avg_lat:>8.1f}  "
                f"{reward:>+7.3f}  {slo_flag:>5s}"
            )

    violation_rate = (
        slo_violations / steps * 100.0 if steps > 0 else 0.0
    )
    print("-" * 82)
    print(
        f"Summary: {steps} steps  |  "
        f"total_reward={total_reward:+.3f}  |  "
        f"SLO violations={slo_violations}/{steps} "
        f"({violation_rate:.1f}%)"
    )

    return {
        "steps": steps,
        "total_reward": total_reward,
        "slo_violations": slo_violations,
        "violation_rate": violation_rate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FlexaScale environment sanity simulation"
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=3,
        help="Number of episodes to run (default: 3)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Base random seed (default: 42)",
    )
    args = parser.parse_args()

    print("FlexaScale RL Environment — Cluster Sanity Simulation")
    print("=" * 55)

    config = EnvConfig()
    env = FlexaScaleEnv(config=config)

    print(f"Dataset:     {config.dataset_path}")
    print(f"Services:    {env.num_services}")
    print(f"Timestamps:  {env.num_timestamps}")
    print(f"SLO target:  {config.latency_target_ms} ms")
    print(f"CPU target:  {config.cpu_target_pct}%")
    print(f"Replicas:    [{config.min_replicas}, {config.max_replicas}]")

    summaries = []
    for ep in range(1, args.episodes + 1):
        seed = args.seed + ep - 1
        summary = run_episode(env, seed=seed, episode_num=ep)
        summaries.append(summary)

    print(f"\n{'=' * 82}")
    print("OVERALL CLUSTER SIMULATION SUMMARY")
    print(f"{'=' * 82}")
    for i, s in enumerate(summaries, 1):
        print(
            f"  Episode {i}: "
            f"reward={s['total_reward']:+.3f}, "
            f"SLO violations={s['slo_violations']}/{s['steps']} "
            f"({s['violation_rate']:.1f}%)"
        )

    env.close()
    print("\nSanity simulation complete.")


if __name__ == "__main__":
    main()
