"""
FlexaScale Locust Load Generation Suite.

Implements realistic microservice workload profiles:
1. LunchSpikeUser: High volume checkout and order processing mimicking peak lunch traffic.
2. QuietNightUser: Low baseline background traffic with intermittent browse requests.
3. BurstUser: High-concurrency sudden step spike testing autoscaler reaction lag.
4. FlexaScaleUser: Standard multi-endpoint user journey.
"""

from locust import HttpUser, between, task


class FlexaScaleUser(HttpUser):
    """Standard user journey through the microservice gateway."""
    wait_time = between(1.0, 2.5)

    @task(3)
    def index_page(self):
        self.client.get("/", name="GET /")

    @task(2)
    def checkout_flow(self):
        self.client.post("/api/checkout", name="POST /api/checkout")


class LunchSpikeUser(HttpUser):
    """Intensive e-commerce order stream during peak hours."""
    wait_time = between(0.2, 0.8)

    @task(4)
    def fast_checkout(self):
        self.client.post("/api/checkout", name="POST /api/checkout [LunchSpike]")

    @task(1)
    def browse(self):
        self.client.get("/", name="GET / [LunchSpike]")


class QuietNightUser(HttpUser):
    """Low background idle traffic during off-peak night hours."""
    wait_time = between(3.0, 6.0)

    @task(4)
    def slow_browse(self):
        self.client.get("/", name="GET / [QuietNight]")

    @task(1)
    def occasional_order(self):
        self.client.post("/api/checkout", name="POST /api/checkout [QuietNight]")


class BurstUser(HttpUser):
    """High concurrency instantaneous burst to test autoscaler scale-up delay."""
    wait_time = between(0.05, 0.2)

    @task
    def burst_request(self):
        self.client.post("/api/checkout", name="POST /api/checkout [Burst]")
