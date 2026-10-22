"""
FlexaScale E-Commerce Microservices Load Testing Suite.
Simulates realistic distributed shopping traffic across the 7 backend microservices:
1. BrowsingUser: Catalog browsing, full-text search, product details, category exploration.
2. ShoppingCustomerUser: Full customer journey (login, add to cart, update qty, checkout, order history).
3. FlashSaleUser: High-concurrency contention on top products to test atomic inventory locking.
4. FailedCheckoutUser: Evaluates two-phase saga rollback and error propagation.
5. HighLatencyPaymentUser: Stresses timeouts and downstream queuing by introducing simulated processing delays.
6. StepSurgeShape: Stepped traffic load shape (ramp-up, spike, and cool-down).
"""

import os
import random
import uuid
from locust import HttpUser, task, between, events, LoadTestShape

TARGET_BASE_URL = os.getenv("TARGET_URL", "http://localhost:8000")

# Test user credentials seeded by apps/database/seed.py
TEST_USERS = [
    {"email": "demo@flexascale.io", "password": "CustomerPass123!", "user_id": 2},
    {"email": "tester@flexascale.io", "password": "TesterPass123!", "user_id": 3},
]

SEARCH_QUERIES = ["headphones", "keyboard", "monitor", "coffee", "wool", "denim", "book", "dumbbell"]

class BrowsingUser(HttpUser):
    """Simulates passive shoppers who explore the store, search, and view product details."""
    wait_time = between(1.0, 3.0)

    @task(5)
    def browse_catalog(self):
        page = random.randint(1, 3)
        self.client.get(f"/api/products?page={page}&limit=10", name="GET /api/products")

    @task(3)
    def search_products(self):
        query = random.choice(SEARCH_QUERIES)
        self.client.get(f"/api/products?q={query}", name="GET /api/products?q=[search]")

    @task(4)
    def view_product_detail(self):
        product_id = random.randint(1, 14)
        self.client.get(f"/api/products/{product_id}", name="GET /api/products/{id}")

    @task(2)
    def view_categories(self):
        self.client.get("/api/categories", name="GET /api/categories")


class ShoppingCustomerUser(HttpUser):
    """Simulates authenticated shoppers adding items to cart, modifying quantities, and completing checkout."""
    wait_time = between(1.5, 4.0)

    def on_start(self):
        self.user_data = random.choice(TEST_USERS)
        self.token = None
        self.user_id = self.user_data["user_id"]
        # Authenticate
        resp = self.client.post("/api/users/login", json={
            "email": self.user_data["email"],
            "password": self.user_data["password"]
        }, name="POST /api/users/login")
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("access_token")
            self.user_id = data.get("user", {}).get("id", self.user_id)

    def get_headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @task(4)
    def add_to_cart_and_view(self):
        prod_id = random.randint(1, 14)
        qty = random.randint(1, 2)
        self.client.post(
            f"/api/cart/{self.user_id}/items",
            json={"product_id": prod_id, "quantity": qty},
            headers=self.get_headers(),
            name="POST /api/cart/{user_id}/items"
        )
        self.client.get(
            f"/api/cart/{self.user_id}",
            headers=self.get_headers(),
            name="GET /api/cart/{user_id}"
        )

    @task(2)
    def checkout_cart(self):
        idemp = f"locust_{uuid.uuid4().hex[:12]}"
        # Ensure cart has an item
        prod_id = random.randint(1, 14)
        self.client.post(
            f"/api/cart/{self.user_id}/items",
            json={"product_id": prod_id, "quantity": 1},
            headers=self.get_headers(),
            name="POST /api/cart/{user_id}/items"
        )

        resp = self.client.post(
            "/api/orders/checkout",
            json={
                "user_id": self.user_id,
                "shipping_address": "123 Performance Lane, Minikube Cluster",
                "card_number": "4000000000000001",
                "payment_method": "simulated_card",
                "simulate_failure": False,
                "idempotency_key": idemp
            },
            headers=self.get_headers(),
            name="POST /api/orders/checkout [Success]"
        )

    @task(1)
    def view_orders(self):
        self.client.get(
            f"/api/orders/user/{self.user_id}",
            headers=self.get_headers(),
            name="GET /api/orders/user/{user_id}"
        )


class FlashSaleUser(HttpUser):
    """Simulates high-velocity traffic on high-demand flash sale items testing atomic row locks."""
    wait_time = between(0.1, 0.5)

    @task
    def rapid_order_flash_item(self):
        # Focus on top 2 products (headphones & keyboard)
        target_prod = random.choice([1, 2])
        idemp = f"flash_{uuid.uuid4().hex[:12]}"
        with self.client.post(
            "/api/orders/checkout",
            json={
                "user_id": random.randint(2, 3),
                "items": [{"product_id": target_prod, "quantity": 1}],
                "shipping_address": "Flash Sale Blitz, Cluster 1",
                "card_number": "4000000000000001",
                "idempotency_key": idemp
            },
            catch_response=True,
            name="POST /api/orders/checkout [FlashSale Contention]"
        ) as resp:
            if resp.status_code in (200, 201):
                resp.success()
            elif resp.status_code == 400:
                resp.success()


class FailedCheckoutUser(HttpUser):
    """Tests failure handling, compensation rollback, and error status propagation."""
    wait_time = between(1.0, 3.0)

    @task
    def simulated_declined_payment(self):
        idemp = f"fail_{uuid.uuid4().hex[:12]}"
        with self.client.post(
            "/api/orders/checkout",
            json={
                "user_id": 2,
                "items": [{"product_id": random.randint(1, 10), "quantity": 1}],
                "shipping_address": "Test Decline Way, Sandbox",
                "card_number": "4000000000000002",  # Always triggers payment decline
                "idempotency_key": idemp
            },
            catch_response=True,
            name="POST /api/orders/checkout [Simulated Decline]"
        ) as response:
            if response.status_code == 402:
                response.success()  # Expected failure behavior
            elif response.status_code == 400:
                response.success()  # Handled error


class HighLatencyPaymentUser(HttpUser):
    """Stresses inter-service timeout handling and concurrent in-flight connection limits."""
    wait_time = between(1.0, 2.5)

    @task
    def delayed_checkout(self):
        idemp = f"delay_{uuid.uuid4().hex[:12]}"
        headers = {"X-Payment-Delay-Ms": "300"}
        self.client.post(
            "/api/orders/checkout",
            json={
                "user_id": 3,
                "items": [{"product_id": random.randint(1, 10), "quantity": 1}],
                "shipping_address": "High Latency Blvd, Stress Test",
                "card_number": "4000000000000001",
                "idempotency_key": idemp
            },
            headers=headers,
            name="POST /api/orders/checkout [High Latency 300ms]"
        )


if os.getenv("USE_STEP_SHAPE", "false").lower() in ("true", "1", "yes"):
    class StepSurgeShape(LoadTestShape):
        """
        Simulates a stepped traffic wave:
        0 - 60s: Warmup (20 users)
        60s - 180s: Sudden lunchtime surge (150 users)
        300s - 420s: Cool-down recovery (30 users)
        """
        stages = [
            {"duration": 60, "users": 20, "spawn_rate": 5},
            {"duration": 180, "users": 150, "spawn_rate": 20},
            {"duration": 300, "users": 300, "spawn_rate": 50},
            {"duration": 420, "users": 30, "spawn_rate": 20},
        ]

        def tick(self):
            run_time = self.get_run_time()
            for stage in self.stages:
                if run_time < stage["duration"]:
                    return (stage["users"], stage["spawn_rate"])
            return None

# Backward-compatibility aliases for legacy scripts
class LunchSpikeUser(ShoppingCustomerUser):
    pass

class QuietNightUser(BrowsingUser):
    pass

class BurstUser(FlashSaleUser):
    pass

class FlexaScaleUser(ShoppingCustomerUser):
    pass

