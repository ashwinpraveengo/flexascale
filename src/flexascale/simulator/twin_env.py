"""
Gymnasium environment for training the v7 graph policy on the application twin.

One step = one operator decision (10 s = 2 twin ticks) for *every* service at once:
the policy proposes a replica change per service, the operator's v7 guards
(``twin_control.V7_GUARDS``, the same code path as ``OperatorLoop``) decide what is
applied, the twin advances 10 s, and the reward is charged.

Reward (docs/POLICY_V7.md §4.2), in replica-equivalents per step, so every trade-off
is explicit ("how many replicas is avoiding this worth?"):

    − replica        x replicas above each service's minimum (requested, averaged over the step)
    − p95_inflation  x min(cap, end-to-end p95 / the p95 with ample capacity − 1), floored at 0
    − slo            x fraction of the step with end-to-end p95 above the SLO (1000 ms)
    − failure_pct    x percent of requests failing
    − scaling_event  x replica changes applied

The p95 term charges under-provisioning only when it actually slows requests, the
replica term charges over-provisioning, and the event term charges churn. All terms
are reported separately in ``info["reward_components"]``.

Episodes: the fitted shop (parameters perturbed ±30%, so the policy cannot memorise
one set of constants) on ``random_workload`` shapes, and with probability
``random_app_prob`` a synthetic application (``twin_workloads.random_app``) so the
policy has to read the graph and the features, not service identities.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from flexascale.rl import features_v3 as fv
from flexascale.simulator.twin import TICK_S, AppSpec, TwinSim, Workload
from flexascale.simulator.twin_control import SYNC_TICKS_OPERATOR, V7_GUARDS, Guards, OperatorLoop, observation
from flexascale.simulator.twin_workloads import random_app, random_workload

ACTION_DELTAS = (-1, 0, 1, 2, 3)
HOLD_INDEX = ACTION_DELTAS.index(0)
E2E_SLO_MS = 1000.0
N_MAX = 20


@dataclass
class RewardConfig:
    replica: float = 1.0
    p95_inflation: float = 6.0
    p95_inflation_cap: float = 4.0
    """Per-step cap on the inflation (amended 2026-10-26 23:30, POLICY_V7 §4.2): uncapped, rare overload episodes
    (inflation up to 620 when holding the minimum) dominated the gradient and taught 'scale everything up'."""
    slo: float = 10.0
    failure_pct: float = 5.0
    scaling_event: float = 0.25
    scale: float = 0.1
    kind: str = "v7"
    """'v7' (above) or 'v5': the v4–v6 reward structure transplanted to the twin, for the reward ablation:
    per service slo + 0.3 efficiency (|CPU% of request − 70| / 100) + 0.1 stability + 1.0 cost (replicas / max),
    with slo = +1 when the end-to-end p95 meets the SLO, else −min(3, p95/SLO − 1)."""


def reward_v5(sim, start: int, events: int, floor: np.ndarray) -> float:
    log = sim.log
    p95 = np.array(log["e2e_p95"][start:])
    cpu = np.array(log["cpu"][start:])                   # cores per service
    ready = np.maximum(np.array(log["ready"][start:]), 1)
    d = np.array(log["desired"][start:])
    cpu_pct = np.minimum(100.0 * cpu / ready / sim.request, 100.0)
    slo = np.where(p95 <= E2E_SLO_MS, 1.0, -np.minimum(3.0, p95 / E2E_SLO_MS - 1.0)).mean()
    eff = -(np.abs(cpu_pct - 70.0) / 100.0).mean()
    cost = -(d / sim.hi).mean()
    stab = -events / max(1, sim.n)
    return float(slo + 0.3 * eff + 0.1 * stab + 1.0 * cost)


def perturb(app: AppSpec, rng: np.random.Generator, spread: float = 0.3) -> AppSpec:
    a = copy.deepcopy(app)
    for s in a.services:
        s.cpu_per_req *= float(np.exp(rng.uniform(np.log(1 - spread), np.log(1 + spread))))
        s.idle_cores *= float(rng.uniform(1 - spread, 1 + spread))
        s.base_latency_ms *= float(rng.uniform(1 - spread / 2, 1 + spread / 2))
    return a


class TwinEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, app: AppSpec, cal: Dict[str, Any], *, n_max: int = N_MAX, reward: Optional[RewardConfig] = None,
                 guards: Guards = V7_GUARDS, random_app_prob: float = 0.25, perturb_spread: float = 0.3,
                 workloads: Optional[List[Workload]] = None, seed: Optional[int] = None) -> None:
        super().__init__()
        self.base_app, self.cal, self.n_max = app, cal, n_max
        self.reward_cfg = reward or RewardConfig()
        self.guards = guards
        self.random_app_prob, self.spread = random_app_prob, perturb_spread
        self.fixed = workloads           # evaluation: cycle through these on the unperturbed app
        self._fixed_i = 0
        self.observation_space = spaces.Box(low=-1.0, high=4.0, shape=(fv.obs_dim(n_max),), dtype=np.float32)
        self.action_space = spaces.MultiDiscrete([len(ACTION_DELTAS)] * n_max)
        self.rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------

    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        if self.fixed is not None:
            self.app, wl = self.base_app, self.fixed[self._fixed_i % len(self.fixed)]
            self._fixed_i += 1
        elif self.rng.random() < self.random_app_prob:
            self.app, cal = random_app(self.rng)
            wl = random_workload(self.app, cal, self.rng)
        else:
            self.app = perturb(self.base_app, self.rng, self.spread)
            wl = random_workload(self.app, self.cal, self.rng)
        self.wl = wl
        self.sim = TwinSim(self.app, wl, seed=int(self.rng.integers(0, 2**31 - 1)))
        self.loop = OperatorLoop(lambda *a: None, self.guards, name="v7")
        self.loop.reset(self.sim)
        self.tracker = fv.FeatureTracker(self.app.names, max_replicas=int(max(s.max_replicas for s in self.app.services)))
        self.floor = np.array([s.min_replicas for s in self.app.services])
        for _ in range(SYNC_TICKS_OPERATOR):  # first decision after the first 10 s, as the operator's first step
            self.sim.step()
        return self._obs(), {"workload": wl.name, "app": self.app.name}

    def _obs(self) -> np.ndarray:
        o = observation(self.sim)
        now = self.sim.t * TICK_S
        feats = {}
        for i, s in enumerate(self.app.services):
            feats[s.name] = self.tracker.update(
                now, s.name, cpu_cores=float(o["cpu_cores"][i]), ready=int(o["ready"][i]), desired=int(o["desired"][i]),
                cpu_limit=s.cpu_limit, rps=float(o["rps"][i]), latency_ms=float(o["latency_ms"][i]) or None)
        self._last_obs = o
        return fv.pack(feats, self.app.names, self.app.edges, self.n_max)

    def step(self, action):
        a = np.asarray(action, dtype=int).ravel()[: len(self.app.services)]
        deltas = np.array([ACTION_DELTAS[int(k)] for k in a])
        applied = self.loop.apply(self.sim, deltas, self._last_obs)
        now = self.sim.t * TICK_S
        for i, s in enumerate(self.app.services):
            if applied[i]:
                self.tracker.note_scale(s.name, int(np.sign(applied[i])), now)
        start = len(self.sim.log["desired"])
        for _ in range(SYNC_TICKS_OPERATOR):
            self.sim.step()
        comps = self._reward_components(start, int(np.abs(applied).sum()))
        cfg = self.reward_cfg
        if cfg.kind == "v5":
            reward = reward_v5(self.sim, start, int(np.abs(applied).sum()), self.floor)
        else:
            reward = reward_v7(comps, cfg)
        done = self.sim.t >= self.wl.ticks
        obs = self._obs()
        info = {"reward_components": comps, "applied": applied.tolist()}
        if done:
            info["summary"] = {k: v for k, v in self.sim.summary().items()}
        return obs, float(reward), done, False, info

    def _reward_components(self, start: int, events: int) -> Dict[str, float]:
        log = self.sim.log
        d = np.array(log["desired"][start:])
        p95 = np.array(log["e2e_p95"][start:])
        base = np.array(log["e2e_p95_base"][start:])
        fail = np.array(log["fail_frac"][start:])
        infl = np.where(np.isfinite(base) & (base > 0), np.maximum(0.0, p95 / np.maximum(base, 1e-6) - 1.0), 0.0)
        infl = np.minimum(infl, self.reward_cfg.p95_inflation_cap)
        return {"replicas_above_min": float((d - self.floor).sum(axis=1).mean()), "p95_inflation": float(infl.mean()),
                "slo_fraction": float((p95 > E2E_SLO_MS).mean()), "failure_pct": float(100.0 * fail.mean()),
                "scaling_events": float(events)}


def reward_v7(comps: Dict[str, float], cfg: RewardConfig) -> float:
    return -cfg.scale * (cfg.replica * comps["replicas_above_min"] + cfg.p95_inflation * comps["p95_inflation"]
                         + cfg.slo * comps["slo_fraction"] + cfg.failure_pct * comps["failure_pct"]
                         + cfg.scaling_event * comps["scaling_events"])


def components_from_log(sim, start: int, end: int, floor: np.ndarray, cap: float = RewardConfig.p95_inflation_cap) -> Dict[str, float]:
    """The env's reward components for ticks [start, end) of any simulated run (events from the log)."""
    log = sim.log
    d = np.array(log["desired"][start:end])
    p95 = np.array(log["e2e_p95"][start:end])
    base = np.array(log["e2e_p95_base"][start:end])
    fail = np.array(log["fail_frac"][start:end])
    ev = log["replica_changes"][end - 1] - (log["replica_changes"][start - 1] if start > 0 else 0)
    infl = np.where(np.isfinite(base) & (base > 0), np.maximum(0.0, p95 / np.maximum(base, 1e-6) - 1.0), 0.0)
    infl = np.minimum(infl, cap)
    return {"replicas_above_min": float((d - floor).sum(axis=1).mean()), "p95_inflation": float(infl.mean()),
            "slo_fraction": float((p95 > E2E_SLO_MS).mean()), "failure_pct": float(100.0 * fail.mean()),
            "scaling_events": float(ev)}


def episode_reward(sim, cfg: RewardConfig) -> float:
    """Total v7 reward of a finished run, charged per 10 s decision window from tick 2 on, as in the env."""
    floor = sim.lo
    T = len(sim.log["desired"])
    return float(sum(reward_v7(components_from_log(sim, k, min(k + SYNC_TICKS_OPERATOR, T), floor, cfg.p95_inflation_cap), cfg)
                     for k in range(SYNC_TICKS_OPERATOR, T, SYNC_TICKS_OPERATOR)))


def load_shop(path: str | Path = "config/twin/shopping.json") -> Tuple[AppSpec, Dict[str, Any]]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return AppSpec.from_json(d), d["scenarios"]


# ---------------------------------------------------------------------------
# Per-service credit (amendment 2, POLICY_V7 §4.2): every service is an agent
# ---------------------------------------------------------------------------


def per_service_rewards(sim, start: int, end: int, floor: np.ndarray, cfg: RewardConfig) -> np.ndarray:
    """
    Split the step's v7 penalty among the services, so that the per-service rewards sum to the global reward:
    each service pays for its own replicas and replica changes, and for the share of the end-to-end latency
    penalty (p95 inflation, SLO, failures) that its own queueing causes: share_i ~ (fraction of requests that
    reach i) x (i's own excess latency). With no excess anywhere the latency penalty is split equally.
    """
    log = sim.log
    d = np.array(log["desired"][start:end])
    prev = np.array(log["desired"][start - 1]) if start > 0 else d[0]
    churn = np.abs(np.diff(np.vstack([prev, d]), axis=0)).sum(axis=0)
    repl = (d - floor).mean(axis=0)
    comps = components_from_log(sim, start, end, floor, cfg.p95_inflation_cap)
    penalty = (cfg.p95_inflation * comps["p95_inflation"] + cfg.slo * comps["slo_fraction"]
               + cfg.failure_pct * comps["failure_pct"])
    own = np.maximum(0.0, np.array(log["own_excess"][start:end]))
    lam = np.array(log["lam"][start:end])
    e2e = np.maximum(np.array(log["rps"][start:end]), 1e-9)[:, None]
    contrib = (np.minimum(1.0, lam / e2e) * own).mean(axis=0)
    share = contrib / contrib.sum() if contrib.sum() > 0 else np.full(sim.n, 1.0 / sim.n)
    return -cfg.scale * (cfg.replica * repl + cfg.scaling_event * churn + share * penalty)


def per_service_rewards_v5(sim, start: int, end: int, floor: np.ndarray) -> np.ndarray:
    """The v4-v6 per-service reward structure (ablation): slo + 0.3 efficiency + 0.1 stability + 1.0 cost."""
    log = sim.log
    p95 = np.array(log["e2e_p95"][start:end])
    d = np.array(log["desired"][start:end])
    prev = np.array(log["desired"][start - 1]) if start > 0 else d[0]
    churn = np.abs(np.diff(np.vstack([prev, d]), axis=0)).sum(axis=0)
    ready = np.maximum(np.array(log["ready"][start:end]), 1)
    cpu_pct = np.minimum(100.0 * np.array(log["cpu"][start:end]) / ready / sim.request, 100.0)
    slo = float(np.where(p95 <= E2E_SLO_MS, 1.0, -np.minimum(3.0, p95 / E2E_SLO_MS - 1.0)).mean())
    eff = -(np.abs(cpu_pct - 70.0) / 100.0).mean(axis=0)
    cost = -(d / sim.hi).mean(axis=0)
    return slo + 0.3 * eff + 0.1 * (-churn) + 1.0 * cost


from stable_baselines3.common.vec_env.base_vec_env import VecEnv as _VecEnv  # noqa: E402


class TwinAgentsVecEnv(_VecEnv):
    """
    Shared-parameter multi-agent view of ``n_sims`` twin environments for SB3: agent slot (k, j) is service j of
    simulation k. Its observation is the whole application (``features_v3.pack``) plus a one-hot of its own node,
    its action is one replica change, and its reward is its own share (``per_service_rewards``). Padded slots
    (no service) get reward 0 and their actions are ignored. All agents of a simulation end together.
    """

    def __init__(self, app: AppSpec, cal: Dict[str, Any], n_sims: int = 4, n_max: int = N_MAX,
                 reward: Optional[RewardConfig] = None, seed: int = 0, random_app_prob: float = 0.25) -> None:
        self.n_sims, self.n_max = n_sims, n_max
        self.cfg = reward or RewardConfig()
        self.envs = [TwinEnv(app, cal, n_max=n_max, reward=self.cfg, random_app_prob=random_app_prob,
                             seed=seed * 1000 + k) for k in range(n_sims)]
        obs_space = spaces.Box(low=-1.0, high=4.0, shape=(fv.obs_dim(n_max) + n_max,), dtype=np.float32)
        act_space = spaces.Discrete(len(ACTION_DELTAS))
        _VecEnv.__init__(self, n_sims * n_max, obs_space, act_space)
        self._base = [None] * n_sims
        self._actions = None
        self._eye = np.eye(n_max, dtype=np.float32)

    # SB3 VecEnv interface -------------------------------------------------------

    def _agent_obs(self, k: int) -> np.ndarray:
        return np.concatenate([np.repeat(self._base[k][None, :], self.n_max, axis=0), self._eye], axis=1)

    def reset(self):
        for k, env in enumerate(self.envs):
            self._base[k], _ = env.reset()
        return np.concatenate([self._agent_obs(k) for k in range(self.n_sims)])

    def step_async(self, actions):
        self._actions = np.asarray(actions).reshape(self.n_sims, self.n_max)

    def step_wait(self):
        obs, rews, dones, infos = [], [], [], []
        for k, env in enumerate(self.envs):
            n = len(env.app.services)
            start = len(env.sim.log["desired"])
            base, _, done, _, info = env.step(self._actions[k])
            end = len(env.sim.log["desired"])
            r = np.zeros(self.n_max, dtype=np.float32)
            if self.cfg.kind == "v5":
                r[:n] = per_service_rewards_v5(env.sim, start, end, env.floor)
            else:
                r[:n] = per_service_rewards(env.sim, start, end, env.floor, self.cfg)
            self._base[k] = base
            agent_infos = [{} for _ in range(self.n_max)]
            if done:
                terminal = self._agent_obs(k)
                for j in range(self.n_max):
                    agent_infos[j] = {"terminal_observation": terminal[j], "TimeLimit.truncated": False}
                if "summary" in info:
                    agent_infos[0]["episode_summary"] = info["summary"]
                self._base[k], _ = env.reset()
            obs.append(self._agent_obs(k))
            rews.append(r)
            dones.append(np.full(self.n_max, done))
            infos.extend(agent_infos)
        return np.concatenate(obs), np.concatenate(rews), np.concatenate(dones), infos

    def close(self):
        pass

    def get_attr(self, attr_name, indices=None):
        return [getattr(self, attr_name, None)] * (len(indices) if indices is not None else self.num_envs)

    def set_attr(self, attr_name, value, indices=None):
        pass

    def env_method(self, method_name, *method_args, indices=None, **method_kwargs):
        return [None] * (len(indices) if indices is not None else self.num_envs)

    def env_is_wrapped(self, wrapper_class, indices=None):
        return [False] * (len(indices) if indices is not None else self.num_envs)

    def seed(self, seed=None):
        return [None] * self.num_envs
