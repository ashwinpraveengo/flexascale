# FlexaScale — E-Commerce Microservices & Intelligent Auto-Scaling Framework

> **Final release (2026-10-26).** Review/presentation quick start: `./scripts/start_review.sh --demo`, then open
> http://127.0.0.1:8090/ (FlexaScale control center; see the top of [RUNNING.md](RUNNING.md)). Project summary, demo runbook and
> viva notes are in `docs/`. Verified status of every component: `reports/final_readiness_report.md`.
>
> **Second laptop (Windows 11, 2026-10-30).** Start and stop with `./fsctl start` / `./fsctl stop` (`fsctl.cmd` in
> PowerShell). Everything was measured again under rules fixed in advance (`docs/POLICY_V9.md`). HPA-tuned was recalibrated
> to a 350% CPU target. A GPU-trained v9 graph policy passed its gate against v7. In a pre-registered 48-run evaluation,
> v9 and Auto are **on par / inconclusive against HPA-tuned** (replica-hours +0.3% and +0.2%). Against default HPA they use
> 7–8% fewer replica-hours, a saving HPA-tuned matches without any model. The graph input showed no measurable
> benefit (`reports/v9/`, readiness report §0.4).
>
> **Results in one paragraph (2026-10-28).** The fair baseline is a *tuned* native HPA: CPU target 250%, 60 s window,
> chosen by a calibration rule fixed in advance. Against it, FlexaScale v7 is **on par**. v7 is a graph policy over the shop's
> call graph, trained in an application twin fitted to live runs. In a pre-registered, clock-controlled replication (48 runs,
> 12 paired blocks), neither the learned policy nor Auto mode differs from HPA-tuned: replica-hours +0.1% (95% CI −0.1 … +0.2),
> Auto's p95 +0.1% (CI −9.3 … +9.5). An earlier 60-run batch had shown Auto beating HPA-tuned on p95 (−21.6%), but that came
> from the test environment. Under the laptop's `balanced` power profile the shop ran faster whenever FlexaScale's live control
> kept the host busy; with the CPU clock controlled, the difference vanished (`docs/V7_REPORT.md`, `docs/POLICY_V7.md`).
> Earlier comparisons with the *default* HPA (e.g. v6's Auto −3.9% replica-hours, `docs/POLICY_V6.md`) ran under the same
> profile and may be affected too. So FlexaScale is a safe, explainable, per-service controller that performs like a
> well-tuned HPA on this shop; it is not shown to beat one.

FlexaScale is an RL-based intelligent autoscaling framework for distributed microservices on Kubernetes. This repository houses the realistic, cloud-native **E-Commerce Shopping Application** workload alongside the FlexaScale reinforcement learning research framework.

---

## 🛍️ Cloud-Native E-Commerce Application Architecture

The shopping platform is a production-grade microservices application featuring a modern React frontend and sixteen independent backend microservices communicating via asynchronous HTTP with PostgreSQL persistence and Prometheus observability.

### Microservice Ecosystem

The diagram shows the core checkout path. The nine services added for the 16-service shop (Helm chart 1.1.0) are listed after the table.

```
                                 ┌─────────────────────────┐
                                 │   Shopping Frontend     │
                                 │ (React 18 + TS + Vite)  │
                                 └────────────┬────────────┘
                                              │ HTTP / JSON
                                              ▼
                                 ┌─────────────────────────┐
                                 │       API Gateway       │
                                 │     (Port 8000/TCP)     │
                                 └──────┬───┬───┬───┬──────┘
                                        │   │   │   │
               ┌────────────────────────┘   │   │   └───────────────────────┐
               │                            │   │                           │
               ▼                            ▼   ▼                           ▼
    ┌──────────────────────┐  ┌──────────────────┐  ┌───────────────────────────────┐
    │     User & Auth      │  │ Product Catalog  │  │         Shopping Cart         │
    │   (Port 8001/TCP)    │  │ (Port 8002/TCP)  │  │        (Port 8003/TCP)        │
    │  JWT + Bcrypt Auth   │  │ Category & Items │  │      Authoritative Pricing    │
    └──────────────────────┘  └────────┬─────────┘  └───────────────┬───────────────┘
                                       │                            │
                                       │ validates catalog info     │ validates cart
                                       ▼                            ▼
                                  ┌───────────────────────────────────────┐
                                  │           Order Management            │
                                  │            (Port 8004/TCP)            │
                                  │        2-Phase Saga Coordinator       │
                                  └───────────┬───────────────┬───────────┘
                                              │               │
                     reserves & confirms/     │               │ charges simulated
                     releases inventory       │               │ payment
                                              ▼               ▼
                                  ┌──────────────────┐  ┌──────────────────┐
                                  │    Inventory     │  │ Payment Service  │
                                  │ (Port 8005/TCP)  │  │ (Port 8006/TCP)  │
                                  │  Pessimistic Row │  │   Simulated TXNs │
                                  │   Locking (FOR   │  │    Idempotency   │
                                  │     UPDATE)      │  │    Delays/Errors │
                                  └──────────────────┘  └──────────────────┘
                                              │
                                              ▼
                                  ┌───────────────────────────┐
                                  │     PostgreSQL Engine     │
                                  │ Multi-Schema Persistence  │
                                  └───────────────────────────┘
```

### Microservice Responsibilities

| Service | Port | Description & Responsibilities | Database Schema |
|---|---|---|---|
| **`shopping-frontend`** | 80 / 5173 | Modern responsive React + TypeScript UI built with Tailwind CSS. Product catalog browsing, full-text search, category filter, dynamic cart, two-phase checkout modal, order history, profile view, and admin catalog & inventory managers. Communicates strictly with API Gateway. | N/A (Client) |
| **`api-gateway`** | 8000 | Unified public entrypoint reverse proxy. Path routing, aggregated health diagnostic endpoint (`/api/system/status`), CORS, request forwarding, bounded timeouts, and Prometheus latency instrumentation. | N/A (Stateless Proxy) |
| **`user-service`** | 8001 | User registration, authentication, bcrypt password hashing, PyJWT token issuance and verification, user profile CRUD, and role-based access control (`customer` vs `admin`). | `users` |
| **`catalog-service`** | 8002 | Product and category catalog, full-text search, pagination, price range filtering, sorting (price, name, newest), and administrative product CRUD operations. | `catalog` |
| **`cart-service`** | 8003 | User shopping carts, add/remove/update items, authoritative item price calculation through Catalog Service, and atomic cart clearing upon checkout. | `cart` |
| **`order-service`** | 8004 | Checkout orchestration via a **2-Phase Distributed Saga**: validates items with Catalog, reserves stock with Inventory, triggers payment with Payment Service, confirms order and inventory on success, or executes compensating release transactions on decline. | `orders` |
| **`inventory-service`** | 8005 | Stock tracking with pessimistic row-level locking (`SELECT ... FOR UPDATE`), atomic inventory reservation, stock release rollback, and administrative stock updates. Prevents lost updates and overselling. | `inventory` |
| **`payment-service`** | 8006 | Simulated payment engine with unique transaction IDs (`txn_*`), configurable card failure simulation, artificial delay injection (`X-Payment-Delay-Ms`), and idempotency key safety. **Never stores real card credentials.** | `payments` |
| **`search-service`** | 8007 | Ranked full-text product search (BM25 over name and description) with live prices: gateway → search → pricing → promotion. | N/A |
| **`recommendation-service`** | 8008 | "Customers also viewed": content similarity over the catalogue, weighted by review ratings. | N/A |
| **`review-service`** | 8009 | Product reviews and rating summaries, read by the product page and by recommendations. | `review` |
| **`pricing-service`** | 8010 | Final prices (promotions, tax) for a list of items. Used by search, cart and checkout. | N/A |
| **`promotion-service`** | 8011 | Evaluates active promotion rules per product. CPU cost grows with the number of products requested. | N/A |
| **`shipping-service`** | 8012 | Delivery quotes. A required checkout step. | N/A |
| **`fraud-service`** | 8013 | Risk-scores a checkout before payment (fixed logistic model). A required checkout step. | N/A |
| **`notification-service`** | 8014 | Order confirmation messages after a confirmed checkout. Best effort: a failure never fails the order. Nothing is actually sent. | N/A |
| **`wishlist-service`** | 8015 | Saved products per user, enriched with live catalogue data. | `wishlist` |

---

## 🔄 Two-Phase Checkout Saga & Inter-Service Dependencies

The checkout flow coordinates state changes across four independent microservices with automatic compensation rollback:

```mermaid
sequenceDiagram
    autonumber
    actor User as Customer (Browser)
    participant GW as API Gateway
    participant Ord as Order Service
    participant Cat as Catalog Service
    participant Inv as Inventory Service
    participant Pay as Payment Service
    participant Cart as Cart Service

    User->>GW: POST /api/orders/checkout
    GW->>Ord: Forward checkout request
    Ord->>Cat: Fetch authoritative product prices
    Cat-->>Ord: Product details & prices
    Ord->>Inv: POST /api/inventory/reserve (items, order_id)
    alt Insufficient stock
        Inv-->>Ord: 400 Bad Request (Stock depleted)
        Ord-->>GW: 400 Insufficient Stock
        GW-->>User: Display error notification
    else Stock reserved successfully
        Inv-->>Ord: 200 OK (Reservation token)
        Ord->>Pay: POST /api/payments/process (amount, idemp_key)
        alt Payment Declined / Error
            Pay-->>Ord: 402 Payment Declined / Error
            Ord->>Inv: POST /api/inventory/release (rollback reservation)
            Inv-->>Ord: 200 OK (Stock restored)
            Ord-->>GW: 400 Payment Failed (Failure recorded)
            GW-->>User: Display decline message
        else Payment Succeeded
            Pay-->>Ord: 200 OK (Transaction ID)
            Ord->>Inv: POST /api/inventory/confirm (finalize stock deduction)
            Inv-->>Ord: 200 OK (Stock confirmed)
            Ord->>Cart: DELETE /api/cart/{user_id}/items (clear cart)
            Cart-->>Ord: 204 No Content
            Ord-->>GW: 201 Created (Confirmed Order)
            GW-->>User: Display Order Confirmation
        end
    end
```

---

## 🗄️ Database & Schema Isolation

The application utilizes a single PostgreSQL instance with **strict per-service schema isolation**:
- `users`: `users.users`
- `catalog`: `catalog.categories`, `catalog.products`
- `cart`: `cart.carts`, `cart.cart_items`
- `inventory`: `inventory.inventory`, `inventory.reservations`
- `orders`: `orders.orders`, `orders.order_items`
- `payments`: `payments.transactions`

DDL initialization is defined in `apps/database/init.sql` and idempotent initial data population is provided via `apps/database/seed.py`.

### Default Test Credentials

| Role | Email | Password | Purpose |
|---|---|---|---|
| **Admin** | `admin@flexascale.io` | `AdminPass123!` | Managing product catalog & stock adjustments |
| **Customer** | `demo@flexascale.io` | `CustomerPass123!` | Standard shopping & checkout journeys |
| **Load Tester** | `tester@flexascale.io` | `TesterPass123!` | Headless load testing & benchmarking |

---

## 🚀 Running Locally with Docker Compose

To run the application locally without Kubernetes:

```bash
# 1. Copy sample environment configuration
cp .env.example .env

# 2. Build and start the 16 services, the frontend and PostgreSQL
docker compose up --build -d

# 3. Seed test users, categories, and products
python apps/database/seed.py

# 4. Access application:
# Frontend:     http://localhost:3000
# API Gateway:  http://localhost:8000
# Aggregated:   http://localhost:8000/api/system/status
```

To stop and remove containers:
```bash
docker compose down -v
```

---

## ☸️ Kubernetes Deployment via Helm

The primary production deployment mechanism is the parameterized Helm chart located at `charts/shopping-app/`.

### 1. Verify Prerequisites

Ensure your Minikube cluster is active with the required addons:

```bash
minikube start -p flexascale --cpus=4 --memory=9216 --kubernetes-version=v1.31.0
minikube addons enable metrics-server -p flexascale
minikube addons enable ingress -p flexascale
```

### 2. Build & Load Container Images

```bash
# Build every shop image (16 services + frontend) with the tag the Helm chart expects
# (charts/shopping-app/values.yaml) and load it into Minikube
./scripts/build_shop_images.sh
minikube -p flexascale image load postgres:16-alpine
```

### 3. Deploy Chart

```bash
# Lint the chart
helm lint charts/shopping-app

# Render templates to verify YAML output
helm template shopping-app charts/shopping-app

# Install or upgrade chart into flexascale-apps namespace
helm upgrade --install shopping-app charts/shopping-app -n flexascale-apps

# Native HPAs for all 16 services (CPU 70% of request, 1-10 replicas): the baseline FlexaScale is compared with
kubectl apply -f deploy/kubernetes/hpa.yaml

# Verify all pods are Ready
kubectl get pods -n flexascale-apps -w
```

### 4. Seed Database in Cluster

```bash
# Port-forward PostgreSQL and run seeder
kubectl port-forward svc/postgres -n flexascale-apps 54322:5432 &
PF_PID=$!
sleep 2
DATABASE_URL="postgresql+psycopg://postgres:postgresPassword123!@127.0.0.1:54322/ecommerce" python apps/database/seed.py
kill $PF_PID
```

### 5. Access the Application

- **Direct Ingress IP**: `http://$(minikube -p flexascale ip)` (e.g., `http://192.168.49.2/`)
- **API Status**: `http://192.168.49.2/api/system/status`
- **Prometheus Metrics**: `http://192.168.49.2/metrics`
- **Port-Forwarding (Optional)**:
  ```bash
  kubectl port-forward svc/api-gateway -n flexascale-apps 8000:8000 &
  kubectl port-forward svc/shopping-frontend -n flexascale-apps 8080:80 &
  ```

---

## 📈 Monitoring & Observability

Every microservice exposes standardized low-cardinality Prometheus metrics at `/metrics`:
- `http_requests_total{service="...", method="...", endpoint="...", status="..."}`: Request counter.
- `http_request_duration_seconds`: Histogram of request latencies.
- `http_requests_in_flight`: Current concurrent requests.
- `gateway_forward_total{target_service="...", status="..."}`: API Gateway downstream routing counter.

### Prometheus & Grafana Integration

- **ServiceMonitor**: Configured in `charts/shopping-app/templates/servicemonitor.yaml` for Prometheus Operator.
- **Scrape Config**: Manual pod scrape annotations (`prometheus.io/scrape: "true"`) in `observability/prometheus/scrape-configs.yaml`.
- **Grafana Dashboard**: Pre-built JSON dashboard in `observability/grafana/dashboard.json` covering RPS, P95 latency, 4xx/5xx error rates, and container CPU/memory usage.

---

## ⚡ Locust Load Testing

The `load-testing/` directory contains realistic shopping traffic scenarios:

| User Class | Description | Characteristics |
|---|---|---|
| **`BrowsingUser`** | Browses product catalog, searches items, views categories | 1-3s think time, GET operations |
| **`ShoppingCustomerUser`** | End-to-end journey: login, cart modification, checkout | Realistic multi-step workflow |
| **`FlashSaleUser`** | Heavy contention on popular products | Tests atomic row locks & stock limits |
| **`FailedCheckoutUser`** | Checkout with simulated payment decline | Tests 2-phase rollback & error handling |
| **`HighLatencyPaymentUser`** | Simulates 300ms+ payment delays | Tests downstream queuing & timeouts |

### Running Load Tests

```bash
# Run headless load test against the cluster ingress
locust -f load-testing/locustfile.py BrowsingUser --headless -u 20 -r 2 --run-time 60s --host http://192.168.49.2

# Run full customer journey test
locust -f load-testing/locustfile.py ShoppingCustomerUser --headless -u 10 -r 1 --run-time 60s --host http://192.168.49.2

# Run stepped surge traffic pattern
USE_STEP_SHAPE=true locust -f load-testing/locustfile.py --headless --host http://192.168.49.2
```

---

## 🧪 Automated Testing Suite

Execute unit and integration tests across the shopping microservices:

```bash
# Run all tests (shopping application + FlexaScale framework)
pytest tests/ -v

# Run shopping application test suite only
pytest tests/shopping-app/ -v

# Run live Kubernetes cluster end-to-end verification
API_URL="http://$(minikube -p flexascale ip)" python scripts/test_live_cluster.py
```

---

## 🛡️ Scope Boundaries & Framework Preservation

The FlexaScale RL framework (`src/flexascale/`), Gymnasium simulator (`FlexaScaleEnv`), GNN dependency encoder (`GNNExtractor`), PPO training pipeline, safety controller, and Alibaba cluster trace datasets remain completely intact and functional. The new shopping microservices platform serves as the realistic distributed workload for future intelligent autoscaling evaluation.
