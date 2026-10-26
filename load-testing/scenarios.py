"""
FlexaScale Live Autoscaling Lab: reproducible Locust workload scenarios.

Selected with environment variables (set by the lab backend):

    FLEXASCALE_SCENARIO     steady_browsing | gradual_ramp | flash_sale |
                            checkout_heavy | traffic_drop | payment_degradation |
                            calibration_steady (HPA-tuned calibration only)
    FLEXASCALE_USERS        peak concurrent users            (default 40)
    FLEXASCALE_SPAWN_RATE   users started per second         (default 5)
    FLEXASCALE_DURATION     total scenario length in seconds (default 300)

The user behaviours are the existing journeys in ``locustfile.py``; this file
only mixes them and shapes the user count over time. Phase changes are
printed as ``FLEXASCALE_PHASE <name> <users>`` so the lab timeline can show
when traffic actually changed.

Run standalone:
    FLEXASCALE_SCENARIO=flash_sale .venv/bin/locust -f load-testing/scenarios.py \
        --headless --host http://192.168.49.2
"""

from __future__ import annotations

import os
import sys

from locust import LoadTestShape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import locustfile as journeys  # noqa: E402

SCENARIO = os.getenv("FLEXASCALE_SCENARIO", "steady_browsing")
PEAK_USERS = max(1, int(os.getenv("FLEXASCALE_USERS", "40")))
SPAWN_RATE = max(0.1, float(os.getenv("FLEXASCALE_SPAWN_RATE", "5")))
DURATION = max(30, int(os.getenv("FLEXASCALE_DURATION", "300")))

# Relative user-class weights per scenario.
MIXES = {
    "steady_browsing": {"Browsing": 8, "Shopper": 2},
    "gradual_ramp": {"Browsing": 6, "Shopper": 4},
    "flash_sale": {"Browsing": 4, "Shopper": 2, "FlashSale": 4},
    "checkout_heavy": {"Browsing": 2, "Shopper": 7, "FlashSale": 1},
    "traffic_drop": {"Browsing": 6, "Shopper": 4},
    "payment_degradation": {"Browsing": 3, "Shopper": 3, "SlowPayment": 3, "DeclinedPayment": 1},
    # HPA-tuned calibration only (docs/POLICY_V7.md §2.1); not one of the evaluation scenarios.
    "calibration_steady": {"Browsing": 5, "Shopper": 5},
}
if SCENARIO not in MIXES:
    raise SystemExit(f"Unknown FLEXASCALE_SCENARIO '{SCENARIO}'. Choose from {sorted(MIXES)}")
MIX = MIXES[SCENARIO]

if "Browsing" in MIX:
    class Browsing(journeys.BrowsingUser):
        weight = MIX["Browsing"]

if "Shopper" in MIX:
    class Shopper(journeys.ShoppingCustomerUser):
        weight = MIX["Shopper"]

if "FlashSale" in MIX:
    class FlashSale(journeys.FlashSaleUser):
        weight = MIX["FlashSale"]

if "SlowPayment" in MIX:
    class SlowPayment(journeys.HighLatencyPaymentUser):
        weight = MIX["SlowPayment"]

if "DeclinedPayment" in MIX:
    class DeclinedPayment(journeys.FailedCheckoutUser):
        weight = MIX["DeclinedPayment"]


def _stages() -> list[tuple[float, int, float, str]]:
    """(end_fraction_of_duration, users, spawn_rate, phase_name)."""
    p, r = PEAK_USERS, SPAWN_RATE
    low = max(1, round(p * 0.2))
    if SCENARIO == "gradual_ramp":
        steps = 6
        stages = [((i + 1) / (steps + 2), max(1, round(p * (i + 1) / steps)), r, f"ramp_{i + 1}") for i in range(steps)]
        return stages + [(1.0, p, r, "plateau")]
    if SCENARIO == "flash_sale":
        return [(0.25, low, r, "baseline"), (0.65, p, max(r, p / 5.0), "flash_sale_spike"), (1.0, low, r, "after_sale")]
    if SCENARIO == "traffic_drop":
        return [(0.45, p, r, "peak"), (1.0, max(1, round(p * 0.1)), r, "drop")]
    return [(1.0, p, r, "steady")]


class ScenarioShape(LoadTestShape):
    stages = _stages()
    _announced = None

    def tick(self):
        t = self.get_run_time()
        if t >= DURATION:
            return None
        frac = t / DURATION
        for end, users, rate, name in self.stages:
            if frac < end:
                if self._announced != name:
                    print(f"FLEXASCALE_PHASE {name} {users}", flush=True)
                    self._announced = name
                return users, rate
        return None
