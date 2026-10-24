"""Workload for the synthetic bookstore. Uses the same FLEXASCALE_* scenario variables as load-testing/scenarios.py."""
import os
import sys

from locust import HttpUser, between, task

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "load-testing"))
from scenarios import ScenarioShape  # noqa: E402,F401  (reuses the scenario load shapes)


class Reader(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(5)
    def home(self):
        self.client.get("/", name="GET / (home)")

    @task(3)
    def search(self):
        self.client.get("/api/search", name="GET /api/search")

    @task(2)
    def cart(self):
        self.client.get("/api/cart", name="GET /api/cart")
