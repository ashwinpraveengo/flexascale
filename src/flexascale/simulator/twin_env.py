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
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    """Per-step cap on the inflation (amended 2026-10-26 23:31, POLICY_V7 §4.2): uncapped, rare overload episodes
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
    d = json.loads(Path(path).read_text())
    return AppSpec.from_json(d), d["scenarios"]
