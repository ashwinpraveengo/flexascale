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

Class balance: under the rule almost every decision is "hold" or "scale down" (in 40 episodes, 17 of 24,647
labels were +1). The rule's decision depends only on CPU per replica against the limit and the replica
count, so each sample is augmented with copies whose CPU feature is rescaled and *relabelled by the rule's
own formula* (``limit_target_label``), and the loss is weighted by inverse class frequency. Recall is
reported per action on held-out original samples and on rescaled held-out copies.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import numpy as np
import torch

from flexascale.rl import features_v3 as fv
from flexascale.simulator.twin_control import observation
from flexascale.simulator.twin_env import ACTION_DELTAS, TwinEnv, per_service_rewards


def limit_target_label(x: np.ndarray, target: float, down: float, max_replicas: int = 10, max_jump: int = 3) -> np.ndarray:
    """``limit_target_policy`` computed from v3 features only (cpu per replica / limit, replica and ready fractions)."""
    cpu, cur = x[:, 0], np.maximum(1, np.rint(x[:, 4] * max_replicas))
    ready = np.maximum(1, np.rint(x[:, 5] * cur))
    cores_over_limit = cpu * ready                     # total cores / limit
    need = np.ceil(cores_over_limit / target - 1e-9)
    up = np.clip(need - cur, 0, max_jump)
    fewer = np.maximum(cur - 1, 1)
    down_ok = (cores_over_limit / fewer < down) & (cur > 1)
    delta = np.where(up > 0, up, np.where(down_ok, -1, 0))
    return np.abs(delta[:, None] - np.asarray(ACTION_DELTAS)[None, :]).argmin(axis=1)


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
    return {"obs": np.concatenate(obs_l).astype(np.float32, copy=False), "labels": np.concatenate(lab_l).astype(np.int64),
            "returns": np.concatenate(ret_l).astype(np.float32)}


def _focal_rows(obs: np.ndarray):
    """Column of each focal observation's own CPU feature, and that service's feature row (a copy)."""
    w = obs.shape[1]
    n_max = int(round((-(fv.F + 2) + np.sqrt((fv.F + 2) ** 2 + 4 * w)) / 2))  # w = obs_dim(n_max) + n_max
    assert fv.obs_dim(n_max) + n_max == w, w
    cpu_col = obs[:, -n_max:].argmax(axis=1) * fv.F
    return cpu_col, np.take_along_axis(obs, cpu_col[:, None] + np.arange(fv.F)[None, :], axis=1)


def _rescale_cpu(cpu: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return np.clip(cpu * np.exp(rng.uniform(np.log(0.3), np.log(4.0), len(cpu))), fv.LOW[0], fv.HIGH[0]).astype(np.float32)


def _recall(pred: np.ndarray, labels: np.ndarray) -> Dict[str, float]:
    return {str(ACTION_DELTAS[k]): round(float((pred[labels == k] == k).mean()), 3)
            for k in range(len(ACTION_DELTAS)) if (labels == k).any()}


def warm_start_focal(model, make_env: Callable[[int], TwinEnv], rule, episodes: int = 400, epsilon: float = 0.2,
                     epochs: int = 15, batch_size: int = 1024, lr: float = 1e-3, value_weight: float = 0.5,
                     seed: int = 0, target: float = None, down: float = None, augment: int = 3) -> Dict[str, Any]:
    """Fit the focal actor to the rule and the critic to the rule's per-service returns, in place.

    With ``target``/``down`` (the teacher's parameters) every training sample also has ``augment`` copies whose
    focal CPU feature is rescaled and relabelled by the rule. Only the rescaled value and the label of a copy
    are stored; copies are assembled per batch, so memory stays that of the collected samples. Copies train
    the actor only: their state differs from the one whose return was observed.
    """
    data = collect_focal(make_env, rule, episodes, epsilon, float(model.gamma), seed)
    obs_all, labels_all, returns_all = data["obs"], data["labels"], torch.as_tensor(data["returns"])
    n = len(obs_all)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    split = int(0.9 * n)
    tr, va = idx[:split], idx[split:]
    cpu_col, rows = _focal_rows(obs_all)
    copies = augment if target is not None and down is not None else 0
    cpu_aug = np.empty((copies, n), dtype=np.float32)
    lab_aug = np.empty((copies, n), dtype=np.int64)
    for c in range(copies):
        r = rows.copy()
        r[:, 0] = _rescale_cpu(rows[:, 0], rng)
        cpu_aug[c], lab_aug[c] = r[:, 0], limit_target_label(r, target, down)
    counts = np.bincount(np.concatenate([labels_all[tr]] + [lab_aug[c, tr] for c in range(copies)]),
                         minlength=len(ACTION_DELTAS)).astype(float)
    class_w = torch.as_tensor(np.where(counts > 0, counts.sum() / (len(counts) * np.maximum(counts, 1)), 0.0), dtype=torch.float32)
    class_w = torch.clamp(class_w, max=50.0)
    policy = model.policy
    policy.set_training_mode(True)
    opt = torch.optim.Adam(policy.parameters(), lr=lr)
    items = np.arange(len(tr) * (1 + copies))  # item j: sample tr[j % len(tr)], copy j // len(tr) (0 = original)
    for epoch in range(epochs):
        order = np.random.default_rng(seed + epoch).permutation(items)
        for b in np.array_split(order, max(1, len(order) // batch_size)):
            s, c = tr[b % len(tr)], b // len(tr)
            o, lab = obs_all[s], labels_all[s]  # fancy indexing copies
            pos = np.flatnonzero(c > 0)
            o[pos, cpu_col[s[pos]]] = cpu_aug[c[pos] - 1, s[pos]]
            lab[pos] = lab_aug[c[pos] - 1, s[pos]]
            lab_t = torch.as_tensor(lab)
            values, log_prob, _ = policy.evaluate_actions(torch.as_tensor(o), lab_t)
            w = class_w[lab_t]
            loss = -(w * log_prob).sum() / w.sum()
            orig = torch.as_tensor(c == 0)
            if orig.any():
                loss = loss + value_weight * torch.nn.functional.mse_loss(values.flatten()[orig], returns_all[s][orig])
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), 0.5)
            opt.step()
    policy.set_training_mode(False)
    labels_va = labels_all[va]
    with torch.no_grad():
        pred, _ = model.predict(obs_all[va], deterministic=True)
        values = policy.predict_values(torch.as_tensor(obs_all[va])).flatten()
    recall_aug = {}
    if copies:  # held-out copies, freshly rescaled (the original held-out set has almost no scale-ups)
        o, r = obs_all[va], rows[va].copy()
        r[:, 0] = _rescale_cpu(r[:, 0], np.random.default_rng(seed + 99))
        o[np.arange(len(va)), cpu_col[va]] = r[:, 0]
        pred_aug, _ = model.predict(o, deterministic=True)
        recall_aug = _recall(pred_aug, limit_target_label(r, target, down))
    return {"teacher": getattr(rule, "name", "rule"), "episodes": episodes, "epsilon": epsilon, "samples": n,
            "label_counts": {str(ACTION_DELTAS[k]): int(c) for k, c in enumerate(np.bincount(labels_all, minlength=len(ACTION_DELTAS)))},
            "agreement_heldout": round(float((pred == labels_va).mean()), 4),
            "recall_per_action_heldout": _recall(pred, labels_va), "recall_per_action_augmented_heldout": recall_aug,
            "value_mse_heldout": round(float(torch.mean((values - returns_all[va]) ** 2)), 4),
            "return_var_heldout": round(float(data["returns"][va].var()), 4)}
