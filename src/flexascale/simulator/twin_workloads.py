"""
Workloads for the application twin: the lab's Locust scenarios as per-service arrival rates.

The shapes reproduce ``load-testing/scenarios.py`` (user count over time, spawn rate)
and the request mix of each scenario as measured live (``scripts/fit_twin.py``):
end-to-end requests per user per second, and each service's request rate as a
fraction of the end-to-end rate. Shoppers log in once when they start
(``ShoppingCustomerUser.on_start``), which is what makes user-service bursty.

``random_workload`` draws training and validation workloads around these shapes:
other peaks, stage timings, request mixes and extra spikes or drops. It never
draws the exact evaluation conditions (fixed shape at 25 users) by construction
of its jitter, and the evaluation set is generated separately with fixed seeds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from flexascale.simulator.twin import TICK_S, AppSpec, Workload

MIXES = {  # load-testing/scenarios.py
    "steady_browsing": {"Browsing": 8, "Shopper": 2},
    "gradual_ramp": {"Browsing": 6, "Shopper": 4},
    "flash_sale": {"Browsing": 4, "Shopper": 2, "FlashSale": 4},
    "checkout_heavy": {"Browsing": 2, "Shopper": 7, "FlashSale": 1},
    "traffic_drop": {"Browsing": 6, "Shopper": 4},
    "payment_degradation": {"Browsing": 3, "Shopper": 3, "SlowPayment": 3, "DeclinedPayment": 1},
    "calibration_steady": {"Browsing": 5, "Shopper": 5},
}
EVALUATION_SCENARIOS = ("steady_browsing", "checkout_heavy", "payment_degradation", "flash_sale", "gradual_ramp", "traffic_drop")


def stages(scenario: str, peak: int, rate: float) -> List[Tuple[float, int, float]]:
    """(end fraction of duration, users, spawn rate), as ``scenarios._stages``."""
    low = max(1, round(peak * 0.2))
    if scenario == "gradual_ramp":
        steps = 6
        st = [((i + 1) / (steps + 2), max(1, round(peak * (i + 1) / steps)), rate) for i in range(steps)]
        return st + [(1.0, peak, rate)]
    if scenario == "flash_sale":
        return [(0.25, low, rate), (0.65, peak, max(rate, peak / 5.0)), (1.0, low, rate)]
    if scenario == "traffic_drop":
        return [(0.45, peak, rate), (1.0, max(1, round(peak * 0.1)), rate)]
    return [(1.0, peak, rate)]


def users_curve(stage_list: List[Tuple[float, int, float]], duration_s: float) -> Tuple[np.ndarray, np.ndarray, List[int]]:
    """Users per tick and users started per tick (Locust ramps at the spawn rate; stops are immediate)."""
    ticks = int(round(duration_s / TICK_S))
    users = np.zeros(ticks)
    started = np.zeros(ticks)
    drops: List[int] = []
    cur, prev_target = 0.0, 0
    for k in range(ticks):
        frac = (k * TICK_S) / duration_s
        target, rate = next(((u, r) for end, u, r in stage_list if frac < end), (stage_list[-1][1], stage_list[-1][2]))
        if target < prev_target:
            drops.append(k)
        prev_target = target
        if cur < target:
            add = min(target - cur, rate * TICK_S)
            started[k] = add
            cur += add
        elif cur > target:
            cur = float(target)
        users[k] = cur
    return users, started, drops


def build(app: AppSpec, cal: Dict[str, Any], scenario: str, peak: int = 25, spawn_rate: float = 5.0,
          duration_s: float = 300.0, stage_list: Optional[List[Tuple[float, int, float]]] = None,
          rps_scale: float = 1.0, ratio_noise: Optional[np.ndarray] = None, name: Optional[str] = None) -> Workload:
    """Workload for one scenario; ``cal`` is the ``scenarios`` block of the fitted twin."""
    sc = cal[scenario]
    st = stage_list or stages(scenario, peak, spawn_rate)
    users, started, drops = users_curve(st, duration_s)
    e2e = users * sc["rps_per_user"] * rps_scale
    names = app.names
    ratios = np.array([sc["ratios"].get(s, 0.0) for s in names])
    if ratio_noise is not None:
        ratios = ratios * ratio_noise
    rates = e2e[:, None] * ratios[None, :]
    mix = MIXES[scenario]
    shopper = mix.get("Shopper", 0) / sum(mix.values())
    for k, spec in enumerate(app.services):  # serial (login-like) services: one request per shopper at start
        if spec.serial and sc["ratios"].get(spec.name, 0.0) < 0.02:
            rates[:, k] = started * shopper / TICK_S
    classes = dict(sc.get("classes") or {})
    think = None
    if classes:  # measured cycle per user = think time + mean response time
        base_mean_s = sum(c["share"] * c["base_ms"] for c in classes.values()) / 1000.0
        think = max(0.05, 1.0 / (sc["rps_per_user"] * rps_scale) - base_mean_s)
    return Workload(name=name or f"{scenario}@{peak}", rates=rates, e2e_rps=e2e, users=users, phase_drops=drops,
                    classes=classes, think_s=think)


def evaluation_set(app: AppSpec, cal: Dict[str, Any], peak: int = 25) -> List[Workload]:
    """The six live evaluation scenarios at the live settings (25 users, spawn 5/s, 300 s)."""
    return [build(app, cal, s, peak=peak) for s in EVALUATION_SCENARIOS]


def random_workload(app: AppSpec, cal: Dict[str, Any], rng: np.random.Generator) -> Workload:
    """A training/validation workload around the scenario shapes (see module docstring)."""
    scenario = str(rng.choice(list(MIXES)))
    peak = int(rng.integers(8, 46))
    rate = float(rng.choice([2.0, 5.0, 10.0]))
    duration = float(rng.choice([300.0, 450.0, 600.0]))
    st = stages(scenario, peak, rate)
    # jitter stage boundaries (keep order) and levels
    ends = np.array([e for e, _, _ in st])
    if len(ends) > 1:
        ends[:-1] = np.clip(ends[:-1] + rng.normal(0, 0.06, len(ends) - 1), 0.05, 0.95)
        ends[:-1] = np.sort(ends[:-1])
    st = [(float(e), max(1, int(round(u * rng.uniform(0.8, 1.2)))), r) for e, (_, u, r) in zip(ends, st)]
    # extra event: a spike or a drop in the middle
    ev = rng.random()
    if ev < 0.25:
        a = float(rng.uniform(0.2, 0.7))
        b = min(0.95, a + float(rng.uniform(0.08, 0.25)))
        mult = float(rng.uniform(1.5, 3.0))
        st = _overlay(st, a, b, mult)
    elif ev < 0.4:
        a = float(rng.uniform(0.3, 0.8))
        st = _overlay(st, a, 1.0, float(rng.uniform(0.1, 0.5)))
    noise = np.exp(rng.normal(0, 0.2, len(app.services)))
    return build(app, cal, scenario, peak=peak, spawn_rate=rate, duration_s=duration, stage_list=st,
                 rps_scale=float(rng.uniform(0.85, 1.15)), ratio_noise=noise, name=f"random:{scenario}@{peak}")


def _overlay(st: List[Tuple[float, int, float]], a: float, b: float, mult: float) -> List[Tuple[float, int, float]]:
    """Multiply users by ``mult`` on [a, b) of the duration."""
    cuts = sorted({0.0, a, b, *[e for e, _, _ in st]})
    out = []
    for lo, hi in zip(cuts, cuts[1:]):
        mid = (lo + hi) / 2
        u, r = next(((u, r) for e, u, r in st if mid < e), (st[-1][1], st[-1][2]))
        if a <= mid < b:
            u = max(1, int(round(u * mult)))
            r = max(r, u / 5.0)
        out.append((hi, u, r))
    return out


def random_app(rng: np.random.Generator, n_lo: int = 5, n_hi: int = 18):
    """
    A synthetic application for generalisation (application-agnostic training): a random call DAG from an
    entry service, per-service CPU cost, idle CPU and latency drawn around the shop's ranges, sometimes one
    serial (CPU-heavy, blocking) service. Returns (AppSpec, cal) with the same scenario shapes as the shop.
    """
    from flexascale.simulator.twin import ServiceSpec

    n = int(rng.integers(n_lo, n_hi + 1))
    names = [f"svc-{i}" for i in range(n)]
    services = []
    serial_i = int(rng.integers(1, n)) if rng.random() < 0.35 else -1
    for i, name in enumerate(names):
        if i == serial_i:
            c = float(rng.uniform(0.08, 0.3))
            services.append(ServiceSpec(name, cpu_per_req=c, idle_cores=float(rng.uniform(0.002, 0.008)),
                                        base_latency_ms=1000 * c / 0.5 + 30, serial=True))
        else:
            services.append(ServiceSpec(name, cpu_per_req=float(np.exp(rng.uniform(np.log(0.0006), np.log(0.03)))),
                                        idle_cores=float(rng.uniform(0.001, 0.02)),
                                        base_latency_ms=float(np.exp(rng.uniform(np.log(1.0), np.log(200.0))))))
    edges, fanout = [], {}
    for i in range(1, n):
        parents = rng.choice(i, size=min(i, int(rng.integers(1, 3))), replace=False)
        for p_ in parents:
            edges.append((names[int(p_)], names[i]))
            fanout[f"{names[int(p_)]}->{names[i]}"] = float(rng.uniform(0.1, 1.0))
    # request rate per service relative to the entry: through the strongest path
    ratio = np.zeros(n)
    ratio[0] = float(rng.uniform(1.0, 2.0))
    for i in range(1, n):
        ratio[i] = max(ratio[names.index(u)] * fanout[f"{u}->{v}"] for u, v in edges if v == names[i]) * float(rng.uniform(0.5, 1.5))
    entry_base = services[0].base_latency_ms
    cal = {}
    for sc in MIXES:
        r = {names[i]: float(ratio[i]) for i in range(n)}
        if serial_i >= 0:
            r[names[serial_i]] = 0.0  # spawn-driven, like logins
        cal[sc] = {"rps_per_user": float(rng.uniform(0.5, 1.3)), "ratios": r,
                   "classes": {"all": {"share": 1.0, "base_ms": float(max(5.0, entry_base)), "sigma": 0.6, "services": [names[0]]}}}
    app = AppSpec(name=f"random-{n}", services=services, edges=edges, fanout=fanout, classes={}, entry=names[0])
    return app, cal
