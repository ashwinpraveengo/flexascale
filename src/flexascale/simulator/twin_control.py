"""
Controllers for the application twin: native HPA, the FlexaScale operator loop, and rules.

* ``NativeHPA`` is the Kubernetes algorithm with the inputs it has live: metrics-server
  CPU per ready pod (60 s resolution) as % of request, a 15 s sync, 10% tolerance, the
  default scale-up policy (max of +100% and +4 pods per 15 s), and a scale-down
  stabilisation window (the highest recommendation of the last W seconds).
* ``OperatorLoop`` is ``AppOperator._decide`` reduced to what changes replicas: a decision
  every 10 s from Prometheus 1-minute rates, then the guards (bounds, scale-up cooldown,
  no scale-up while pods start, scale-down cooldown, scale-down blocks on CPU and latency,
  step limits). A *policy* maps the observation to a replica change per service.
* Policies: ``threshold_policy`` (the operator's CPU heuristic) and ``limit_target_policy``
  (proportional to CPU per replica relative to the limit, with hysteresis), plus any
  callable, e.g. the trained v7 network through ``rl/graph_policy.py``.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from flexascale.simulator.twin import TICK_S, AppSpec, TwinSim, Workload

SYNC_TICKS_HPA = 3        # 15 s
SYNC_TICKS_OPERATOR = 2   # 10 s


class NativeHPA:
    def __init__(self, target_pct: float = 70.0, window_s: float = 300.0, tolerance: float = 0.1) -> None:
        self.target, self.window_s, self.tol = target_pct, window_s, tolerance
        self.name = f"hpa(target={target_pct:g}%, window={window_s:g}s)"

    def reset(self, sim: TwinSim) -> None:
        self.hist: List[deque] = [deque() for _ in range(sim.n)]

    def tick(self, sim: TwinSim) -> None:
        if sim.t % SYNC_TICKS_HPA:
            return
        cpu = sim.metrics_server_cpu_pct()
        now = sim.t * TICK_S
        for i in range(sim.n):
            cur = len(sim.pods[i])
            ratio = cpu[i] / self.target if self.target > 0 else 1.0
            rec = cur if abs(ratio - 1.0) <= self.tol else int(math.ceil(cur * ratio - 1e-9))
            rec = int(np.clip(rec, sim.lo[i], sim.hi[i]))
            h = self.hist[i]
            h.append((now, rec))
            while h and h[0][0] < now - self.window_s:
                h.popleft()
            stab = max(r for _, r in h) if rec < cur else rec  # scale-down: highest recommendation in the window
            if stab > cur:
                stab = min(stab, max(2 * cur, cur + 4))
            sim.set_desired(i, stab)


@dataclass
class Guards:
    """The operator's guards (config/apps/*.yaml), in seconds and percent of request."""
    max_step: int = 1
    max_scale_down_step: int = 1
    scale_up_cooldown_s: float = 30.0
    scale_down_cooldown_s: float = 60.0
    scale_down_block_cpu_pct: float = 85.0
    scale_down_block_slo_ratio: Optional[float] = 1.0     # block scale-down when latency > ratio x SLO (None: off)
    slo_ms: Optional[Dict[str, float]] = None


V7_GUARDS = Guards(max_step=3, max_scale_down_step=1, scale_up_cooldown_s=20.0, scale_down_cooldown_s=30.0,
                   scale_down_block_cpu_pct=400.0, scale_down_block_slo_ratio=None)
"""Operator guards for v7 (config/apps/shopping_v7.yaml): scale-down never at >= 80% of the 500m limit (400% of
request), one replica down per 30 s, up to +3 per decision, 20 s between scale-ups; no single latency SLO."""


def observation(sim: TwinSim) -> Dict[str, np.ndarray]:
    """Per-service live inputs: what the operator can compute from Prometheus and the Kubernetes API."""
    prom = sim.prometheus()
    ready = np.maximum(sim.ready(), 1)
    desired = np.array([len(p) for p in sim.pods])
    return {
        "cpu_cores": prom["cpu_cores"], "rps": prom["rps"], "latency_ms": np.nan_to_num(prom["latency_ms"], nan=0.0),
        "ready": sim.ready(), "desired": desired,
        "cpu_pct_request": 100.0 * prom["cpu_cores"] / ready / sim.request,
        "cpu_frac_limit": prom["cpu_cores"] / ready / sim.limit,
    }


class OperatorLoop:
    def __init__(self, policy: Callable[[TwinSim, Dict[str, np.ndarray], "OperatorLoop"], np.ndarray], guards: Guards,
                 name: str = "operator") -> None:
        self.policy, self.g, self.name = policy, guards, name

    def reset(self, sim: TwinSim) -> None:
        self.last_up = np.full(sim.n, -1e9)
        self.last_down = np.full(sim.n, -1e9)
        self.state: Dict[str, Any] = {}
        if hasattr(self.policy, "reset"):
            self.policy.reset(sim)

    def tick(self, sim: TwinSim) -> None:
        if sim.t % SYNC_TICKS_OPERATOR:
            return
        obs = observation(sim)
        self.apply(sim, np.asarray(self.policy(sim, obs, self), dtype=int), obs)

    def apply(self, sim: TwinSim, deltas: np.ndarray, obs: Dict[str, np.ndarray]) -> np.ndarray:
        """The operator's guards (``AppOperator._decide``) on proposed replica changes; returns the applied changes."""
        now = sim.t * TICK_S
        ready = sim.ready()
        names = sim.app.names
        applied = np.zeros(sim.n, dtype=int)
        for i in range(sim.n):
            cur = len(sim.pods[i])
            d = int(np.clip(deltas[i], -self.g.max_scale_down_step, self.g.max_step))
            prop = int(np.clip(cur + d, sim.lo[i], sim.hi[i]))
            if prop > cur:
                if ready[i] < cur or now - self.last_up[i] < self.g.scale_up_cooldown_s:
                    prop = cur
            elif prop < cur:
                slo = (self.g.slo_ms or {}).get(names[i])
                if obs["cpu_pct_request"][i] >= self.g.scale_down_block_cpu_pct:
                    prop = cur
                elif slo and self.g.scale_down_block_slo_ratio and obs["latency_ms"][i] > self.g.scale_down_block_slo_ratio * slo:
                    prop = cur
                elif now - self.last_down[i] < self.g.scale_down_cooldown_s or ready[i] < cur:
                    prop = cur
            if prop != cur:
                sim.set_desired(i, prop)
                applied[i] = prop - cur
                if prop > cur:
                    self.last_up[i] = now
                else:
                    self.last_down[i] = now
        return applied


def threshold_policy(target_pct: float = 70.0):
    """The operator's CPU heuristic (``app_operator.heuristic_actions``): +-1 outside a 10% band."""
    def f(sim, obs, loop):
        c = obs["cpu_pct_request"]
        return np.where(c > target_pct * 1.1, 1, np.where(c < target_pct * 0.9, -1, 0))
    f.name = f"threshold({target_pct:g}% of request)"
    return f


def limit_target_policy(target_frac: float = 0.6, down_frac: float = 0.35, max_jump: int = 3):
    """
    Proportional rule on CPU per replica relative to the CPU *limit*: scale up to
    ceil(cores / (target x limit)) when above target; scale down by one when the service
    would stay below ``down_frac`` of the limit with one replica fewer.
    """
    def f(sim, obs, loop):
        cores = obs["cpu_cores"]
        cur = obs["desired"].astype(float)
        need = np.ceil(cores / (target_frac * sim.limit) - 1e-9)
        up = np.clip(need - cur, 0, max_jump)
        fewer = np.maximum(cur - 1, 1)
        down = (cores / (fewer * sim.limit) < down_frac) & (cur > sim.lo)
        return np.where(up > 0, up, np.where(down, -1, 0)).astype(int)
    f.name = f"limit_target({target_frac:g}/{down_frac:g} of limit)"
    return f


def simulate(app: AppSpec, workload: Workload, controller, seed: int = 0) -> Dict[str, Any]:
    sim = TwinSim(app, workload, seed=seed)
    controller.reset(sim)
    for _ in range(workload.ticks):
        controller.tick(sim)
        sim.step()
    out = sim.summary()
    out["recovery_s"] = recovery_time(sim, workload)
    out["controller"] = getattr(controller, "name", type(controller).__name__)
    out["workload"] = workload.name
    out["sim"] = sim
    return out


def recovery_time(sim: TwinSim, wl: Workload) -> Optional[float]:
    """Seconds from the first load decrease until total desired replicas are within 1 of the run's minimum total."""
    if not wl.phase_drops:
        return None
    d = np.array(sim.log["desired"]).sum(axis=1)
    k0 = wl.phase_drops[0]
    floor = d.min()
    for k in range(k0, len(d)):
        if d[k] <= floor + 1:
            return float((k - k0) * TICK_S)
    return float((len(d) - k0) * TICK_S)
