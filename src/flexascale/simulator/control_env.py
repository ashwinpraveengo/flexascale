"""
Control-loop simulator for FlexaScale (observation version 2, v6 policy).

Why it exists: v5 beat the HPA-like rule in ``FlexaScaleEnvV2`` but not native
HPA on the cluster. The live decision logs showed why: the live loop does not
behave like the simulator the policy was trained in.

* v2 takes one decision per trace minute and a new replica serves at once.
  Live, the operator decides every 15 s, a new pod is ready after 10-15 s
  (median 10 s over 510 live scale-ups), and the CPU it sees is a 1-minute
  Prometheus rate, so it lags the load.
* v2 has no operator guards. Live, about a third of v5's scale-ups on a ramp
  were blocked by them (cooldown, readiness wait).
* v2's actions are +-1 replica. Native HPA jumps to ``ceil(n x cpu / target)``
  in one step, so on a ramp a +-1 controller falls behind.
* v2 compares with a stateless threshold rule. Native HPA also holds replicas
  for 5 minutes after load falls (scale-down stabilisation), which costs
  replica-hours.

``FlexaScaleEnvV3`` keeps v2's trace demand, dependency chain, shared
bottleneck, SLOs, traffic events, observation and reward, and adds:

* ``substeps`` control steps per trace minute (demand linearly interpolated);
* actions are replica *deltas* (``action_deltas``, default -2..+3);
* new replicas become ready after ``startup_delay_steps`` (+1 with prob. 0.3);
  capacity and latency use ready replicas, cost uses requested replicas;
* observed CPU is the mean over ``cpu_window_steps``; the rate trend compares
  with ``trend_lookback_steps`` ago;
* slot 0 (the agent) is subject to the live operator's guards: scale-up
  cooldown, no scale-up while replicas are starting, scale-down cooldown and
  step limit, no scale-down above ``scale_down_block_cpu_pct`` CPU or above
  the SLO;
* background slots follow the native HPA algorithm (target, tolerance,
  scale-up limit max(2x, +4) per step, scale-down stabilisation window) with
  ``background_epsilon`` random deviations;
* ``slot0_controller='hpa'`` replaces the agent with that same HPA algorithm,
  which is the baseline the policy must beat.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any

import numpy as np
from gymnasium import spaces

from flexascale.config.env_config import EnvConfig
from flexascale.simulator.dependency_env import FlexaScaleEnvV2, v2_features


def hpa_recommendation(current: int, cpu_pct: float, cfg: EnvConfig) -> int:
    """Native HPA's per-sync recommendation (before stabilisation) for one Deployment."""
    ratio = cpu_pct / cfg.cpu_target_pct
    if abs(ratio - 1.0) <= cfg.hpa_tolerance:
        return current
    rec = int(math.ceil(current * ratio - 1e-9))
    rec = min(rec, max(2 * current, current + 4))  # default scale-up policy per 15 s
    return int(np.clip(rec, cfg.min_replicas, cfg.max_replicas))


class FlexaScaleEnvV3(FlexaScaleEnvV2):
    """v2 dynamics with a 15-second control loop, start-up delay, metric lag, guards and native HPA."""

    def __init__(self, config: EnvConfig | None = None) -> None:
        config = config or EnvConfig(demand_model="normalized", control="focal")
        if config.control != "focal":
            raise ValueError("FlexaScaleEnvV3 supports control='focal' only (one decision per service, as live).")
        super().__init__(config)
        self.deltas = np.asarray(config.action_deltas, dtype=int)
        self.action_space = spaces.MultiDiscrete([len(self.deltas)] * self.num_services)
        self.slot0_controller = "agent"
        self._k = 0

    # ------------------------------------------------------------------
    # Episode
    # ------------------------------------------------------------------

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        options = options or {}
        self.slot0_controller = options.get("slot0_controller", self.slot0_controller)
        self._episode_ready = False
        FlexaScaleEnvV2.__bases__[0].reset(self, seed=seed, options=options)  # base: services, replicas
        self._draw_episode()
        cfg = self.config
        n = self.num_services
        self._k = 0
        self._K = len(self._sequence) * cfg.substeps
        self._desired = np.array([self._simulated_replicas[s] for s in self._all_service_ids], dtype=int)
        self._prev_desired = self._desired.copy()
        self._pending: list[list[tuple[int, int]]] = [[] for _ in range(n)]
        self._last_up = np.full(n, -10_000)
        self._last_down = np.full(n, -10_000)
        self._recs = [deque(maxlen=max(1, cfg.hpa_stabilization_steps)) for _ in range(n)]
        self._cpu_hist = [deque(maxlen=max(1, cfg.cpu_window_steps)) for _ in range(n)]
        self._rps_hist: deque = deque(maxlen=cfg.trend_lookback_steps + 1)
        self._episode_ready = True
        raw = self._dynamics()
        for i in range(n):
            self._cpu_hist[i].append(raw["cpu_true"][i])
        self._rps_hist.append(raw["rps"])
        obs = self._build_observation()
        return obs, self._build_info(reward_components=None)

    @property
    def episode_length(self) -> int:
        return len(self._sequence) * self.config.substeps

    # ------------------------------------------------------------------
    # Dynamics
    # ------------------------------------------------------------------

    def _ready(self) -> np.ndarray:
        return np.array([self._desired[i] - sum(c for _, c in self._pending[i]) for i in range(self.num_services)])

    def _interp(self, arr: np.ndarray) -> np.ndarray:
        sub = self.config.substeps
        t0 = min(self._k // sub, len(arr) - 1)
        t1 = min(t0 + 1, len(arr) - 1)
        f = (self._k % sub) / sub
        return arr[t0] * (1.0 - f) + arr[t1] * f

    def _dynamics(self) -> dict[str, np.ndarray]:
        n = self.num_services
        ready = np.maximum(1, self._ready()).astype(float)
        traffic = float(self._interp(self._traffic[:, None])[0])
        demand = self._interp(self._base_demand) * traffic
        s0 = self._interp(self._s0)
        rho = demand / (ready * 100.0)
        own = s0 / (1.0 - np.minimum(rho, 0.98)) * np.maximum(1.0, rho)
        g = 1.0
        if self._bottleneck_on:
            load = float(self._interp(self._load_index[:, None])[0])
            g = 1.0 / (1.0 - min(load / self._bottleneck_capacity, 0.9))
        latency = np.zeros(n)
        for i in reversed(range(n)):
            latency[i] = own[i] + self._external[i] * s0[i] * g
            if i + 1 < n:
                latency[i] += self._coupling[i] * latency[i + 1]
        return {
            "cpu_true": np.minimum(rho, 1.0) * 100.0,
            "memory_pct": self._interp(self._mem),
            "rps": self._interp(self._base_rps) * traffic,
            "latency_ms": latency,
            "rho": rho,
            "ready": ready,
            "traffic": traffic,
            "bottleneck_factor": float(g),
        }

    def _simulate(self) -> dict[str, np.ndarray]:
        raw = self._dynamics()
        cpu_obs = np.array([np.mean(h) if h else c for h, c in zip(self._cpu_hist, raw["cpu_true"])])
        prev = self._rps_hist[0] if len(self._rps_hist) > self.config.trend_lookback_steps else None
        if prev is None:
            trend = np.ones(self.num_services)
        else:
            trend = np.where(prev > 0, raw["rps"] / np.maximum(prev, 1e-9), 1.0)
        raw.update({
            "cpu_pct": cpu_obs,
            "replicas": self._desired.astype(float),
            "rps_trend": trend,
            "slo_ms": self._slo.copy(),
            "traffic_event": self._traffic_kind,
            "bottleneck": self._bottleneck_on,
        })
        return raw

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def _apply(self, i: int, target: int) -> None:
        cfg = self.config
        cur = int(self._desired[i])
        target = int(np.clip(target, cfg.min_replicas, cfg.max_replicas))
        if target > cur:
            delay = cfg.startup_delay_steps + int(self.np_random.random() < 0.3)
            self._pending[i].append((self._k + delay, target - cur))
            self._last_up[i] = self._k
        elif target < cur:
            remove = cur - target
            while remove > 0 and self._pending[i]:  # starting pods go first
                ready_at, c = self._pending[i].pop()
                take = min(c, remove)
                if c > take:
                    self._pending[i].append((ready_at, c - take))
                remove -= take
            self._last_down[i] = self._k
        self._desired[i] = target

    def guarded_target(self, i: int, delta: int, raw: dict[str, np.ndarray]) -> tuple[int, str]:
        """Apply the live operator's guards (app_operator._decide) to a proposed change."""
        cfg = self.config
        cur = int(self._desired[i])
        target = int(np.clip(cur + delta, cfg.min_replicas, cfg.max_replicas))
        if target > cur:
            if self._ready()[i] < cur:
                return cur, "scale_up_waiting_for_readiness"
            if self._k - self._last_up[i] < cfg.scale_up_cooldown_steps:
                return cur, "scale_up_cooldown"
        elif target < cur:
            target = max(target, cur - cfg.max_scale_down_step)
            if raw["cpu_pct"][i] >= cfg.scale_down_block_cpu_pct:
                return cur, "scale_down_blocked_cpu"
            if raw["latency_ms"][i] > raw["slo_ms"][i]:
                return cur, "scale_down_blocked_slo"
            if self._k - self._last_down[i] < cfg.scale_down_cooldown_steps:
                return cur, "scale_down_cooldown"
            if self._ready()[i] < cur:
                return cur, "scale_down_waiting_for_readiness"
        return target, "accepted"

    def _hpa_target(self, i: int, cpu_pct: float) -> int:
        cur = int(self._desired[i])
        rec = hpa_recommendation(cur, cpu_pct, self.config)
        self._recs[i].append(rec)
        if rec > cur:
            return rec
        return min(cur, max(self._recs[i]))  # scale-down stabilisation: highest recent recommendation

    def step(self, action: Any):
        cfg = self.config
        n = self.num_services
        raw = self._raw if self._raw else self._simulate()
        self._prev_desired = self._desired.copy()
        acts = np.asarray(action).flatten().tolist()
        self._last_guard = "accepted"
        if self.slot0_controller == "hpa":
            self._apply(0, self._hpa_target(0, raw["cpu_pct"][0]))
        else:
            a = int(acts[0]) if acts else int(np.where(self.deltas == 0)[0][0])
            target, self._last_guard = self.guarded_target(0, int(self.deltas[a]), raw)
            self._apply(0, target)
        for i in range(1, n):
            if self.np_random.random() < cfg.background_epsilon:
                self._apply(i, int(self._desired[i]) + int(self.np_random.integers(-1, 2)))
            else:
                self._apply(i, self._hpa_target(i, raw["cpu_pct"][i]))

        self._k += 1
        for i in range(n):  # replicas whose start-up has finished
            self._pending[i] = [(r, c) for r, c in self._pending[i] if r > self._k]
        for sid, d in zip(self._all_service_ids, self._desired):
            self._prev_replicas[sid] = self._simulated_replicas[sid]
            self._simulated_replicas[sid] = int(d)
        if self._k >= self._K:
            self._k = self._K - 1
            obs = self._build_observation()
            return obs, 0.0, True, False, self._build_info(reward_components=None)
        dyn = self._dynamics()
        for i in range(n):
            self._cpu_hist[i].append(dyn["cpu_true"][i])
        self._rps_hist.append(dyn["rps"])
        obs = self._build_observation()
        reward, comps = self._compute_reward(obs)
        return obs, reward, False, False, self._build_info(reward_components=comps)

    def _build_observation(self) -> np.ndarray:
        if not self._episode_ready:
            return np.zeros(self.observation_space.shape if hasattr(self, "observation_space") else 0, dtype=np.float32)
        raw = self._simulate()
        self._raw = raw
        parts = [
            v2_features(raw["cpu_pct"][i], raw["memory_pct"][i], raw["replicas"][i], self.config.max_replicas,
                        raw["rps_trend"][i], raw["latency_ms"][i], raw["slo_ms"][i])
            for i in range(self.num_services)
        ]
        return np.concatenate(parts).astype(np.float32)

    def _compute_reward(self, obs: np.ndarray) -> tuple[float, dict[str, float]]:
        """v2 reward for slot 0; ``eff`` uses the true (not lagged) CPU."""
        cfg = self.config
        w = cfg.reward_weights
        raw = self._raw
        ratio = raw["latency_ms"][0] / raw["slo_ms"][0]
        slo = 1.0 if ratio <= 1.0 else max(-(ratio - 1.0), -cfg.slo_penalty_cap)
        eff = -abs(raw["cpu_true"][0] - cfg.cpu_target_pct) / 100.0
        stab = -float(abs(self._desired[0] - self._prev_desired[0]))
        cost = -float(self._desired[0]) / float(cfg.max_replicas)
        total = (w.get("slo", 1.0) * slo + w.get("efficiency", 0.3) * eff
                 + w.get("stability", 0.1) * stab + w.get("cost", 0.0) * cost)
        return float(total), {"slo": slo, "efficiency": eff, "stability": stab, "cost": cost}

    def _build_info(self, reward_components: dict[str, float] | None) -> dict[str, Any]:
        info = super()._build_info(reward_components)
        if self._episode_ready:
            info["guard"] = getattr(self, "_last_guard", "accepted")
            info["ready"] = self._ready().tolist()
        return info
