#!/usr/bin/env python3
"""
Sanity-check script for the FlexaScale RL simulation environment.

Runs a simple heuristic baseline policy and prints per-step diagnostics
so the team can verify that the simulator behaves sensibly:

    - Scale up   when CPU exceeds the target
    - Scale down when CPU drops below half the target
    - Otherwise  maintain

Usage::

    python scripts/run_sanity_simulation.py
    python scripts/run_sanity_simulation.py --episodes 5 --seed 42
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the src/ directory is importable when running from the repo root.
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from flexascale.config.env_config import EnvConfig
from flexascale.simulator.flexascale_env import (
    ACTION_MAINTAIN,
    ACTION_SCALE_DOWN,
    ACTION_SCALE_UP,
    FlexaScaleEnv,
)


def heuristic_policy(
    obs,
    cpu_target: float = 70.0,
) -> int:
    """
    Simple rule-based scaling policy.

    Args:
        obs:        Current observation vector (VECTOR_FIELDS layout).
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
    service = info["service_id"][:16]

    print(f"\n{'=' * 78}")
    print(
        f"Episode {episode_num}  |  "
        f"service={service}...  |  "
        f"trace_steps={env.episode_length}"
    )
    print(f"{'=' * 78}")
    print(
        f"{'step':>4s}  {'action':>6s}  {'replicas':>8s}  "
        f"{'cpu%':>7s}  {'mem%':>7s}  "
        f"{'rps':>8s}  {'latency':>8s}  "
        f"{'reward':>7s}  {'SLO':>5s}"
    )
    print("-" * 78)

    total_reward = 0.0
    slo_violations = 0
    steps = 0

    # Print initial state.
    print(
        f"{'init':>4s}  {'    -':>6s}  {info['simulated_replicas']:>8d}  "
        f"{obs[0]:>7.2f}  {obs[1]:>7.2f}  "
        f"{obs[3]:>8.1f}  {obs[4]:>8.1f}  "
        f"{'    -':>7s}  {'  -':>5s}"
    )

    terminated = False
    while not terminated:
        action = heuristic_policy(obs, env.config.cpu_target_pct)
        obs, reward, terminated, truncated, info = env.step(action)
        steps += 1
        total_reward += reward

        slo_flag = "FAIL" if info.get("slo_violated") else "  ok"
        if info.get("slo_violated"):
            slo_violations += 1

        print(
            f"{steps:>4d}  {_ACTION_NAMES[action]:>6s}  "
            f"{info['simulated_replicas']:>8d}  "
            f"{obs[0]:>7.2f}  {obs[1]:>7.2f}  "
            f"{obs[3]:>8.1f}  {obs[4]:>8.1f}  "
            f"{reward:>+7.3f}  {slo_flag:>5s}"
        )

        if terminated or truncated:
            break

    # Episode summary.
    violation_rate = (
        slo_violations / steps * 100.0 if steps > 0 else 0.0
    )
    print("-" * 78)
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

    print("FlexaScale RL Environment — Sanity Simulation")
    print("=" * 50)

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

    # Overall summary.
    print(f"\n{'=' * 78}")
    print("OVERALL SUMMARY")
    print(f"{'=' * 78}")
    for i, s in enumerate(summaries, 1):
        print(
            f"  Episode {i}: "
            f"reward={s['total_reward']:+.3f}, "
            f"SLO violations={s['slo_violations']}/{s['steps']} "
            f"({s['violation_rate']:.1f}%)"
        )

    env.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
