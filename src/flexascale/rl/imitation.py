"""
Warm start for PPO: imitate the HPA-like rule before reinforcement learning.

Why: PPO from random weights (v4) ended *below* the HPA-like rule on its own
reward, although the rule is a policy the network can represent exactly. The
fine-tuning stage therefore starts from the rule and can only be selected if it
improves on it.

The teacher is the rule the operator is compared with: scale up above 77% of
the CPU request, down below 63% (native HPA's 70% target with its 10%
tolerance), hold otherwise. Labels come from the observation itself
(``cpu_fraction`` is feature 0 of each service), so the imitated rule is the
one the model can see live.

Actor and critic are trained together: cross-entropy on the teacher's action
for every slot, and regression of the value head on discounted Monte-Carlo
returns of the same rollouts. Starting PPO with an untrained critic would make
its first updates follow noise and undo the imitation.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import torch
from stable_baselines3 import PPO

from flexascale.simulator.dependency_env import FEATURE_NAMES, FlexaScaleEnvV2

N_FEATURES = len(FEATURE_NAMES)
HPA_UP, HPA_DOWN = 0.77, 0.63


def ratio_teacher(deltas, max_replicas: int, target: float = 0.70, tolerance: float = 0.10):
    """
    Native HPA's ratio rule as a teacher for delta actions (v6, ``FlexaScaleEnvV3``).

    desired = ceil(replicas x cpu / target) outside the tolerance band, as the HPA
    controller computes it, then the closest available replica change. Replicas
    come from ``replica_fraction`` (feature 2), so the rule uses only what the
    model sees; HPA's stabilisation window (history) is not part of it.
    """
    d = np.asarray(deltas, dtype=int)

    def teacher(obs: np.ndarray) -> np.ndarray:
        x = np.asarray(obs, dtype=np.float32).reshape(-1, N_FEATURES)
        cpu, cur = x[:, 0], np.maximum(1, np.rint(x[:, 2] * max_replicas))
        ratio = cpu / target
        want = np.where(np.abs(ratio - 1.0) <= tolerance, cur, np.ceil(cur * ratio - 1e-9))
        change = np.clip(want - cur, d.min(), d.max())
        return np.abs(change[:, None] - d[None, :]).argmin(axis=1).astype(np.int64)

    teacher.description = f"native HPA ratio rule: ceil(n x cpu / {target}) outside +-{tolerance:.0%}, deltas {[int(v) for v in d]}"
    return teacher


def hpa_teacher(obs: np.ndarray) -> np.ndarray:
    """HPA-like action (0 down, 1 hold, 2 up) per service from a version-2 observation."""
    cpu = np.asarray(obs, dtype=np.float32).reshape(-1, N_FEATURES)[:, 0]
    return np.where(cpu > HPA_UP, 2, np.where(cpu < HPA_DOWN, 0, 1)).astype(np.int64)


def collect(env: FlexaScaleEnvV2, episodes: int, epsilon: float, gamma: float, seed: int,
            teacher: Callable[[np.ndarray], np.ndarray] = hpa_teacher) -> dict[str, np.ndarray]:
    """
    Roll out the teacher with epsilon-random slot-0 actions (for state coverage).

    Returns observations, teacher labels for every slot, and discounted returns.
    """
    rng = np.random.default_rng(seed)
    obs_l, lab_l, ret_l = [], [], []
    for ep in range(episodes):
        obs, _ = env.reset(seed=seed + ep)
        ep_obs, ep_lab, ep_rew = [], [], []
        while True:
            label = teacher(obs)
            act = label.copy()
            if rng.random() < epsilon:
                act[0] = rng.integers(0, int(env.action_space.nvec[0]))
            nxt, r, term, trunc, _ = env.step(act)
            if term or trunc:
                break  # the terminal step carries no decision
            ep_obs.append(obs)
            ep_lab.append(label)
            ep_rew.append(r)
            obs = nxt
        g, rets = 0.0, []
        for r in reversed(ep_rew):
            g = r + gamma * g
            rets.append(g)
        obs_l += ep_obs
        lab_l += ep_lab
        ret_l += rets[::-1]
    return {"obs": np.asarray(obs_l, dtype=np.float32), "labels": np.asarray(lab_l, dtype=np.int64),
            "returns": np.asarray(ret_l, dtype=np.float32)}


def warm_start(model: PPO, env: FlexaScaleEnvV2, episodes: int = 3000, epsilon: float = 0.3,
               epochs: int = 30, batch_size: int = 256, lr: float = 1e-3, value_weight: float = 0.5,
               seed: int = 0, teacher: Callable[[np.ndarray], np.ndarray] = hpa_teacher) -> dict[str, Any]:
    """Fit ``model``'s actor to the teacher and its critic to the teacher's returns, in place."""
    data = collect(env, episodes, epsilon, float(model.gamma), seed, teacher=teacher)
    n = len(data["obs"])
    idx = np.random.default_rng(seed).permutation(n)
    split = int(0.9 * n)
    tr, va = idx[:split], idx[split:]
    policy = model.policy
    policy.set_training_mode(True)
    opt = torch.optim.Adam(policy.parameters(), lr=lr)
    obs = torch.as_tensor(data["obs"])
    labels = torch.as_tensor(data["labels"])
    returns = torch.as_tensor(data["returns"])
    for _ in range(epochs):
        for b in np.array_split(np.random.default_rng(seed + 1).permutation(tr), max(1, len(tr) // batch_size)):
            values, log_prob, _ = policy.evaluate_actions(obs[b], labels[b])
            loss = -log_prob.mean() + value_weight * torch.nn.functional.mse_loss(values.flatten(), returns[b])
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), 0.5)
            opt.step()
    policy.set_training_mode(False)
    with torch.no_grad():
        pred, _ = model.predict(data["obs"][va], deterministic=True)
        values = policy.predict_values(obs[va]).flatten()
    return {
        "teacher": getattr(teacher, "description", f"HPA-like rule on cpu_fraction: up > {HPA_UP}, down < {HPA_DOWN}"),
        "episodes": episodes, "epsilon": epsilon, "samples": n, "epochs": epochs, "lr": lr,
        "slot0_agreement_heldout": round(float((pred[:, 0] == data["labels"][va][:, 0]).mean()), 4),
        "value_mse_heldout": round(float(torch.mean((values - returns[va]) ** 2)), 4),
        "return_var_heldout": round(float(returns[va].var()), 4),
    }
