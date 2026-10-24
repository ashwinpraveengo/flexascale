"""
Dependency-aware, unit-free FlexaScale simulator (observation version 2).

Why it exists: the first simulator (``FlexaScaleEnv``) taught PPO to scale
every service up on every step. Three properties of that simulator made
"always scale up" the best policy, and none of them holds on a real cluster:

1. One absolute latency target (100 ms) for every trace service. Services whose
   trace latency is already above it could only reduce their penalty by adding
   replicas, without ever reaching the target.
2. All latency was the service's own queueing delay, so more replicas always
   meant lower latency. Real applications have latency that replicas cannot
   remove: calls to downstream services and shared dependencies (the shopping
   application's single PostgreSQL instance).
3. Raw request rates (trace: hundreds to thousands of req/s) and raw latencies
   were policy inputs; a live service at idle (0 req/s, no latency samples) was
   far outside the training distribution.

This environment keeps the trace demand, the action space, the 4-service chain
and the GNN input width, and changes the dynamics and the observation:

* Slot ``i`` calls slot ``i+1``. A random fraction of the callee's latency
  appears in the caller's latency.
* Each service has latency that replicas cannot remove, and with probability
  ``bottleneck_probability`` a shared dependency whose latency grows with the
  application's total load, independent of replica counts.
* Each service's SLO is ``slack x`` its latency when every service runs at the
  configured CPU target (no shared-dependency surge), so it is attainable by
  provisioning to the same target the operator is given.
* One app-wide traffic event (spike, ramp or drop) is overlaid on the trace.
* Observation per service (all unit-free, identical in simulation and live)::

      0 cpu / 100                 CPU used as a fraction of the CPU request
      1 memory / 100              memory as a fraction of the limit
      2 replicas / max_replicas
      3 request-rate trend        rate now / rate one step (one minute) ago
      4 latency / SLO

* Reward per service: ``slo + 0.3 efficiency + 0.1 stability + w_cost cost``
  with a bounded SLO penalty (``slo_penalty_cap``).
* ``control='focal'``: the agent decides for slot 0 only and is rewarded for
  slot 0 only, while its downstream services follow an HPA-like rule with
  random deviations. This is how the policy is used live (one decision per
  service, from a window with that service in slot 0) and gives each decision
  its own reward instead of an average over four services.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from gymnasium import spaces

from flexascale.config.env_config import EnvConfig
from flexascale.simulator.flexascale_env import FlexaScaleEnv

OBSERVATION_VERSION = 2
FEATURE_NAMES = ("cpu_fraction", "memory_fraction", "replica_fraction", "rps_trend", "latency_slo_ratio")
FEATURE_HIGH = np.array([1.0, 1.0, 1.0, 3.0, 5.0], dtype=np.float32)
FEATURE_LOW = np.array([0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)


def v2_features(
    cpu_pct: float,
    memory_pct: float,
    replicas: float,
    max_replicas: float,
    rps_trend: float,
    latency_ms: float,
    slo_ms: float,
) -> np.ndarray:
    """The version-2 policy input for one service (shared by simulator and live operator)."""
    vec = np.array(
        [
            cpu_pct / 100.0,
            memory_pct / 100.0,
            replicas / max(1.0, max_replicas),
            rps_trend,
            latency_ms / slo_ms if slo_ms > 0 else 0.0,
        ],
        dtype=np.float32,
    )
    vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(vec, FEATURE_LOW, FEATURE_HIGH)


class FlexaScaleEnvV2(FlexaScaleEnv):
    """Multi-service simulator with dependency, shared-bottleneck and SLO-relative dynamics."""

    def __init__(self, config: EnvConfig | None = None) -> None:
        config = config or EnvConfig(demand_model="normalized")
        if config.demand_model != "normalized":
            raise ValueError("FlexaScaleEnvV2 requires demand_model='normalized'.")
        if config.service_id is not None:
            raise ValueError("FlexaScaleEnvV2 simulates several services; service_id must be None.")
        if config.control not in ("all", "focal"):
            raise ValueError(f"Unknown control '{config.control}'.")
        self._episode_ready = False
        super().__init__(config)
        n = self.num_services
        self.observation_space = spaces.Box(
            low=np.tile(FEATURE_LOW, n), high=np.tile(FEATURE_HIGH, n), dtype=np.float32
        )
        self._raw: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Episode setup
    # ------------------------------------------------------------------

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        self._episode_ready = False
        super().reset(seed=seed, options=options)
        self._draw_episode()
        self._episode_ready = True
        obs = self._build_observation()
        return obs, self._build_info(reward_components=None)

    def _draw_episode(self) -> None:
        cfg = self.config
        rng = self.np_random
        sids = self._all_service_ids
        n, T = len(sids), len(self._sequence)

        # Service time s0 (ms): trace latency with the trace's own queueing removed.
        self._s0 = np.ones((T, n))
        self._base_demand = np.zeros((T, n))
        self._base_rps = np.zeros((T, n))
        self._mem = np.zeros((T, n))
        for t, step in enumerate(self._sequence):
            for i, sid in enumerate(sids):
                row = step.get(sid)
                if row is None:
                    continue
                rho_trace = min(float(row["cpu_utilization"]) / 100.0, 0.95)
                self._s0[t, i] = max(1.0, float(row["latency_ms"]) * (1.0 - rho_trace))
                self._base_demand[t, i] = self._scaled_demand(sid, row)
                self._base_rps[t, i] = max(0.0, float(row["request_rate"])) * max(1, int(row["replica_count"]))
                self._mem[t, i] = float(row["memory_utilization"])

        self._traffic = self._draw_traffic(T)
        self._coupling = np.append(rng.uniform(0.0, cfg.downstream_coupling_high, n - 1), 0.0)
        self._external = rng.uniform(0.0, cfg.external_latency_high, n)
        self._bottleneck_on = bool(rng.random() < cfg.bottleneck_probability)
        self._bottleneck_capacity = float(rng.uniform(0.7, 1.5))
        peak = np.maximum(self._base_demand.max(axis=0), 1e-9)
        self._load_index = (self._base_demand / peak).mean(axis=1) * self._traffic  # (T,)

        # SLO: slack x latency when every service runs at the configured CPU target
        # (the same target the operator is given), shared dependency at rest.
        s0_med = np.median(self._s0, axis=0)
        at_target = 1.0 / (1.0 - min(cfg.cpu_target_pct / 100.0, 0.95))
        base = np.zeros(n)
        for i in reversed(range(n)):
            base[i] = at_target * s0_med[i] + self._external[i] * s0_med[i]
            if i + 1 < n:
                base[i] += self._coupling[i] * base[i + 1]
        self._slo = base * rng.uniform(cfg.slo_slack_low, cfg.slo_slack_high, n)

    def _draw_traffic(self, T: int) -> np.ndarray:
        m = np.ones(T)
        self._traffic_kind = "none"
        if not self.config.traffic_events or T < 6:
            return m
        rng = self.np_random
        kind = str(rng.choice(["none", "spike", "ramp", "drop"], p=[0.25, 0.3, 0.25, 0.2]))
        self._traffic_kind = kind
        if kind == "spike":
            t0 = int(rng.integers(2, max(3, T - 5)))
            dur = int(rng.integers(3, 9))
            m[t0:t0 + dur] = rng.uniform(1.5, 3.0)
        elif kind == "ramp":
            t0 = int(rng.integers(0, T // 2))
            m[t0:] = np.linspace(1.0, rng.uniform(1.5, 2.5), T - t0)
        elif kind == "drop":
            t0 = int(rng.integers(2, max(3, T - 5)))
            m[t0:] = rng.uniform(0.2, 0.5)
        return m

    def step(self, action: Any):
        if self.config.control == "focal" and self._episode_ready:
            acts = np.asarray(action).flatten().tolist()
            acts = [int(acts[0])] + self._background_actions()
            return super().step(acts)
        return super().step(action)

    def _background_actions(self) -> list[int]:
        """HPA-like rule (70% target, 10% tolerance) with random deviations for slots 1..n-1."""
        cpu = self._simulate()["cpu_pct"]
        out = []
        for c in cpu[1:]:
            if self.np_random.random() < self.config.background_epsilon:
                out.append(int(self.np_random.integers(0, 3)))
            else:
                out.append(2 if c > 77 else (0 if c < 63 else 1))
        return out

    # ------------------------------------------------------------------
    # Dynamics
    # ------------------------------------------------------------------

    def _simulate(self) -> dict[str, np.ndarray]:
        t = self._step_idx
        n = self.num_services
        reps = np.array([max(1, self._simulated_replicas[s]) for s in self._all_service_ids], dtype=float)
        demand = self._base_demand[t] * self._traffic[t]
        rho = demand / (reps * 100.0)
        own = self._s0[t] / (1.0 - np.minimum(rho, 0.98)) * np.maximum(1.0, rho)
        g = 1.0
        if self._bottleneck_on:
            g = 1.0 / (1.0 - min(self._load_index[t] / self._bottleneck_capacity, 0.9))
        latency = np.zeros(n)
        for i in reversed(range(n)):
            latency[i] = own[i] + self._external[i] * self._s0[t, i] * g
            if i + 1 < n:
                latency[i] += self._coupling[i] * latency[i + 1]
        rps = self._base_rps[t] * self._traffic[t]
        if t > 0:
            prev = self._base_rps[t - 1] * self._traffic[t - 1]
            trend = np.where(prev > 0, rps / np.maximum(prev, 1e-9), 1.0)
        else:
            trend = np.ones(n)
        return {
            "cpu_pct": np.minimum(rho, 1.0) * 100.0,
            "memory_pct": self._mem[t],
            "replicas": reps,
            "rps_trend": trend,
            "rps": rps,
            "latency_ms": latency,
            "slo_ms": self._slo.copy(),
            "rho": rho,
            "traffic": float(self._traffic[t]),
            "bottleneck_factor": float(g),
            "traffic_event": self._traffic_kind,
            "bottleneck": self._bottleneck_on,
        }

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
        cfg = self.config
        w = cfg.reward_weights
        raw = self._raw
        comps = {"slo": 0.0, "efficiency": 0.0, "stability": 0.0, "cost": 0.0}
        total = 0.0
        scored = self._all_service_ids[:1] if cfg.control == "focal" else self._all_service_ids
        for i, sid in enumerate(scored):
            ratio = raw["latency_ms"][i] / raw["slo_ms"][i]
            slo = 1.0 if ratio <= 1.0 else max(-(ratio - 1.0), -cfg.slo_penalty_cap)
            eff = -abs(raw["cpu_pct"][i] - cfg.cpu_target_pct) / 100.0
            stab = -float(abs(self._simulated_replicas[sid] - self._prev_replicas[sid]))
            cost = -float(self._simulated_replicas[sid]) / float(cfg.max_replicas)
            total += (w.get("slo", 1.0) * slo + w.get("efficiency", 0.3) * eff
                      + w.get("stability", 0.1) * stab + w.get("cost", 0.0) * cost)
            comps["slo"] += slo
            comps["efficiency"] += eff
            comps["stability"] += stab
            comps["cost"] += cost
        n = len(scored)
        return float(total / n), {k: v / n for k, v in comps.items()}

    def _build_info(self, reward_components: dict[str, float] | None) -> dict[str, Any]:
        info: dict[str, Any] = {
            "step_idx": self._step_idx,
            "timestep": self._step_idx,
            "service_ids": list(self._all_service_ids),
            "replicas_dict": self._simulated_replicas.copy(),
            "slo_violated": False,
        }
        if self._episode_ready:
            self._build_observation()
            raw = self._raw
            info["raw"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in raw.items()}
            info["slo_violations"] = int((raw["latency_ms"] > raw["slo_ms"]).sum())
            info["slo_violated"] = info["slo_violations"] > 0
            info["focal_violation"] = bool(raw["latency_ms"][0] > raw["slo_ms"][0])
        if reward_components is not None:
            info["reward_components"] = reward_components
        return info
