#!/usr/bin/env python3
"""
Where does PPO training time go? (GPU assessment, docs/POLICY_V9.md §2)

Runs a few PPO iterations of the v7 training set-up (focal graph policy on the application twin,
the exact FOCAL_PPO_KW of scripts/train_v7.py) and times the two phases separately:

* rollout: stepping the twin simulator (NumPy, single-threaded Python) plus policy *inference*;
* update:  PPO's gradient epochs over the collected batch (the only part a GPU could accelerate).

By Amdahl's law the whole-training speed-up from any accelerator is at most 1 / (rollout share).
With ``--device cuda`` (needs a CUDA build of PyTorch) the same run is timed on the GPU.

    python scripts/profile_training.py [--iterations 6] [--device cpu|cuda] [--threads 2]
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iterations", type=int, default=6)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--threads", type=int, default=2, help="torch threads (train_v7 uses 2)")
    ap.add_argument("--out", default=None, help="append the result as one JSON line to this file")
    args = ap.parse_args()

    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.policies import ActorCriticPolicy

    import flexascale.rl  # noqa: F401  (sb3 compat shim)
    from flexascale.rl.graph_policy import GraphFocalExtractor
    from flexascale.simulator.twin_env import N_MAX, RewardConfig, TwinAgentsVecEnv, load_shop
    from train_v7 import FOCAL_PPO_KW

    torch.set_num_threads(args.threads)
    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    venv = TwinAgentsVecEnv(app, cal, n_sims=4, n_max=N_MAX, reward=RewardConfig(kind="v7"), seed=1)
    model = PPO(ActorCriticPolicy, venv, seed=1, verbose=0, device=args.device,
                policy_kwargs={"features_extractor_class": GraphFocalExtractor,
                               "features_extractor_kwargs": {"n_max": N_MAX, "hidden": 64, "rounds": 2, "use_graph": True},
                               "net_arch": {"pi": [64], "vf": [64]}, "ortho_init": False}, **FOCAL_PPO_KW)

    timing = {"rollout": 0.0, "update": 0.0}
    collect, train = model.collect_rollouts, model.train

    def timed(phase, fn):
        def wrapper(*a, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                if args.device.startswith("cuda"):
                    torch.cuda.synchronize()
                timing[phase] += time.perf_counter() - t0
        return wrapper

    model.collect_rollouts = timed("rollout", collect)
    model.train = timed("update", train)
    per_iter = model.n_steps * model.n_envs
    model.learn(total_timesteps=per_iter)  # warm-up iteration (allocations, first kernel launches)
    timing.update(rollout=0.0, update=0.0)
    t0 = time.perf_counter()
    model.learn(total_timesteps=per_iter * args.iterations, reset_num_timesteps=False)
    wall = time.perf_counter() - t0
    params = sum(p.numel() for p in model.policy.parameters())
    share = timing["update"] / max(1e-9, timing["rollout"] + timing["update"])
    result = {
        "device": args.device, "torch": torch.__version__, "cuda_build": torch.version.cuda, "threads": args.threads,
        "cpu": platform.processor(), "iterations": args.iterations, "agent_steps_per_iteration": per_iter,
        "parameters": params, "rollout_s": round(timing["rollout"], 2), "update_s": round(timing["update"], 2),
        "wall_s": round(wall, 2), "update_share": round(share, 3), "agent_steps_per_s": round(per_iter * args.iterations / wall, 1),
        "max_speedup_if_update_were_free": round(1 / max(1e-9, 1 - share), 2),
    }
    print(json.dumps(result, indent=2))
    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
