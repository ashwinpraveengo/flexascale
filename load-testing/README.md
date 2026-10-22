# FlexaScale E-Commerce Load Testing Suite

This directory contains realistic Locust load-generation workloads for evaluating the 7 backend microservices, testing concurrency and locking behavior, measuring SLA latency distributions, and observing Prometheus metrics.

---

## 1. Workload Profiles

| User Class | Focus / Behavior | Target Endpoints |
| :--- | :--- | :--- |
| `BrowsingUser` | Catalog exploration, search queries, product detail views | `/api/products`, `/api/products?q=...`, `/api/categories` |
| `ShoppingCustomerUser` | End-to-end shopping flow: login, add-to-cart, cart views, checkout | `/api/users/login`, `/api/cart/*`, `/api/orders/checkout`, `/api/orders/*` |
| `FlashSaleUser` | High-frequency checkout contention on top items testing atomic locks | `/api/orders/checkout` (High Concurrency) |
| `FailedCheckoutUser` | Payment decline & error simulation testing 2-phase saga rollback | `/api/orders/checkout` with failure cards |
| `HighLatencyPaymentUser`| Stresses timeouts and downstream queueing via `X-Payment-Delay-Ms` | `/api/orders/checkout` with artificial delays |
| `StepSurgeShape` | Automatic step load shape: 20 → 150 → 300 → 30 users | Full application stack |

---

## 2. Prerequisites

Locust is installed in the project's virtual environment:

```bash
# Verify locust installation
./.venv/bin/locust --version
```

---

## 3. Running Load Tests

### A. Interactive Web UI Mode
Launch Locust with its interactive web interface:

```bash
./.venv/bin/locust -f load-testing/locustfile.py --host http://localhost:8000
```
Open [http://localhost:8089](http://localhost:8089) in your browser. Configure number of users, spawn rate, and select user classes.

### B. Headless Automated Execution
Run an automated 60-second benchmark targeting the API Gateway:

```bash
# Standard multi-endpoint shopping journey with 50 concurrent users
./.venv/bin/locust -f load-testing/locustfile.py \
  --host http://localhost:8000 \
  --headless \
  --users 50 \
  --spawn-rate 10 \
  --run-time 1m \
  ShoppingCustomerUser
```

### C. Flash Sale Contention Test
Test atomic database inventory locking under high concurrency:

```bash
./.venv/bin/locust -f load-testing/locustfile.py \
  --host http://localhost:8000 \
  --headless \
  --users 100 \
  --spawn-rate 25 \
  --run-time 45s \
  FlashSaleUser
```

### D. Stepped Wave Traffic Surge
Simulate a realistic traffic spike using the built-in `StepSurgeShape`:

```bash
./.venv/bin/locust -f load-testing/locustfile.py \
  --host http://localhost:8000 \
  --headless
```

---

## 4. Monitoring in Prometheus & Grafana

During and after running load tests, observe the real-time impact:

1. **Prometheus Queries**:
   - Total HTTP Request Rate (RPS):
     ```promql
     sum by (service) (rate(http_requests_total[1m]))
     ```
   - 95th Percentile Latency:
     ```promql
     histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket[1m]))) * 1000
     ```
   - HTTP Error Rates:
     ```promql
     sum by (service, status) (rate(http_requests_total{status=~"[45].."}[1m]))
     ```
   - Active Concurrent In-Flight Requests:
     ```promql
     sum by (service) (http_requests_in_flight)
     ```

2. **Grafana Dashboard**:
   - Navigate to the `FlexaScale - E-Commerce Microservices Observability` dashboard in Grafana (`http://localhost:3000` or Kubernetes Ingress).
   - Watch live RPS, latency spikes, error handling, and container CPU/memory graphs update every 5 seconds.
