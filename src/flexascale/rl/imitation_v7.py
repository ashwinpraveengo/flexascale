"""
Warm start for the v7 focal policy: imitate a rule, then let PPO improve on it (amendment 4, POLICY_V7 §4.2).

The teacher is the best hand-written rule on the validation set (``twin_control.limit_target_policy``, chosen
by the protocol of §4.3), run in the twin on the training distribution with epsilon-random deviations for
coverage. Every service's decision is one sample: its focal observation (the application + a one-hot of the
service), the rule's replica change mapped to the nearest action, and the service's own discounted return
(``twin_env.per_service_rewards``), so the critic starts calibrated to the per-service rewards PPO will use.

PPO fine-tuning then starts from a policy that is as good as the rule; selection on validation keeps the
fine-tuned checkpoint only if it beats the warm start. If the learned policy ends where the rule is, the
live rule arm (§3.2) shows that directly.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import numpy as np
import torch

from flexascale.simulator.twin_control import OperatorLoop, observation
from flexascale.simulator.twin_env import ACTION_DELTAS, TwinEnv, per_service_rewards


def collect_focal(make_env: Callable[[int], TwinEnv], rule, episodes: int, epsilon: float, gamma: float,
                  seed: int) -> Dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    deltas = np.asarray(ACTION_DELTAS)
    obs_l, lab_l, ret_l = [], [], []
    n_max = None
    for ep in range(episodes):
        env = make_env(seed + ep)
        base, _ = env.reset(seed=seed + ep)
        n_max = env.n_max
        eye = np.eye(n_max, dtype=np.float32)
        n = len(env.app.services)
        ep_obs, ep_lab, ep_rew = [], [], []
        done = False
        while not done:
            want = np.asarray(rule(env.sim, observation(env.sim), env.loop), dtype=int)
            label = np.abs(np.clip(want, deltas.min(), deltas.max())[:, None] - deltas[None, :]).argmin(axis=1)
            act = label.copy()
            explore = rng.random(n) < epsilon
            act[explore] = rng.integers(0, len(deltas), int(explore.sum()))
            full = np.full(n_max, ACTION_DELTAS.index(0))
            full[:n] = act
            start = len(env.sim.log["desired"])
            nxt, _, done, _, _ = env.step(full)
            r = per_service_rewards(env.sim, start, len(env.sim.log["desired"]), env.floor, env.reward_cfg)
            ep_obs.append(np.concatenate([np.repeat(base[None, :], n, axis=0), eye[:n]], axis=1))
            ep_lab.append(label)
            ep_rew.append(r)
            base = nxt
        g = np.zeros(n)
        rets = []
        for r in reversed(ep_rew):
            g = r + gamma * g
            rets.append(g.copy())
        rets = rets[::-1]
        for o, lab, rt in zip(ep_obs, ep_lab, rets):
            obs_l.append(o)
            lab_l.append(lab)
            ret_l.append(rt)
    return {"obs": np.concatenate(obs_l).astype(np.float32), "labels": np.concatenate(lab_l).astype(np.int64),
            "returns": np.concatenate(ret_l).astype(np.float32)}


def warm_start_focal(model, make_env: Callable[[int], TwinEnv], rule, episodes: int = 400, epsilon: float = 0.2,
                     epochs: int = 15, batch_size: int = 1024, lr: float = 1e-3, value_weight: float = 0.5,
                     seed: int = 0) -> Dict[str, Any]:
    """Fit the focal actor to the rule and the critic to the rule's per-service returns, in place."""
    data = collect_focal(make_env, rule, episodes, epsilon, float(model.gamma), seed)
    n = len(data["obs"])
    idx = np.random.default_rng(seed).permutation(n)
    split = int(0.9 * n)
    tr, va = idx[:split], idx[split:]
    policy = model.policy
    policy.set_training_mode(True)
    opt = torch.optim.Adam(policy.parameters(), lr=lr)
    obs, labels, returns = (torch.as_tensor(data[k]) for k in ("obs", "labels", "returns"))
    for epoch in range(epochs):
        order = np.random.default_rng(seed + epoch).permutation(tr)
        for b in np.array_split(order, max(1, len(order) // batch_size)):
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
    labels_va = data["labels"][va]
    moving = labels_va != ACTION_DELTAS.index(0)
    return {"teacher": getattr(rule, "name", "rule"), "episodes": episodes, "epsilon": epsilon, "samples": n,
            "agreement_heldout": round(float((pred == labels_va).mean()), 4),
            "agreement_on_scaling_decisions": round(float((pred[moving] == labels_va[moving]).mean()), 4) if moving.any() else None,
            "value_mse_heldout": round(float(torch.mean((values - returns[va]) ** 2)), 4),
            "return_var_heldout": round(float(returns[va].var()), 4)}
