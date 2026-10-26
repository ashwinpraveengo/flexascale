"""
Calibrated application simulator ("twin") for FlexaScale v7 (docs/POLICY_V7.md §4).

Why it exists: the v4–v6 simulators made native HPA's rule optimal by construction
(capacity per replica = the CPU *request*, SLO defined at the 70% target), and they
never saw the application FlexaScale is evaluated on. This simulator is built from
what the live runs measured instead (``scripts/fit_twin.py``):

* CPU demand per service = ``cpu_per_req x arrival rate + idle_cores x replicas``
  (least-squares fit on 3,758 samples per service, R² 0.74–0.95).
* Capacity per replica = the container's CPU *limit* (500m in the shop). Work above
  it queues (a backlog of CPU-seconds), so latency rises steeply only near the limit,
  as measured. ``serial`` services (bcrypt login in user-service) serve one request
  at a time per replica, so bursts queue even at moderate average CPU.
* Latency per service = its measured low-load latency, plus CPU queueing
  (processor sharing, ``S/(1-u)``), plus the queue wait, plus the *excess* latency
  of the services it calls (weighted by the fraction of its requests that call them).
* Pods are ready 10 s after creation (15 s with probability 0.3; live median 10 s,
  p90 15 s over 510 scale-ups).
* Controllers see what they see live: FlexaScale a 1-minute Prometheus rate scraped
  every 30 s, native HPA a metrics-server value with 60 s resolution.

End-to-end latency is reported per Locust request class (browse, cart, checkout,
orders, login; ``Workload.classes``), each lognormal around its fitted base latency
plus the excess latency on its path; the run's p95 is the 95th percentile of the
traffic-weighted mixture of all requests, the analogue of Locust's aggregated p95.

The simulator is deterministic given its seed. One tick is 5 s (the lab's
sampling interval).
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

TICK_S = 5.0
PROM_WINDOW_TICKS = 12      # rate[1m]
PROM_SCRAPE_TICKS = 6       # cAdvisor scraped every 30 s
MS_RESOLUTION_TICKS = 12    # metrics-server --metric-resolution=60s
LOGNORMAL_SIGMA = 0.8
REQUEST_TIMEOUT_S = 10.0
LAT_GRID = np.exp(np.linspace(np.log(0.5), np.log(120000.0), 400))  # ms, for end-to-end latency distributions


def _erf(x: np.ndarray) -> np.ndarray:
    """Vectorised error function (Abramowitz & Stegun 7.1.26, |error| < 1.5e-7)."""
    sign = np.sign(x)
    x = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return sign * y


@dataclass
class ServiceSpec:
    name: str
    cpu_per_req: float          # CPU-seconds per request
    idle_cores: float           # cores per replica at no load
    base_latency_ms: float      # measured mean latency at low load (includes downstream base latency)
    cpu_limit: float = 0.5
    cpu_request: float = 0.1
    min_replicas: int = 1
    max_replicas: int = 10
    serial: bool = False        # one request at a time per replica (blocking handler)


@dataclass
class AppSpec:
    name: str
    services: List[ServiceSpec]
    edges: List[Tuple[str, str]]                       # caller -> callee
    fanout: Dict[str, float] = field(default_factory=dict)
    """'caller->callee' -> fraction of the caller's requests that call the callee (excess-latency weight)."""
    entry: str = "api-gateway"

    def index(self) -> Dict[str, int]:
        return {s.name: i for i, s in enumerate(self.services)}

    @property
    def names(self) -> List[str]:
        return [s.name for s in self.services]

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        d["edges"] = [list(e) for e in self.edges]
        return d

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> "AppSpec":
        return cls(name=d["name"], services=[ServiceSpec(**s) for s in d["services"]],
                   edges=[tuple(e) for e in d["edges"]], fanout=dict(d.get("fanout") or {}),
                   entry=d.get("entry", "api-gateway"))

    @classmethod
    def load(cls, path: str | Path) -> "AppSpec":
        return cls.from_json(json.loads(Path(path).read_text()))


@dataclass
class Workload:
    """Per-tick arrival rates (req/s) for every service, in AppSpec order."""
    name: str
    rates: np.ndarray           # (T, N)
    e2e_rps: np.ndarray         # (T,)
    users: np.ndarray           # (T,)
    phase_drops: List[int] = field(default_factory=list)
    """Ticks at which the user count falls (for recovery-time metrics)."""
    classes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    """Locust request classes: name -> {share, base_ms, sigma, services} (fitted per scenario, scripts/fit_twin.py)."""
    think_s: Optional[float] = None
    """Closed loop: Locust users wait for each response, then think. Arrival rates are scaled by
    (think + base latency) / (think + current latency); None = open loop."""

    @property
    def ticks(self) -> int:
        return int(self.rates.shape[0])


# ---------------------------------------------------------------------------
# Observations as the two controllers see them
# ---------------------------------------------------------------------------


class MetricView:
    """Windowed, scraped view of a per-tick series (1-minute rate, sampled every scrape interval)."""

    def __init__(self, n: int, window: int, refresh: int, idle: Optional[np.ndarray] = None, phase: int = 0) -> None:
        self.window, self.refresh = window, refresh
        self.hist: deque = deque(maxlen=window)
        # Runs start from an idle, settled application (comparable start): the window is full of idle samples.
        x0 = np.zeros(n) if idle is None else np.asarray(idle, dtype=float)
        for _ in range(window):
            self.hist.append((x0.copy(), None))
        self.value = x0.copy()
        self._since = phase  # scrape/resolution cycles are not aligned with the run start

    def update(self, x: np.ndarray, weights: Optional[np.ndarray] = None) -> None:
        self.hist.append((np.asarray(x, dtype=float).copy(), None if weights is None else np.asarray(weights, float).copy()))
        self._since += 1
        if self._since >= self.refresh:
            self._since = 0
            if not self.hist:
                return
            xs = np.stack([h[0] for h in self.hist])
            if self.hist[0][1] is None:
                self.value = xs.mean(axis=0)
            else:
                ws = np.stack([h[1] for h in self.hist])
                tot = ws.sum(axis=0)
                self.value = np.where(tot > 0, (xs * ws).sum(axis=0) / np.maximum(tot, 1e-12), np.nan)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


class TwinSim:
    """One application under one workload; controllers set desired replicas between ticks."""

    def __init__(self, app: AppSpec, workload: Workload, seed: int = 0, startup_ticks: Tuple[int, int, float] = (2, 3, 0.3)) -> None:
        self.app, self.wl = app, workload
        self.rng = np.random.default_rng(seed)
        self.n = len(app.services)
        idx = app.index()
        self.limit = np.array([s.cpu_limit for s in app.services])
        self.request = np.array([s.cpu_request for s in app.services])
        self.c = np.array([s.cpu_per_req for s in app.services])
        self.idle = np.array([s.idle_cores for s in app.services])
        self.base = np.array([s.base_latency_ms for s in app.services])
        self.serial = np.array([s.serial for s in app.services])
        self.lo = np.array([s.min_replicas for s in app.services])
        self.hi = np.array([s.max_replicas for s in app.services])
        self.startup = startup_ticks
        # callers before callees is not guaranteed; latency is resolved callees-first by topological order
        self.callees: List[List[Tuple[int, float]]] = [[] for _ in range(self.n)]
        for u, v in app.edges:
            if u in idx and v in idx:
                self.callees[idx[u]].append((idx[v], float(app.fanout.get(f"{u}->{v}", 1.0))))
        self.order = self._callees_first_order()
        self.t = 0
        self.desired = self.lo.astype(int).copy()
        self.pods: List[List[int]] = [[-10] * int(self.lo[i]) for i in range(self.n)]  # ready-at tick per pod
        self.backlog = np.zeros(self.n)            # CPU-seconds waiting
        idle_cpu = self.idle * self.lo
        ph = int(self.rng.integers(0, PROM_SCRAPE_TICKS))
        self.prom_cpu = MetricView(self.n, PROM_WINDOW_TICKS, PROM_SCRAPE_TICKS, idle=idle_cpu, phase=ph)
        self.prom_rps = MetricView(self.n, PROM_WINDOW_TICKS, PROM_SCRAPE_TICKS, phase=ph)
        self.prom_lat = MetricView(self.n, PROM_WINDOW_TICKS, PROM_SCRAPE_TICKS, phase=ph)
        self.prom_lat.hist.clear()
        self.ms_cpu = MetricView(self.n, MS_RESOLUTION_TICKS, MS_RESOLUTION_TICKS, idle=idle_cpu,
                                 phase=int(self.rng.integers(0, MS_RESOLUTION_TICKS)))
        self.log: Dict[str, List[Any]] = {k: [] for k in ("desired", "ready", "cpu", "lat", "e2e_p95", "e2e_mean",
                                                          "fail_frac", "rps", "u", "e2e_p95_base", "events", "replica_changes")}
        self._p95_base = float("nan")
        self.events = 0
        self.replica_changes = 0                   # replicas added or removed (the reward's churn unit)
        self.direction = np.zeros(self.n)          # last scaling direction per service (oscillation count)
        self.oscillations = 0
        self.agg_cdf = np.zeros_like(LAT_GRID)     # request-weighted end-to-end latency CDF over the run
        self.agg_weight = 0.0
        self._prev_e2e_mean: Optional[float] = None
        self._throttle = 1.0
        self._login_col = np.array([s.serial for s in app.services])  # spawn-driven (login) arrivals are not throttled

    def _callees_first_order(self) -> List[int]:
        seen, out = set(), []

        def visit(i, stack):
            if i in seen or i in stack:
                return
            stack.add(i)
            for j, _ in self.callees[i]:
                visit(j, stack)
            stack.discard(i)
            seen.add(i)
            out.append(i)

        for i in range(self.n):
            visit(i, set())
        return out

    # -- control interface ---------------------------------------------------

    def ready(self) -> np.ndarray:
        return np.array([sum(1 for r in p if r <= self.t) for p in self.pods])

    def set_desired(self, i: int, replicas: int) -> None:
        replicas = int(np.clip(replicas, self.lo[i], self.hi[i]))
        cur = len(self.pods[i])
        if replicas == cur:
            return
        d = 1 if replicas > cur else -1
        if self.direction[i] and d != self.direction[i]:
            self.oscillations += 1
        self.direction[i] = d
        self.events += 1
        self.replica_changes += abs(replicas - cur)
        if replicas > cur:
            for _ in range(replicas - cur):
                delay = self.startup[1] if self.rng.random() < self.startup[2] else self.startup[0]
                self.pods[i].append(self.t + delay)
        else:
            # Kubernetes removes not-ready pods first, then the newest
            self.pods[i].sort(key=lambda r: (r <= self.t, -r))
            self.pods[i] = self.pods[i][cur - replicas:]
        self.desired[i] = replicas

    # -- one tick ----------------------------------------------------------------

    def step(self) -> Dict[str, Any]:
        t = min(self.t, self.wl.ticks - 1)
        lam = self.wl.rates[t].copy()
        if self.wl.think_s is not None and self._prev_e2e_mean is not None:
            base_mean = sum(c["share"] * c["base_ms"] for c in self.wl.classes.values()) / 1000.0
            factor = (self.wl.think_s + base_mean) / (self.wl.think_s + self._prev_e2e_mean / 1000.0)
            keep = self._login_col
            self._throttle = min(1.0, factor)
            lam = np.where(keep, lam, lam * self._throttle)
        ready = np.maximum(self.ready(), 0)
        cap = ready * self.limit                       # cores
        work = self.c * lam * TICK_S + self.idle * ready * TICK_S + self.backlog
        served = np.minimum(work, cap * TICK_S)
        self.backlog = work - served
        u = np.where(cap > 0, served / np.maximum(cap * TICK_S, 1e-9), 1.0)
        cpu_used = served / TICK_S
        # own latency: low-load latency + CPU queueing (processor sharing) + backlog wait
        svc_ms = 1000.0 * self.c
        wait_s = np.where(cap > 0, self.backlog / np.maximum(cap, 1e-9), REQUEST_TIMEOUT_S)
        ps = svc_ms * (1.0 / (1.0 - np.minimum(u, 0.95)) - 1.0)
        # serial handlers: a burst within a tick queues behind one request per replica
        burst = np.where(self.serial & (ready > 0), svc_ms * np.maximum(0.0, lam * TICK_S / np.maximum(ready, 1) - 1) / 2.0
                         * np.minimum(1.0, self.c * lam / np.maximum(cap, 1e-9)), 0.0)
        own = self.base + ps + 1000.0 * wait_s + burst
        lat = own.copy()
        for i in self.order:
            for j, f in self.callees[i]:
                lat[i] += f * max(0.0, lat[j] - self.base[j])
        fail = np.clip((wait_s - REQUEST_TIMEOUT_S) / REQUEST_TIMEOUT_S, 0.0, 1.0)
        e2e_mean, e2e_p95, fail_frac = self._e2e(lat, fail, lam)
        self._prev_e2e_mean = e2e_mean
        self.prom_cpu.update(cpu_used)
        self.prom_rps.update(lam)
        self.prom_lat.update(lat, weights=lam)
        self.ms_cpu.update(cpu_used)
        for k, v in (("desired", np.array([len(p) for p in self.pods])), ("ready", ready), ("cpu", cpu_used), ("lat", lat),
                     ("e2e_p95", e2e_p95), ("e2e_mean", e2e_mean), ("fail_frac", fail_frac), ("rps", float(self.wl.e2e_rps[t]) * self._throttle),
                     ("u", u), ("e2e_p95_base", self._p95_base), ("events", self.events),
                     ("replica_changes", self.replica_changes)):
            self.log[k].append(v)
        self.t += 1
        return {"u": u, "lat": lat, "e2e_p95": e2e_p95}

    def _e2e(self, lat: np.ndarray, fail: np.ndarray, lam: np.ndarray) -> Tuple[float, float, float]:
        if self.wl.classes:
            return self._e2e_classes(lat, fail)
        # no request mix known: one lognormal class around the entry service's latency
        entry = self.app.index().get(self.app.entry)
        tot = float(self.wl.e2e_rps[min(self.t, self.wl.ticks - 1)])
        m = max(float(lat[entry]) if entry is not None else float(lat.mean()), 0.1)
        z = (np.log(LAT_GRID) - (math.log(m) - LOGNORMAL_SIGMA ** 2 / 2)) / (LOGNORMAL_SIGMA * math.sqrt(2))
        w_tot = max(tot, 1e-9)
        self.agg_cdf += w_tot * 0.5 * (1.0 + _erf(z))
        self.agg_weight += w_tot
        q95 = math.exp(1.645 * LOGNORMAL_SIGMA - LOGNORMAL_SIGMA ** 2 / 2)
        self._p95_base = float(self.base[entry]) * q95 if entry is not None else float("nan")
        return m, m * q95, float(fail[entry]) if entry is not None else 0.0

    def _e2e_classes(self, lat: np.ndarray, fail: np.ndarray) -> Tuple[float, float, float]:
        """Locust request classes: fitted base latency plus the *excess* latency of the services on their path."""
        idx = self.app.index()
        entry = idx.get(self.app.entry)
        excess = np.maximum(0.0, lat - self.base)
        gw_excess = 0.0
        if entry is not None:  # the gateway's own queueing (its excess minus what it inherits from callees)
            gw_excess = max(0.0, excess[entry] - sum(f * excess[j] for j, f in self.callees[entry]))
        tot = float(self.wl.e2e_rps[min(self.t, self.wl.ticks - 1)]) * self._throttle
        shares, means, sigmas, fails = [], [], [], []
        for c in self.wl.classes.values():
            path = [idx[s] for s in c["services"] if s in idx]
            ex = float(np.mean([excess[j] for j in path])) if path else 0.0
            shares.append(float(c["share"]))
            means.append(float(c["base_ms"]) + ex + gw_excess)
            sigmas.append(float(c.get("sigma", LOGNORMAL_SIGMA)))
            fails.append(max([fail[j] for j in path] + ([fail[entry]] if entry is not None else [0.0])))
        w = np.array(shares) / max(sum(shares), 1e-12)
        m, sg = np.maximum(np.array(means), 0.1), np.array(sigmas)
        mu = np.log(m) - sg ** 2 / 2
        z = (np.log(LAT_GRID)[None, :] - mu[:, None]) / (sg[:, None] * math.sqrt(2))
        cdf = (w[:, None] * 0.5 * (1.0 + _erf(z))).sum(axis=0)
        self.agg_cdf += tot * cdf
        self.agg_weight += tot
        p95 = float(LAT_GRID[min(len(LAT_GRID) - 1, int(np.searchsorted(cdf, 0.95)))])
        # the same mixture with no excess latency: what this tick's p95 would be with ample capacity
        mb = np.maximum(np.array([float(c["base_ms"]) for c in self.wl.classes.values()]), 0.1)
        zb = (np.log(LAT_GRID)[None, :] - (np.log(mb) - sg ** 2 / 2)[:, None]) / (sg[:, None] * math.sqrt(2))
        cdf_b = (w[:, None] * 0.5 * (1.0 + _erf(zb))).sum(axis=0)
        self._p95_base = float(LAT_GRID[min(len(LAT_GRID) - 1, int(np.searchsorted(cdf_b, 0.95)))])
        return float((w * m).sum()), p95, float((w * np.array(fails)).sum())

    # -- views for controllers ---------------------------------------------------

    def prometheus(self) -> Dict[str, np.ndarray]:
        """What the FlexaScale operator reads: 1-minute rates, scraped every 30 s (per service totals)."""
        return {"cpu_cores": self.prom_cpu.value.copy(), "rps": self.prom_rps.value.copy(),
                "latency_ms": self.prom_lat.value.copy()}

    def metrics_server_cpu_pct(self) -> np.ndarray:
        """What native HPA reads: mean CPU per ready pod as % of request, 60 s resolution."""
        ready = np.maximum(self.ready(), 1)
        return 100.0 * self.ms_cpu.value / ready / self.request

    # -- results --------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        d = np.array(self.log["desired"])          # (T, N)
        r = np.array(self.log["ready"])
        p95 = np.array(self.log["e2e_p95"])
        mean = np.array(self.log["e2e_mean"])
        rps = np.array(self.log["rps"])
        fail = np.array(self.log["fail_frac"])
        w = np.maximum(rps, 1e-9)
        return {
            "replica_hours": float(r.sum() * TICK_S / 3600.0),
            "requested_replica_hours": float(d.sum() * TICK_S / 3600.0),
            "avg_replicas": float(r.sum(axis=1).mean()),
            "peak_replicas": int(d.sum(axis=1).max()),
            "p95_ms": self.run_quantile(0.95),
            "p50_ms": self.run_quantile(0.50),
            "mean_latency_ms": float((mean * w).sum() / w.sum()),
            "failure_pct": float(100.0 * (fail * w).sum() / w.sum()),
            "slo_violation_s": float((p95 > 1000.0).sum() * TICK_S),
            "scaling_events": int(self.events),
            "oscillations": int(self.oscillations),
        }

    def run_quantile(self, q: float) -> float:
        """Quantile of the latency of all requests in the run (Locust's aggregated percentile)."""
        if self.agg_weight <= 0:
            return float("nan")
        cdf = self.agg_cdf / self.agg_weight
        return float(LAT_GRID[min(len(LAT_GRID) - 1, int(np.searchsorted(cdf, q)))])
