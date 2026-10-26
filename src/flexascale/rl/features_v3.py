"""
Observation version 3: per-service inputs for the v7 graph policy (docs/POLICY_V7.md §4).

Shared, line for line, by the twin environment (``simulator/twin_env.py``) and the live
operator (``operator/app_operator.py``), so a feature means the same thing in training and
on the cluster. Every input is something the operator can compute from Prometheus
(1-minute rates) and the Kubernetes API, and every input is unit-free:

==  =====================  ==============================================================
0   cpu_limit_frac         CPU per ready replica / CPU *limit* (not the request), clip 0–2
1   cpu_limit_trend        change of feature 0 since the previous decision, clip −1–1
2   rps_trend              request rate now / ~60 s ago, clip 0–3 (1 when unknown)
3   latency_inflation      log2(latency / the service's own low-load latency), clip −1–4
4   replica_frac           replicas / max replicas
5   ready_frac             ready / desired replicas
6   cpu_per_request        log10(CPU-milliseconds per request) / 3, clip 0–1 (0 when unknown)
7   burstiness             log2(peak / mean request rate over ~5 min), clip 0–3
8   since_scale_up         seconds since this service last scaled up / 60, clip 0–1
9   since_scale_down       seconds since it last scaled down / 60, clip 0–1
==  =====================  ==============================================================

Why these, given the diagnosis (§1): CPU relative to the *limit* is how close a pod is to
throttling (v5 saw CPU/request capped at 1.0). Latency inflation relative to the service's
own baseline replaces one SLO for every service (user-service's bcrypt latency is normal
at 1 s). CPU per request and burstiness tell services apart (order-service: 16 ms per
request and spiky; catalog: 2 ms), which a single HPA target cannot. The graph policy sees
its neighbours' features through message passing over the application's call graph.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Dict, List, Optional, Sequence

import numpy as np

OBSERVATION_VERSION = 3
FEATURES = ("cpu_limit_frac", "cpu_limit_trend", "rps_trend", "latency_inflation", "replica_frac", "ready_frac",
            "cpu_per_request", "burstiness", "since_scale_up", "since_scale_down")
F = len(FEATURES)
LOW = np.array([0, -1, 0, -1, 0, 0, 0, 0, 0, 0], dtype=np.float32)
HIGH = np.array([2, 1, 3, 4, 1, 1, 1, 3, 1, 1], dtype=np.float32)
TREND_S = 60.0
BURST_S = 300.0
BASELINE_S = 1800.0


class FeatureTracker:
    """Keeps the short histories the features need, per service; call ``update`` once per decision."""

    def __init__(self, services: Sequence[str], max_replicas: int = 10) -> None:
        self.services = list(services)
        self.max_replicas = max_replicas
        self.rps_hist: Dict[str, deque] = defaultdict(deque)   # services may appear later (live discovery)
        self.lat_hist: Dict[str, deque] = defaultdict(deque)
        self.prev_cpu: Dict[str, float] = {}
        self.cpr: Dict[str, float] = {}
        self.last_up: Dict[str, float] = {}
        self.last_down: Dict[str, float] = {}

    def note_scale(self, service: str, direction: int, now: float) -> None:
        if direction > 0:
            self.last_up[service] = now
        elif direction < 0:
            self.last_down[service] = now

    def update(self, now: float, service: str, *, cpu_cores: Optional[float], ready: int, desired: int,
               cpu_limit: float, rps: Optional[float], latency_ms: Optional[float]) -> np.ndarray:
        ready_n = max(1, int(ready))
        cpu = None if cpu_cores is None else float(cpu_cores) / ready_n / max(cpu_limit, 1e-6)
        x = np.zeros(F, dtype=np.float32)
        x[0] = 0.0 if cpu is None else cpu
        prev = self.prev_cpu.get(service)
        x[1] = 0.0 if (cpu is None or prev is None) else cpu - prev
        if cpu is not None:
            self.prev_cpu[service] = cpu

        h = self.rps_hist[service]
        if rps is not None and math.isfinite(rps):
            h.append((now, float(rps)))
        while h and now - h[0][0] > BURST_S:
            h.popleft()
        old = [r for t, r in h if now - t >= 0.75 * TREND_S]
        if rps is None or not old:
            x[2] = 1.0
        else:
            base = old[-1]
            x[2] = (3.0 if rps > 0 else 1.0) if base <= 0 else float(rps) / base
        rates = [r for _, r in h]
        mean = sum(rates) / len(rates) if rates else 0.0
        x[7] = math.log2(max(rates) / mean) if rates and mean > 0 else 0.0

        lh = self.lat_hist[service]
        if latency_ms is not None and math.isfinite(latency_ms) and latency_ms > 0:
            lh.append((now, float(latency_ms)))
        while lh and now - lh[0][0] > BASELINE_S:
            lh.popleft()
        if latency_ms and lh:
            base_lat = min(v for _, v in lh)
            x[3] = math.log2(max(latency_ms, 1e-3) / max(base_lat, 1e-3))
        x[4] = min(1.0, desired / max(1, self.max_replicas))
        x[5] = min(1.0, ready / max(1, desired))
        if cpu_cores is not None and rps is not None and rps > 1.0:
            est = 1000.0 * float(cpu_cores) / float(rps)      # CPU-ms per request (includes idle share)
            self.cpr[service] = est if service not in self.cpr else 0.8 * self.cpr[service] + 0.2 * est
        c = self.cpr.get(service)
        x[6] = 0.0 if not c else math.log10(max(c, 1.0)) / 3.0
        x[8] = min(1.0, (now - self.last_up.get(service, -1e9)) / 60.0)
        x[9] = min(1.0, (now - self.last_down.get(service, -1e9)) / 60.0)
        return np.clip(np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0), LOW, HIGH)


def pack(features: Dict[str, np.ndarray], services: Sequence[str], edges: Sequence[tuple], n_max: int) -> np.ndarray:
    """Flat observation: node features (n_max x F), adjacency caller->callee (n_max x n_max), node mask (n_max)."""
    services = list(services)
    if len(services) > n_max:
        raise ValueError(f"{len(services)} services exceed the policy's capacity of {n_max}")
    idx = {s: i for i, s in enumerate(services)}
    x = np.zeros((n_max, F), dtype=np.float32)
    for s in services:
        x[idx[s]] = features[s]
    adj = np.zeros((n_max, n_max), dtype=np.float32)
    for u, v in edges:
        if u in idx and v in idx and u != v:
            adj[idx[u], idx[v]] = 1.0
    mask = np.zeros(n_max, dtype=np.float32)
    mask[: len(services)] = 1.0
    return np.concatenate([x.ravel(), adj.ravel(), mask])


def obs_dim(n_max: int) -> int:
    return n_max * F + n_max * n_max + n_max


def unpack(obs: np.ndarray, n_max: int):
    x = obs[..., : n_max * F].reshape(*obs.shape[:-1], n_max, F)
    adj = obs[..., n_max * F: n_max * F + n_max * n_max].reshape(*obs.shape[:-1], n_max, n_max)
    mask = obs[..., n_max * F + n_max * n_max:]
    return x, adj, mask
