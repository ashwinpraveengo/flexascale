# FlexaScale — End-to-End Execution & Verification Guide

This guide provides the complete, authoritative run instructions to set up, deploy, simulate, monitor, and train the FlexaScale RL-based intelligent auto-scaling framework from a fresh terminal.

---

## Quick Start for Project Reviews and Presentations

Use this when the cluster and application are already installed. A new laptop needs the one-time setup below first; the full installation is in sections [A–G](#a-repository--python-setup).

**1. Start everything** (≈30 s if Minikube is running, 2–4 min if it has to start):

| Windows (PowerShell or cmd, repository root) | Linux / macOS / Git Bash |
| :--- | :--- |
| `.\fsctl start` | `./fsctl start` |

Wait for `READY`. It checks the tools, starts the existing Minikube profile if needed (never creates one), waits for every pod, opens the shop's ingress (on Windows and macOS through a managed `minikube tunnel`, because the Minikube IP is not reachable from the host there), port-forwards Prometheus and Grafana, restores native-HPA ownership if anything was left frozen, and starts the control center. It never rebuilds, reinstalls, retrains or downloads anything, and it reuses processes that are already healthy. `fsctl start --check` runs the preflight only; `fsctl start --demo` also prints the demo sequence. (`./scripts/start_review.sh` is the same command.)

**2. Open the URLs printed by the command:**

| What | URL |
| :--- | :--- |
| FlexaScale control center | http://127.0.0.1:8090/ |
| Shopping application | http://127.0.0.1/ on Windows/macOS (tunnel), `http://$(minikube ip -p flexascale)/` on Linux. Login `demo@flexascale.io` / `CustomerPass123!` |
| Prometheus / Grafana | http://localhost:9090/ and http://localhost:3000/ |

**3. Status at any time:** `fsctl status` (read-only).

**4. Live experiment (Live lab page):**
1. Autoscaling mode: **Native HPA**, **FlexaScale** or **Auto** (plus the two HPA references: 60 s scale-down, and the calibrated *HPA-tuned*). FlexaScale and Auto take the controller Lease and freeze a service's HPA before scaling it; Auto decides per service and step who scales it and logs the rule and reason. With Native HPA, *shadow mode* logs what FlexaScale would do without changing anything.
2. Scenario: steady browsing, gradual ramp-up, flash-sale spike, checkout-heavy, traffic drop, or payment latency & failures; 25 peak users and 300 s for comparable results. *Comparable start* resets the application data and every service to its minimum first.
3. **Start**, then watch the **Live Autoscaling Timeline**: desired and ready replicas, the FlexaScale proposal (dashed, a filled dot = a scale request actually sent), HPA's proposal (dotted; its own `status.desiredReplicas` while it owns a service, the rule estimate while FlexaScale does), observed scale-ups/downs, controller ownership, Locust traffic, p50/p95 latency with the SLA line and hatched violation periods, CPU/memory on demand, and an event lane (workload phases, scale requests, Auto handoffs, safety interventions). Pick one service to see its own requests/s and latency from Prometheus. *Pause* freezes the view while data keeps arriving; a finished run becomes a **REPLAY** with play/speed/scrub controls. Gaps mean no telemetry was recorded; nothing is interpolated.
4. **Stop** ends Locust and the operator and always restores HPA ownership (verified).

**5. Compare and inspect:** **Comparison** = the paired benchmark with 95% intervals and the pre-registered verdict rule; **Experiments** = every saved run with its configuration, validity checks (complete, settled start, cleanup verified, AC power) and a replay of its timeline; pick a baseline there and *Compare with baseline*. Raw data: `reports/experiments/<run>/run.json`, `telemetry.csv`, `decisions.jsonl`, Locust CSVs.

**6. Stop safely:** `fsctl stop` (or `./scripts/stop_review.sh`). It stops only the processes the launcher started (never by port), asks a running experiment to stop first, restores every HPA's original bounds and verifies that no FlexaScale Lease is held. Minikube, deployments, Helm releases, volumes and database data are left untouched. `fsctl stop --force-release-lease` clears a Lease left by a dead controller.

**One-time setup on a new laptop** (images are local, not in a registry):

```bash
python -m venv .venv            # Windows: .venv\Scripts\pip ...; Linux: .venv/bin/pip ...
.venv/Scripts/pip install -r requirements.txt bcrypt sqlalchemy "psycopg[binary]" pyjwt httpx psutil && .venv/Scripts/pip install -e .
cd dashboard && npm ci && npm run build && cd ..          # builds the control center into src/flexascale/lab/static
minikube start -p flexascale --driver=docker --cpus=4 --memory=6g
./scripts/deploy_monitoring.sh                             # Windows: scripts\deploy_monitoring.ps1 (kube-prometheus-stack)
./scripts/build_shop_images.sh                             # builds all 17 images inside Minikube's Docker daemon (Git Bash on Windows)
helm upgrade --install shopping-app charts/shopping-app -n flexascale-apps && kubectl apply -f deploy/kubernetes/hpa.yaml
kubectl -n flexascale-apps port-forward svc/postgres 54322:5432 &   # then seed once:
DATABASE_URL="postgresql+psycopg://postgres:postgresPassword123!@127.0.0.1:54322/ecommerce" .venv/Scripts/python apps/database/seed.py
```

**Troubleshooting**

| Symptom | Fix |
| :--- | :--- |
| Docker not running | Start Docker Desktop (Windows/macOS) or `sudo systemctl start docker`, then `fsctl start`. |
| Shop unreachable on Windows/macOS | `fsctl start` runs `minikube tunnel` as a managed process; check `.runtime/logs/tunnel.log`. Port 80 must be free. |
| Pods not ready right after a cluster restart | Wait 1–2 min (PostgreSQL first). `kubectl get pods -A`. |
| Dashboard shows CPU "missing" for every service | Prometheus port-forward down (`fsctl status`), or the cluster's cAdvisor has no samples yet. FlexaScale reads container-level series and falls back to pod-level ones (Docker runtime on cgroup v2). |
| Latency "no requests" for a service | It was scraped but served no requests in the last minute: a genuine 0 req/s, not missing data. |
| Port 8090/9090/3000 in use | The launcher never touches foreign processes. Free the port or set `FLEXASCALE_LAB_PORT`, `FLEXASCALE_PROMETHEUS_PORT`, `FLEXASCALE_GRAFANA_PORT`. |
| Dashboard does not load / looks outdated | `.runtime/logs/lab.log`; rebuild with `cd dashboard && npm run build` (the page is served with `no-cache`, so a reload shows the new build). |
| "controller lease held" / HPA left frozen | `fsctl stop` restores HPAs; `fsctl stop --force-release-lease` if a dead controller holds the Lease. |

Details: [U. Installing FlexaScale on any application](#u-installing-flexascale-on-any-kubernetes-application) · [V. Live Lab and reproducible evaluation](#v-live-autoscaling-lab-and-reproducible-evaluation) · [W. Retraining](#w-retraining-and-evaluating-the-policy) · docs/FINAL_DEMO_RUNBOOK.md · docs/POLICY_V9.md (this laptop)

---

## Architecture Overview

```
                        ┌─────────────────────────────────────────────────┐
                        │              FlexaScale Framework               │
                        └─────────────────────────────────────────────────┘

   [ Offline / Trace Mode ]                                  [ Live Cluster Mode ]
   
   Alibaba Microservice Trace                                Kubernetes Cluster (Minikube)
              │                                                            │
              ▼                                                            ▼
    data/raw/alibaba/v2021/                                  Microservice Dependency Chain
   (MSResource & MSRTQps)                                    (frontend → orders → inv → pay)
              │                                                            │
              ▼                                                            ▼
     Data Preprocessing                                      Prometheus Telemetry Scraper
   (build_dataset.py)                                          (5-second sampling rate)
              │                                                            │
              ▼                                                            ▼
  data/processed/alibaba_service_state.csv                    Prometheus Metrics Wrapper
              │                                               (flexascale.metrics.client)
              ▼                                                            │
   ┌───────────────────────────────────────────────────────────────────────┴───────────────┐
   │                        Shared State-Vector Schema (ServiceState)                      │
   │      - Time: timestamp, submit_time, start_time, finish_time, completion_time, wait    │
   │      - CPU / Mem: cpu_utilization, memory_utilization, cpu_memory_ratio               │
   │      - Hardware: replica_count, cpu_capacity, gpu_count, gpu_utilization              │
   │      - Performance: request_rate, latency_ms, jct, acceptance_ratio                   │
   │      - Reliability: successful_requests, failed_requests, error_rate, success_rate    │
   │      - Vector: [CPU%, Mem%, Replicas, RPS, Latency] (5D float32 per service)          │
   └───────────────────────────────────────────────────────────────────────┬───────────────┘
                                                                           │
                                                                           ▼
                                                                Gymnasium Simulation Env
                                                                   (FlexaScaleEnv)
                                                                           │
                                                                           ▼
                                                             PyG GNN Dependency Encoder
                                                                   (GNNExtractor)
                                                                           │
                                                                           ▼
                                                                  Stable-Baselines3 PPO
                                                                   (Actor-Critic Agent)
                                                                           │
                                                                           ▼
                                                              Confidence Proxy & Safety
                                                                (predict_with_fallback)
                                                                           │
                                                                           ▼
                                                               Horizontal Pod Scaling Actions
```

---

## Table of Contents
1. [A. Repository & Python Setup](#a-repository--python-setup)
2. [B. Verify Python & Scaffolding](#b-verify-python--scaffolding)
3. [C. Start Minikube Cluster](#c-start-minikube-cluster)
4. [D. Helm Installation & Repositories](#d-helm-installation--repositories)
5. [E. Deploy & Test Demo Microservices](#e-deploy--test-demo-microservices)
6. [F. Prometheus Monitoring & Metrics Scraping](#f-prometheus-monitoring--metrics-scraping)
7. [G. Grafana Dashboard & Visualization](#g-grafana-dashboard--visualization)
8. [H. Alibaba Trace Processing Pipeline](#h-alibaba-trace-processing-pipeline)
9. [I. Schema Validation (Dual SIM & LIVE Match)](#i-schema-validation)
10. [J. Gymnasium Cluster Environment](#j-gymnasium-cluster-environment)
11. [K. GNN Dependency Encoder](#k-gnn-dependency-encoder)
12. [L. PPO Reinforcement Learning Agent](#l-ppo-reinforcement-learning-agent)
13. [M. Training Loop, Evaluation & Baseline Comparison](#m-training-loop--baseline-comparison)
14. [N. Phase 4 — Safety & Execution Layer (HPA Fallback + Mutual-Exclusion Lock)](#n-phase-4--safety--execution-layer-hpa-fallback--mutual-exclusion-lock)
15. [O. Phase 3 — Live State Aggregator & Graph Inference](#o-phase-3--live-state-aggregator--graph-inference)
16. [P. Phase 4 — Kubernetes Operator (Autonomous Control Loop)](#p-phase-4--kubernetes-operator-autonomous-control-loop)
17. [Q. Phase 5 — Dashboard & REST API Backend](#q-phase-5--dashboard--rest-api-backend)
18. [R. Phase 6 — Integration, Locust Scenarios & Benchmarking](#r-phase-6--integration-locust-scenarios--benchmarking)
19. [S. Phase 6 — Helm Packaging & Cluster Deployment](#s-phase-6--helm-packaging--cluster-deployment)
20. [T. Phase 7 — Live Shopping Microservices Integration & Benchmark Evaluation](#t-phase-7--live-shopping-microservices-integration--benchmark-evaluation)
21. [Output Commands (Review PPT & Defense)](#output-commands)
22. [Run Everything Verification Flow](#-run-everything-verification-flow)
23. [Verification Checklist](#-verification-checklist)

---

## A. Repository & Python Setup

Clone or navigate to the repository directory, create a Python 3.10+ virtual environment, activate it, and install all required dependencies:

```bash
cd ~/flexascale

# 1. Create Python virtual environment
python3 -m venv .venv

# 2. Activate virtual environment
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1

# 3. Upgrade pip and install all project dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Install flexascale in editable mode
pip install -e .
```

---

## B. Verify Python & Project Setup

Verify the Python runtime version, package dependencies, and package imports:

```bash
# Check Python version (>= 3.10)
python3 --version

# Verify editable installation and package import
python3 -c "import flexascale; print('FlexaScale version:', flexascale.__name__)"

# Run full pytest test suite (138 tests across all modules)
pytest -v
```

Expected output: All 138 test cases across all 10 test modules (`test_package.py`, `test_schema.py`, `test_dataset_split.py`, `test_flexascale_env.py`, `test_gnn_encoder.py`, `test_safety.py`, `test_graph_inference.py`, `test_live_builder.py`, `test_operator.py`, `test_api.py`, `test_discovery.py`, `test_agnostic_operator.py`) pass with `0` failures and `0` warnings.

---

## C. Start Minikube Cluster

Start the dedicated local Kubernetes cluster profile named `flexascale`:

```bash
# Option 1: Using automated script
# Linux / macOS:
./scripts/setup_cluster.sh 6144 4 flexascale docker
# Windows PowerShell:
# .\scripts\setup_cluster.ps1 -Memory 6144 -Cpus 4 -Profile flexascale

# Option 2: Direct Minikube CLI
minikube start -p flexascale --driver=docker --cpus=4 --memory=6144 --kubernetes-version=v1.31.0
minikube addons enable metrics-server -p flexascale
minikube addons enable ingress -p flexascale
minikube addons enable dashboard -p flexascale

# Verify cluster status
minikube status -p flexascale
kubectl get nodes -o wide
```

---

## D. Helm Installation & Namespaces

Ensure namespaces and Helm repositories are configured:

```bash
# Create dedicated project namespaces
kubectl get namespace flexascale-apps || kubectl create namespace flexascale-apps
kubectl get namespace flexascale-monitoring || kubectl create namespace flexascale-monitoring

# Configure and update Helm repositories
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm repo add grafana https://grafana.github.io/helm-charts --force-update
helm repo update

# Verify namespaces
kubectl get namespaces
```

---

## E. Deploy & Test E-Commerce Microservices Application

The application is a full e-commerce shopping platform: a React frontend and **16 FastAPI backend microservices** with PostgreSQL persistence. Call graph (caller → callee):

| Service | Port | Calls | Role |
| :--- | ---: | :--- | :--- |
| api-gateway | 8000 | all public routes | Edge routing |
| user-service | 8001 | PostgreSQL | Accounts, JWT login |
| catalog-service | 8002 | PostgreSQL | Products, categories |
| cart-service | 8003 | catalog, inventory, pricing | Carts with promotions and tax |
| order-service | 8004 | cart, catalog, shipping, fraud, inventory, payment, notification | Checkout saga |
| inventory-service | 8005 | PostgreSQL | Stock, reservations |
| payment-service | 8006 | PostgreSQL | Simulated card payments (fault injection) |
| search-service | 8007 | catalog, pricing | BM25 ranked search with live prices |
| recommendation-service | 8008 | catalog, review | "Customers also viewed" |
| review-service | 8009 | PostgreSQL | Reviews and rating summaries |
| pricing-service | 8010 | promotion | Discounts and tax |
| promotion-service | 8011 | – | Promotion rules |
| shipping-service | 8012 | – | Delivery quotes (required in checkout) |
| fraud-service | 8013 | – | Risk score (required in checkout) |
| notification-service | 8014 | – | Order confirmation (best effort) |
| wishlist-service | 8015 | catalog, PostgreSQL | Saved products |

The longest chain is gateway → search → pricing → promotion. Checkout touches 8 services. All 16 have a CPU HPA (70%, 1–10 replicas, `deploy/kubernetes/hpa.yaml`).

### 1. Build & Load Container Images into Minikube

```bash
./scripts/build_shop_images.sh          # all 16 services + frontend, tags from charts/shopping-app/values.yaml
minikube -p flexascale image load postgres:16-alpine
```

The Minikube node container is limited to 9 GiB (`docker update --memory 9g --memory-swap 9g flexascale`; it was 6 GiB for the 7-service shop).

### 2. Deploy via Helm Chart

```bash
# Lint chart
helm lint charts/shopping-app

# Render manifests
helm template shopping-app charts/shopping-app

# Install or upgrade chart in flexascale-apps namespace
helm upgrade --install shopping-app charts/shopping-app -n flexascale-apps

# Verify all 18 pods (16 services + frontend + postgres) are Running and 1/1 Ready
kubectl apply -f deploy/kubernetes/hpa.yaml
kubectl get pods -n flexascale-apps -o wide
kubectl get svc -n flexascale-apps
```

### 3. Seed PostgreSQL Database

```bash
# Port-forward PostgreSQL and seed test data
kubectl port-forward svc/postgres -n flexascale-apps 54322:5432 &
PF_PID=$!
sleep 2
DATABASE_URL="postgresql+psycopg://postgres:postgresPassword123!@127.0.0.1:54322/ecommerce" python apps/database/seed.py
kill $PF_PID
```

### 4. Send End-to-End Test Request Through the Service Chain

```bash
# Execute automated live verification script against Ingress
API_URL="http://$(minikube -p flexascale ip)" python scripts/test_live_cluster.py

# Or test directly with curl:
curl -s http://$(minikube -p flexascale ip)/api/system/status
```

Expected response from `/api/system/status`:
```json
{
  "gateway": "healthy",
  "all_services_healthy": true,
  "services": {
    "users": {"url": "http://user-service:8001", "status": "up", "status_code": 200},
    "products": {"url": "http://catalog-service:8002", "status": "up", "status_code": 200},
    "cart": {"url": "http://cart-service:8003", "status": "up", "status_code": 200},
    "orders": {"url": "http://order-service:8004", "status": "up", "status_code": 200},
    "inventory": {"url": "http://inventory-service:8005", "status": "up", "status_code": 200},
    "payments": {"url": "http://payment-service:8006", "status": "up", "status_code": 200}
  }
}
```

---

## F. Prometheus Monitoring & Metrics Scraping

### 1. Deploy Prometheus Stack

```bash
# Option 1: Automated deployment script
./scripts/deploy_monitoring.sh
# Windows PowerShell: .\scripts\deploy_monitoring.ps1

# Option 2: Helm upgrade command
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace flexascale-monitoring \
  -f k8s/prometheus-values.yaml
```

### 2. Access Prometheus Web UI & Verify Metrics

```bash
# Terminal 1: Port-forward Prometheus Server
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n flexascale-monitoring 9090:9090
```

Open browser at `http://localhost:9090` and verify targets under **Status → Targets**:
- All pods in `flexascale-apps` (`frontend`, `orders`, `inventory`, `payments`) show state **UP**.

### Useful Working PromQL Queries:
- **CPU Utilization (%)**:
  ```promql
  avg by (app) (rate(container_cpu_usage_seconds_total{namespace="flexascale-apps", container!=""}[1m])) * 100
  ```
- **Memory Utilization (%)**:
  ```promql
  avg by (app) (container_memory_working_set_bytes{namespace="flexascale-apps", container!=""} / container_spec_memory_limit_bytes{namespace="flexascale-apps", container!=""}) * 100
  ```
- **Request Rate (req/s)**:
  ```promql
  sum by (app) (rate(http_requests_total{namespace="flexascale-apps"}[1m]))
  ```
- **Response Latency (ms)**:
  ```promql
  avg by (app) (rate(http_request_duration_seconds_sum{namespace="flexascale-apps"}[1m]) / rate(http_request_duration_seconds_count{namespace="flexascale-apps"}[1m])) * 1000
  ```
- **Error Rate (%)**:
  ```promql
  (sum by (app) (rate(http_requests_total{namespace="flexascale-apps", status=~"5.."}[1m])) / sum by (app) (rate(http_requests_total{namespace="flexascale-apps"}[1m]))) * 100
  ```

---

## G. Grafana Dashboard & Visualization

### 1. Access Grafana UI

```bash
# Terminal 1: Port-forward Grafana Service
kubectl port-forward svc/monitoring-grafana -n flexascale-monitoring 3000:80
```

- **URL**: `http://localhost:3000`
- **Username**: `admin`
- **Password**: `admin`

### 2. Verify Dashboards & Live Metrics

1. In Grafana, navigate to **Dashboards → FlexaScale - Microservices Auto-Scaling Dashboard** (auto-provisioned via ConfigMap `flexascale-grafana-dashboard`).
2. Verify all panels display real-time live data:
   - ✅ **CPU Utilization per Service**
   - ✅ **Memory Utilization per Service**
   - ✅ **Request Rate (Throughput)**
   - ✅ **Response Latency**
   - ✅ **Error Rate (%)**
   - ✅ **Active Running Pod Replicas**

### 3. Deploy or Update Dashboard ConfigMap

To apply or refresh the Grafana dashboard JSON:

```bash
# Apply updated dashboard ConfigMap into flexascale-monitoring namespace
kubectl apply -f observability/grafana/dashboard-configmap.yaml

# Restart Grafana deployment to trigger immediate reload
kubectl rollout restart deployment monitoring-grafana -n flexascale-monitoring
```

---

## H. Alibaba Trace Processing Pipeline & Dataset Splits

Process raw Alibaba cluster traces (`MSResource` and `MSRTQps`) into the unified service state dataset and generate Train / Validation / Test partitions:

```bash
# 1. Run dataset builder pipeline (generates full dataset and 70/15/15 splits)
python3 src/flexascale/data/build_dataset.py

# 2. (Optional) Re-split with custom ratios or methods via standalone CLI
python3 scripts/split_dataset.py --method temporal --train-ratio 0.70 --val-ratio 0.15 --test-ratio 0.15
```

Output files in `data/processed/`:
- `alibaba_service_state.csv`: Full unified dataset (36,355 rows, 30 timestamps, 1,213 services, ~5.4 MB).
- `alibaba_service_state_train.csv`: Training split (25,446 rows, 21 timestamps, 70.0%).
- `alibaba_service_state_val.csv`: Validation split (4,847 rows, 4 timestamps, 13.3%).
- `alibaba_service_state_test.csv`: Testing split (6,062 rows, 5 timestamps, 16.7%).

> [!NOTE]
> Splitting uses **temporal chronological partitioning** across timestamps. This prevents future lookahead leakage into training data, strictly preserving the causality needed for reinforcement learning auto-scaling.

---

## I. Schema Validation

Verify that both the offline trace simulator and live Prometheus monitoring pipelines generate identical, compatible schema vectors:

```bash
python3 scripts/validate_schema.py
```

Expected output:
```text
==================================================
 FlexaScale - Dual Schema Match Validation
==================================================
[*] Validating SIM (Alibaba) data schema...
  [+] SIM Validation passed! Vector shape: (5,), dtype: float32
      Extended metrics -> CPU/Mem Ratio: 0.75, Error Rate: 1.33%, JCT: 25.4ms

[*] Validating LIVE (Prometheus) data schema...
  [+] LIVE Validation passed! Vector shape: (5,), dtype: float32
      Extended metrics -> CPU/Mem Ratio: 0.00, Error Rate: 0.00%

[SUCCESS] Schema contract validated perfectly between LIVE and SIM data pipelines!
Observation Dimension: 5 | Vector Fields: ('cpu_utilization', 'memory_utilization', 'replica_count', 'request_rate', 'latency_ms')
```

---

## J. Gymnasium Cluster Environment

Run the cluster simulation environment over the Alibaba trace:

```bash
# 1. Multi-service simulation (default: 4 services, 3 episodes)
python3 scripts/run_sanity_simulation.py --episodes 3 --seed 42

# 2. Single-service simulation (targeting specific microservice ID)
python3 scripts/run_sanity_simulation.py --service-id 002251d4123496684687c2acad43bdef9419a5e4fc01a65d2c558af92a5ad649 --episodes 1

# 3. Custom SLO latency and CPU target thresholds
python3 scripts/run_sanity_simulation.py --episodes 3 --slo-target 100.0 --cpu-target 70.0
```

### CLI Parameters:
- `--episodes`: Number of simulation episodes to run (default: `3`)
- `--seed`: Base random seed for reproducibility (default: `42`)
- `--slo-target`: Target latency SLO in milliseconds (default: `100.0`)
- `--cpu-target`: Target CPU utilization percentage (default: `70.0%`)
- `--service-id`: Specific service ID to simulate in single-service mode

### Simulation Diagnostics Columns:
- `step`: Simulation step index in the trace time-window
- `actions`: Scaling actions executed per service (`U`=Scale UP, `D`=Scale DOWN, `M`=MAINTAIN)
- `avg_reps`: Average replica count across active services
- `avg_cpu%` / `avg_mem%`: Average cluster CPU and Memory utilization percentages
- `tot_rps`: Aggregate request throughput (requests per second)
- `avg_lat` / `max_lat`: Average and bottleneck maximum response latencies (ms)
- `reward`: Multi-objective composite step reward
- `SLO`: `ok` (SLO satisfied) or `FAIL` (`max_lat > slo_target`)

---

## K. GNN Dependency Encoder

Verify PyTorch Geometric graph convolutions over the microservice call-graph topology:

```bash
pytest -v tests/test_gnn_encoder.py
```

Validates:
- `ServiceDependencyGraph` directed and bidirectional edges with self-loops.
- `GNNDependencyEncoder` multi-layer GCN, GAT, and GraphSAGE message passing.
- `GNNExtractor` BaseFeaturesExtractor integration for Stable-Baselines3.

---

## L. PPO Reinforcement Learning Agent

Train the PPO actor-critic agent integrated with the GNN dependency feature extractor on the **training split** while continuously evaluating and checkpointing `best_model` against the **validation split**:

```bash
# Train PPO agent with GNN encoder on training split with validation checkpointing
python3 src/flexascale/rl/train.py \
  --timesteps 5000 \
  --split train \
  --eval-split val \
  --extractor gnn \
  --conv-type gcn \
  --hidden-dim 64
```

Output:
- Checkpoints saved in `models/checkpoints/`
- Best evaluation model (evaluated on validation split) saved in `models/best_model/`
- Final trained model saved to `models/ppo_flexascale_final.zip`
- Tensorboard telemetry written to `logs/tb/`

---

## M. Training Loop & Baseline Comparison

Evaluate the trained PPO agent with confidence-proxy safety fallback against the standard Kubernetes HPA heuristic baseline on the **unseen test split**:

```bash
# Evaluate baseline vs RL on the held-out test split
python3 scripts/evaluate_baseline_vs_rl.py --split test --episodes 5 --threshold 0.8
```

Expected output comparison table:
```text
================================================================================
EVALUATION COMPARISON: BASELINE (HPA Heuristic) vs RL (PPO + Confidence Proxy)
================================================================================
Metric                    | Baseline (Heuristic)      | RL + Proxy               
--------------------------------------------------------------------------------
Avg Total Reward          | -7.872                    | +10.827                  
SLO Violation Rate        | 100.00%                   | 100.00%                  
Avg Fallbacks (per ep)    | N/A                       | 30.0                     
================================================================================
```

---

## N. Phase 4 — Safety & Execution Layer (HPA Fallback + Mutual-Exclusion Lock)

Phase 4 introduces the safety execution boundary between RL policies and Kubernetes HPA, guaranteeing that **RL and HPA never attempt to scale workloads concurrently**.

```text
             Metrics (Prometheus)
                     ↓
               RL Controller
                     ↓
            RL action + confidence
                     ↓
            Safety Coordinator
               ↙             ↘
      HIGH CONFIDENCE       LOW CONFIDENCE / FAILURE
      (conf ≥ 0.70)             (conf < 0.60, NaN, Crash)
           ↓                            ↓
      Acquire Lock (Mode=RL)       Release Lock (Mode=HPA)
      Freeze HPA (min=N, max=N)    Restore HPA (min=1, max=10)
      Scale Deployment to N        Dynamic HPA Controls Workload
```

### 1. Deploy Native HorizontalPodAutoscalers (HPA v2)

Deploy the native Kubernetes HPA manifests for all 4 demo microservices:

```bash
# Apply HPA manifests for all 4 microservices
kubectl apply -f deploy/kubernetes/hpa.yaml

# Verify HPA resources and targets (targets: cpu: 70%, min: 1, max: 10)
kubectl get hpa -n flexascale-apps
```

### 2. Run Dedicated Safety Unit Tests

Execute the 11 unit tests covering mutual exclusion, hysteresis, cooldown, lease expiration, and fail-safe recovery:

```bash
pytest tests/test_safety.py -v
```

### 3. Run Safety & Fallback Automated Demo

The safety controller script executes 7 sequential verification scenarios (High Confidence RL Scaling, Confidence Soft Drop, Low Confidence Fallback, Cooldown Spike Suppression, Invalid/Missing Confidence, Lease Expiry / Crash Recovery, and Cluster Teardown):

```bash
# Standalone / In-memory mock mode (runs in any environment without Kubernetes):
python3 scripts/run_safety_controller.py --demo

# Live mode against Minikube cluster (manipulates live Deployments, HPAs, and ConfigMap):
python3 scripts/run_safety_controller.py --live --demo
```

### 4. Run Live Controller on a Specific Service

To target a specific microservice with custom confidence thresholds and cooldown timings:

```bash
python3 scripts/run_safety_controller.py --live --service frontend --threshold 0.70 --cooldown 15.0
```

### 5. Inspect Observable Cluster Lock State

Verify the live ConfigMap used for cross-process mutual-exclusion locking:

```bash
kubectl get configmap -n flexascale-apps flexascale-safety-lock -o yaml
```

```bash
python3 -c "from flexascale.safety import SafetyCoordinator; c = SafetyCoordinator(live=True); c.fallback_all_to_hpa('manual_reset')"
```

---

## O. Phase 3 — Live State Aggregator & Graph Inference

Phase 3 bridges live Prometheus telemetry into the exact mathematical observation schema and dynamically discovers caller-callee microservice dependencies using Exponential Moving Average (EMA) decay:

$$W_{u,v}^{(t)} = \alpha \cdot \text{traffic}_{u,v}^{(t)} + (1 - \alpha) \cdot W_{u,v}^{(t-1)}$$

### 1. Run Dedicated Phase 3 Unit Tests

```bash
pytest tests/test_graph_inference.py tests/test_live_builder.py -v
```

Validates:
- Real-time online EMA edge weighting, passive decay, and pruning of inactive dependencies.
- Conversion to PyTorch Geometric `edge_index` (`(2, E)`) tensor and `ServiceDependencyGraph`.
- Transformation of Prometheus metrics into the concatenated 20-dimensional `(num_services * 5,)` observation vector.

### 2. Live State Aggregator CLI Verification

```bash
python3 -c "from flexascale.state import LiveStateBuilder; b = LiveStateBuilder(mock=True); s = b.build(); print('Observation Shape:', s.observation_vector.shape); print('Services:', list(s.service_states.keys()))"
```

Expected output:
```text
Observation Shape: (20,)
Services: ['frontend', 'orders', 'inventory', 'payments']
```

---

## P. Phase 4 — Kubernetes Operator (Autonomous Control Loop)

The FlexaScale Operator is the autonomous scaling daemon that continuously queries live telemetry, updates the dependency graph, estimates RL action probabilities, and executes scaling decisions through the mutual-exclusion safety layer.

### 1. Run Dedicated Operator Unit Tests

```bash
pytest tests/test_operator.py -v
```

### 2. Run Operator Demo Simulation

Execute a 3-step demonstration of autonomous operator scaling, confidence evaluation, and fail-safe shutdown:

```bash
python3 scripts/run_operator.py --demo
```

**Sample Output (High-Confidence RL Autonomous Scaling)**:
```text
================================================================================
FLEXASCALE AUTONOMOUS OPERATOR
Mode: MOCK / DEMO
Confidence Threshold: 0.70
Hysteresis Floor:     0.60
Poll Interval:        5.0s
================================================================================

[*] Running 3 autonomous operator control steps in demo mode...

--- Step 1: Normal Traffic ---
Service      | Mode   | Conf   | Target | Action  | Lock  | HPA Frozen | Reason
--------------------------------------------------------------------------------
frontend     | HPA    | 0.57   | 2      | None    | False | False      | low_confidence
orders       | RL     | 0.92   | 3      | +2      | True  | True       | high_confidence_rl_scaling
inventory    | HPA    | 0.47   | 2      | None    | False | False      | low_confidence
payments     | RL     | 0.70   | 2      | +1      | True  | True       | high_confidence_rl_scaling

--- Step 2: Traffic & CPU Surge on Frontend ---
[LOCK] Renewed RL scaling lease for 'orders' (expires in 60.0s)
[HPA] Freezing HPA conflicts for 'orders' to target replicas (min=3, max=3)
[RL] Applying scale action to 'orders': 3 replicas
Service      | Mode   | Conf   | Target | Action  | Lock  | HPA Frozen | Reason
--------------------------------------------------------------------------------
frontend     | HPA    | 0.57   | 2      | None    | False | False      | low_confidence
orders       | RL     | 0.93   | 3      | +2      | True  | True       | high_confidence_rl_scaling
inventory    | HPA    | 0.47   | 2      | None    | False | False      | low_confidence
payments     | RL     | 0.71   | 2      | +1      | True  | True       | high_confidence_rl_scaling
```

### 3. Launch Autonomous Operator Daemon (Live or Mock)

```bash
# In-memory mock mode:
python3 scripts/run_operator.py --interval 5.0 --threshold 0.70

# Live Minikube cluster mode:
python3 scripts/run_operator.py --live --interval 5.0 --threshold 0.70
```

---

## Q. Phase 5 — Dashboard & REST API Backend

Phase 5 provides a high-performance FastAPI telemetry backend coupled with a modern dark-mode, glassmorphic real-time React web dashboard.

### 1. Run Dedicated REST API Unit Tests

```bash
pytest tests/test_api.py -v
```

### 2. Launch FastAPI Server & Live Dashboard

```bash
# Start server on port 8080 (Mock mode)
python3 scripts/run_api.py --port 8080

# Start server connected to live Minikube cluster & Prometheus:
python3 scripts/run_api.py --live --port 8080
```

- **Live Dashboard Web UI**: [http://localhost:8080](http://localhost:8080)
- **Interactive OpenAPI Docs**: [http://localhost:8080/docs](http://localhost:8080/docs)

### 3. Key REST API Endpoints

```bash
# Check cluster status and controller ownership modes:
curl -s http://localhost:8080/api/status | jq .

# Retrieve real-time microservice metrics & SLO compliance:
curl -s http://localhost:8080/api/metrics | jq .

# Retrieve inferred dependency call-graph with EMA weights:
curl -s http://localhost:8080/api/graph | jq .

# Inspect recent scaling decisions audit log:
curl -s http://localhost:8080/api/decisions | jq .

# Dynamically adjust SLO and safety parameters:
curl -X POST http://localhost:8080/api/config \
  -H "Content-Type: application/json" \
  -d '{"slo_latency_target_ms": 120.0, "confidence_threshold": 0.75}'

# Trigger emergency cluster-wide fallback to native HPA:
curl -X POST http://localhost:8080/api/fallback
```

---

## R. Phase 6 — Integration, Locust Scenarios & Benchmarking

### 1. Run Full End-to-End Closed-Loop Controller

Execute the integrated closed-loop pipeline uniting traffic generation, live state building, GNN + PPO policy inference, safety locking, and scaling execution:

```bash
# Automated 5-step closed-loop demonstration:
python3 scripts/run_closed_loop.py --demo

# Continuous live cluster execution:
python3 scripts/run_closed_loop.py --live --interval 5.0 --threshold 0.70
```

### 2. Execute Locust Multi-Scenario Load Generation

Generate traffic profiles matching realistic e-commerce traffic waves:

```bash
# 1. Lunch Spike (high checkout rush):
python3 scripts/run_locust_scenarios.py --scenario lunch_spike --duration 30

# 2. Quiet Night (low off-peak background traffic):
python3 scripts/run_locust_scenarios.py --scenario quiet_night --duration 20

# 3. Burst (sudden step spike testing autoscaler reaction lag):
python3 scripts/run_locust_scenarios.py --scenario burst --users 50 --duration 25

# 4. Run all scenarios in mock benchmark mode:
python3 scripts/run_locust_scenarios.py --scenario all --mock
```

### 3. FlexaScale vs. Standard Kubernetes HPA Benchmark

Execute controlled comparative benchmarks between native Kubernetes HPA (reactive CPU threshold) and FlexaScale RL + GNN + Safety Fallback:

```bash
python3 scripts/run_hpa_vs_rl_benchmark.py --episodes 3 --split test --threshold 0.70
```

Outputs:
- Terminal ASCII comparison table (Mean/P95/P99 latency, SLO violation rate, average replicas, oscillations).
- Formatted Markdown report: `reports/benchmark_report.md`
- Raw telemetry JSON summary: `reports/benchmark_summary.json`

---

## S. Application-Agnostic Helm Packaging & Cluster Deployment

FlexaScale is packaged as a fully application-agnostic, reusable Kubernetes add-on. It can be installed into any Kubernetes cluster (EKS, GKE, AKS, Minikube, kind) to autoscale **any containerized microservice application without requiring any changes to the application's source code or Docker images**.

### 1. Key Application-Agnostic Features
- **Automatic Workload Discovery**: Dynamically identifies scalable Deployments in the target namespace via the Kubernetes API or Prometheus, filtering out system components.
- **Zero-Code Prometheus Telemetry**: Collects CPU, memory, and replica metrics from standard Kubernetes infrastructure (cAdvisor and kube-state-metrics). Falls back to container network I/O if application-level HTTP endpoints are uninstrumented.
- **Dynamic Dependency Call Graph**: Infers caller-callee request flows from Prometheus traffic with online Exponential Moving Average (EMA) decay.
- **Graph-Size Invariant GNN + PPO Engine**: Automatically adapts to any number of microservices ($N \ge 1$) using node-level scaling policy evaluation.
- **Conflict-Free Safety Coordinator**: Enforces mutual exclusion, clamping HPA min=max during high-confidence RL ownership and safely restoring dynamic HPA bounds on low confidence, crash, or shutdown.

### 2. Lint and Verify Helm Chart

```bash
# Validate chart syntax and guidelines
helm lint helm/flexascale

# Render and inspect Kubernetes manifests with custom target namespace and label selector
helm template flexascale helm/flexascale \
  --set targetNamespace=production \
  --set discovery.labelSelector="app.kubernetes.io/part-of=ecommerce"
```

### 3. Install FlexaScale on Any Kubernetes Cluster

```bash
# Option A: Monitor and autoscale all deployments in a custom namespace (e.g. 'ecommerce')
helm upgrade --install flexascale helm/flexascale \
  --namespace flexascale-system --create-namespace \
  --set targetNamespace=ecommerce \
  --set operator.threshold=0.70 \
  --set autoscaling.sloLatencyTargetMs=100.0

# Option B: Monitor specific deployments filtered by label selector
helm upgrade --install flexascale helm/flexascale \
  --namespace flexascale-system --create-namespace \
  --set targetNamespace=my-app \
  --set discovery.labelSelector="flexascale.io/managed=true"

# Option C: Deploy to local Minikube cluster
helm upgrade --install flexascale helm/flexascale \
  --namespace flexascale-apps \
  --set targetNamespace=flexascale-apps

# Verify deployed FlexaScale operator and dashboard pods
kubectl get pods -n flexascale-system -l app.kubernetes.io/name=flexascale
kubectl get svc -n flexascale-system -l app.kubernetes.io/name=flexascale
```

### 4. Test Operator with Custom Microservices (Zero-Code Demo)

To verify that FlexaScale operates on a completely different set of microservices without demo assumptions:

```bash
# Run 3-step autonomous operator demo on arbitrary services (auth-api, cart-service, catalog-db):
python3 scripts/run_operator.py --demo --custom-app

# Run 5-step closed-loop simulation on arbitrary custom workloads:
python3 scripts/run_closed_loop.py --demo --custom-app
```

---

## T. Phase 7 — Live Shopping Microservices Integration & Benchmark Evaluation

> **Historical (Phase 7, 7-service shop).** The shop now has **16 services** (Helm chart 1.1.0; table at the top of README.md, 16 HPAs in `deploy/kubernetes/hpa.yaml`). Live evaluation now runs through the lab (Quick Start, section V), and the operator evaluates any number of services in 4-service neighbourhood windows, so the 7 × 5 = 35 input described below applies only to that original setup.

FlexaScale directly integrates with the real seven-backend-microservice e-commerce shopping application:
1. `api-gateway` (Port 8000) — Central entry point & reverse proxy with custom forward metrics.
2. `user-service` (Port 8001) — Authentication, profiles, and address management.
3. `catalog-service` (Port 8002) — Product exploration, full-text search, categories.
4. `cart-service` (Port 8003) — In-memory & DB cart item lifecycle.
5. `order-service` (Port 8004) — Saga orchestration, checkout, order state.
6. `inventory-service` (Port 8005) — Stock levels, reservation locks, release rollback.
7. `payment-service` (Port 8006) — Simulated payment processing & delay injection.

### 1. Preflight Checks
Verify Minikube, pods, Services, and port-forwards are healthy:
```bash
# Verify all 9 pods in flexascale-apps are 1/1 Running
kubectl get pods -n flexascale-apps -o wide

# Verify all 7 HPAs are active with target metrics
kubectl get hpa -n flexascale-apps

# Port-forward Prometheus server (Terminal 1)
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n flexascale-monitoring 9090:9090

# Port-forward API Gateway (Terminal 2)
kubectl port-forward svc/api-gateway -n flexascale-apps 8000:8000

# Verify connectivity
curl -s http://localhost:9090/-/ready
curl -s http://localhost:8000/api/products | jq .total
```

### 2. Schema and Discovery Validation
Verify that all 7 microservices are dynamically discovered and telemetry maps strictly to the 35-dimensional observation vector ($7 \times 5 = 35$):
```bash
source .venv/bin/activate
python3 scripts/validate_schema.py
```

### 3. Observation-Only Operation (Dry-Run Mode)
Observe live Prometheus telemetry, GNN inference, and safety fallback decisions without modifying Kubernetes replicas:
```bash
python3 scripts/run_closed_loop.py --steps 5 --interval 3.0
```

### 4. Safe Live Execution
Execute the closed-loop controller live in Minikube with mutual-exclusion ConfigMap lease locks and HPA conflict prevention:
```bash
python3 scripts/run_closed_loop.py --live --steps 5 --interval 3.0 --threshold 0.70
```

### 5. Locust Load Generation Experiments
Stress the seven microservices under real customer shopping journeys (catalog browsing, cart, checkout, payment latency, and flash-sale contention):
```bash
.venv/bin/locust -f load-testing/locustfile.py --headless -u 30 -r 5 --run-time 60s --host http://localhost:8000 --exit-code-on-error 0
```

### 6. Native HPA Baseline Benchmark Run
Run Native Kubernetes HPA exclusively (with RL locks released and HPA dynamic bounds enabled):
```bash
python3 scripts/run_live_shopping_benchmark.py --duration 60 --users 30 --spawn-rate 5
```

### 7. FlexaScale RL Evaluation Run
The benchmark runner executes Phase B automatically, isolating FlexaScale under identical Locust load while freezing HPA to prevent controller fighting.

### 8. Benchmark Report Generation
Raw telemetry and comparative markdown analysis are automatically generated:
```bash
cat reports/shopping_benchmark_report.md
cat reports/shopping_benchmark_raw.json | jq .metadata
head -n 10 reports/shopping_benchmark_telemetry.csv
```

### 9. Rollback and Cleanup
Restore all microservices to baseline conditions and release all safety locks:
```bash
# 1. Reset all deployments to 1 replica
for svc in api-gateway user-service catalog-service cart-service order-service inventory-service payment-service; do
  kubectl scale deployment/$svc -n flexascale-apps --replicas=1
done

# 2. Restore native dynamic HPA bounds (1 to 10 replicas)
for svc in api-gateway user-service catalog-service cart-service order-service inventory-service payment-service; do
  kubectl patch hpa/${svc}-hpa -n flexascale-apps --type=merge -p '{"spec":{"minReplicas":1,"maxReplicas":10}}'
done

# 3. Emergency lock release via API or script
curl -X POST http://localhost:8080/api/fallback
```

---

## Output Commands

This section provides the authoritative set of commands to generate, inspect, and extract real-time metrics, telemetry graphs, benchmark tables, and safety logs for your **review presentation and PPT slides**.

### 1. Cluster & Monitoring Infrastructure Startup

Start Minikube and expose all monitoring and application interfaces:

```bash
# Start Minikube cluster
minikube start -p flexascale

# Terminal 1: Port-forward Prometheus Server (Port 9090)
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n flexascale-monitoring 9090:9090

# Terminal 2: Port-forward Grafana Web UI (Port 3000)
kubectl port-forward svc/monitoring-grafana -n flexascale-monitoring 3000:80

# Terminal 3: Port-forward Frontend API Gateway (Port 8000)
kubectl port-forward svc/frontend -n flexascale-apps 8000:8000
```

> **Direct Access URLs**:
> - **Grafana Dashboard**: [http://localhost:3000/d/flexascale-overview/flexascale-microservices-auto-scaling-dashboard](http://localhost:3000/d/flexascale-overview/flexascale-microservices-auto-scaling-dashboard) (*Login: `admin` / `admin`*)
> - **Prometheus UI**: [http://localhost:9090](http://localhost:9090)
> - **Frontend Gateway**: [http://localhost:8000/api/checkout](http://localhost:8000/api/checkout)

---

### 2. Locust Load Generation (Dynamic Curves for Grafana & Prometheus)

Generate a wave of multi-user concurrent traffic through the entire 4-tier microservice chain to produce live spikes, latency steps, and CPU curves:

```bash
cd ~/flexascale
source .venv/bin/activate

# Run headless load test (30 users, 6 spawn rate, 45 seconds)
locust -f load-testing/locustfile.py --headless -u 30 -r 6 --run-time 45s --host http://localhost:8000
```

**Expected PPT Output (Latency Percentiles & Throughput)**:
```text
Type     Name             # reqs      # fails |    Avg     Min     Max    Med |   req/s  failures/s
--------|----------------|-------|-------------|-------|-------|-------|-------|--------|-----------
GET      /                   593     0(0.00%) |      5       1      18      6 |   13.27        0.00
POST     /api/checkout       213     0(0.00%) |    415     312     519    420 |    4.77        0.00
--------|----------------|-------|-------------|-------|-------|-------|-------|--------|-----------
         Aggregated          806     0(0.00%) |    113       1     519      6 |   18.04        0.00

Response time percentiles (approximated)
Type     Name             50%    66%    75%    80%    90%    95%    98%    99%    100% # reqs
--------|----------------|------|------|------|------|------|------|------|------|------|------
GET      /                  6      6      7      7      7      8     14     16     18    593
POST     /api/checkout    420    460    470    480    490    510    510    510    520    213
--------|----------------|------|------|------|------|------|------|------|------|------|------
         Aggregated         6      7    320    360    440    480    500    510    520    806
```

---

### 3. Prometheus PromQL Telemetry Commands

Execute these working PromQL expressions directly in the Prometheus Web UI ([http://localhost:9090](http://localhost:9090)) or via API to verify the live scrape values:

* **Request Rate per Service (RPS)**:
  ```promql
  sum by (app) (rate(http_requests_total{namespace="flexascale-apps"}[1m]))
  ```
* **Response Latency per Service (ms)**:
  ```promql
  avg by (app) (rate(http_request_duration_seconds_sum{namespace="flexascale-apps"}[1m]) / rate(http_request_duration_seconds_count{namespace="flexascale-apps"}[1m])) * 1000
  ```
* **CPU Utilization per Service (%)**:
  ```promql
  avg by (container) (rate(container_cpu_usage_seconds_total{namespace="flexascale-apps", container=~"frontend|orders|inventory|payments"}[1m])) * 100
  ```
* **Memory Utilization per Service (%)**:
  ```promql
  (sum by (container) (container_memory_working_set_bytes{namespace="flexascale-apps", container=~"frontend|orders|inventory|payments"}) / sum by (container) (kube_pod_container_resource_limits{namespace="flexascale-apps", resource="memory"})) * 100
  ```
* **Active Pod Replicas per Service**:
  ```promql
  sum by (deployment) (kube_deployment_status_replicas_ready{namespace="flexascale-apps"})
  ```

---

### 4. Baseline (HPA Heuristic) vs RL (PPO + Confidence Proxy) Evaluation

Compare the standard Kubernetes HPA heuristic against the PPO + GNN agent on the test split:

```bash
# Evaluate baseline vs RL on the test split (calibrated confidence threshold 0.50)
python3 scripts/evaluate_baseline_vs_rl.py --split test --episodes 3 --threshold 0.50
```

**Expected PPT Output (Comparison Table)**:
```text
================================================================================
EVALUATION COMPARISON: BASELINE (HPA Heuristic) vs RL (PPO + Confidence Proxy)
================================================================================
Metric                    | Baseline (Heuristic)      | RL + Proxy               
--------------------------------------------------------------------------------
Avg Total Reward          | 1.193                     | 1.297                    
SLO Violation Rate        | 100.00%                   | 100.00%                  
Avg Fallbacks (per ep)    | N/A                       | 11.0                     
================================================================================
```

> **Note on Confidence Threshold**: In a 3-choice discrete action space ($\Delta \in \{-1, 0, +1\}$), random guessing is 33.3%. Setting a threshold of `0.80` causes 100% of decisions to fall back to HPA because the model's exploratory softmax output sits between 45%–65%. Calibrating to `0.50` allows high-confidence RL decisions to take effect, boosting reward while falling back safely when uncertain.


---

### 5. Dataset Splits & Statistics (Dataset Architecture Slide)

Display the chronological train / val / test breakdown and schema validation stats for review presentation slides:

```bash
# Display dataset split stats and verification
python3 scripts/split_dataset.py --method temporal
```

**Expected PPT Output (Dataset Split Table)**:
```text
================================================================================
FLEXASCALE ALIBABA TRACE DATASET SPLIT SUMMARY (TEMPORAL LEAK-FREE)
================================================================================
Split       | Timestamps | Range (ms)              | Records   | % of Dataset | Services
-----------------------------------------------------------------------------------------
Train (70%) | 21         | 0 -> 1,200,000          | 25,446    | 70.0%        | 1,213
Val (15%)   | 4          | 1,260,000 -> 1,440,000  | 4,847     | 13.3%        | 1,213
Test (15%)  | 5          | 1,500,000 -> 1,740,000  | 6,062     | 16.7%        | 1,213
-----------------------------------------------------------------------------------------
Total       | 30         | 0 -> 1,740,000          | 36,355    | 100.0%       | 1,213
Schema      | 25 ServiceState fields verified across all subsets (Pass)
================================================================================
```

---

### 6. Phase 4 Safety Controller Verification Demo (7 Scenarios)

Demonstrate mutual exclusion locking, HPA conflict-free freezing, hysteresis, cooldown anti-thrashing, and crash recovery:

```bash
# Run against live Minikube cluster
python3 scripts/run_safety_controller.py --live --demo
```

**Expected PPT Output**:
```text
================================================================================
FLEXASCALE PHASE 4 — SAFETY & HPA FALLBACK VERIFICATION DEMO
Target Service: frontend
Confidence Threshold (RL Activation):   0.70
Deactivation Floor (Hysteresis):        0.60
Cooldown Period:                        15.0s
Lock TTL (Crash Recovery):              60.0s
================================================================================

[Scenario 1] High Confidence RL Action (conf=0.85, action=2 -> Scale UP)
  [LOCK] RL acquired scaling ownership for 'frontend' (ControlMode=RL, TTL=60.0s)
  [HPA]  Freezing HPA conflicts for 'frontend' to target replicas (min=2, max=2)
  [RL]   Successfully scaled 'frontend' to 2 replicas under RL ownership.
  Result -> Mode: RL, Target Replicas: 2, Lock: True, HPA Frozen: True

[Scenario 2] Confidence Soft Drop (conf=0.65: above 0.60 floor, maintains RL)
  [LOCK] Renewed RL scaling lease for 'frontend' (expires in 60.0s)
  Result -> Mode: RL, Replicas: 2, HPA Frozen: True

[Scenario 3] Low Confidence Drop (conf=0.45 < 0.60 -> Release Lock, Restore HPA)
  [LOCK] Releasing scaling ownership for 'frontend' back to HPA (reason: low_confidence)
  [HPA]  Restoring dynamic HPA bounds for 'frontend' (min=1, max=10, targetCPU=70%)
  Result -> Mode: HPA, Lock: False, HPA Active: True

[Scenario 4] Immediate High Confidence Spike During Cooldown (conf=0.88)
  [SAFETY] RL confidence >= 0.70, but cooldown active (15.0s remaining). Maintaining HPA.
  Result -> Mode: HPA, Reason: low_confidence

[Scenario 5] Missing/Invalid Confidence (conf=None -> Fail Safe to HPA)
  [SAFETY] Invalid or missing confidence for 'frontend' (value=None). Falling back safely.
  Result -> Mode: HPA, HPA Active: True

[Scenario 6] Simulated Crash / Lease Expiration Recovery
  [LOCK] Lease expired for 'frontend' (TTL elapsed). Failing safe to HPA.
  Expired services: ['frontend'] -> Mode restored to: HPA

[Scenario 7] Cluster Teardown / Safe Fallback All to HPA
  [SAFETY] Falling back all services to HPA (frontend, orders, inventory, payments)...
================================================================================
ALL PHASE 4 SAFETY & HPA FALLBACK SCENARIOS VERIFIED SUCCESSFULLY!
================================================================================
```

---

### 6. Dual SIM vs LIVE Schema Contract Validation

Verify mathematical parity between offline Alibaba traces and live Prometheus vectors:

```bash
python3 scripts/validate_schema.py
```

**Expected PPT Output**:
```text
==================================================
 FlexaScale - Dual Schema Match Validation
==================================================
[*] Validating SIM (Alibaba) data schema...
  [+] SIM Validation passed! Vector shape: (5,), dtype: float32
      Extended metrics -> CPU/Mem Ratio: 0.75, Error Rate: 1.33%, JCT: 25.4ms

[*] Validating LIVE (Prometheus) data schema...
  [+] LIVE Validation passed! Vector shape: (5,), dtype: float32
      Extended metrics -> CPU/Mem Ratio: 0.00, Error Rate: 0.00%

[SUCCESS] Schema contract validated perfectly between LIVE and SIM data pipelines!
Observation Dimension: 5 | Vector Fields: ('cpu_utilization', 'memory_utilization', 'replica_count', 'request_rate', 'latency_ms')
```

---

### 7. End-to-End Microservice Chain Test

Send an end-to-end checkout call traversing all 4 services:

```bash
curl -X POST http://localhost:8000/api/checkout
```

**Expected PPT Output (Multi-Tier Call Trace)**:
```json
{
  "service": "frontend",
  "message": "Checkout successful",
  "order_data": {
    "service": "orders",
    "order_id": 2418,
    "inventory_data": {
      "service": "inventory",
      "status": "reserved",
      "payment_data": {
        "service": "payments",
        "status": "success",
        "transaction_id": "txn_434599"
      }
    }
  }
}
```

---

### 8. Gymnasium Cluster Sanity Simulation Diagnostics

Run step-by-step trace simulation over Alibaba production trace logs:

```bash
python3 scripts/run_sanity_simulation.py --episodes 1
```

**Expected PPT Output (Step Diagnostics)**:
```text
============================================================================================
Episode 1  |  services=4  |  trace_steps=30
============================================================================================
step     actions   avg_reps   avg_cpu%   avg_mem%    tot_rps   avg_lat   max_lat   reward    SLO
--------------------------------------------------------------------------------------------
   1        DDDU       33.0       0.48       2.27      205.1      55.1     162.5   +0.285   FAIL
   2        DDDU       32.5       0.49       2.32      207.5      54.1     156.5   +0.300   FAIL
   3        DDDU       32.0       0.51       2.39      206.6      53.8     154.0   +0.306   FAIL
   4        DDDU       31.5       0.51       2.47      206.3      54.1     153.5   +0.308   FAIL
   5        DDDU       31.0       0.53       2.57      207.5      53.8     149.8   +0.317   FAIL
   8        DDDU       29.5       0.62       3.23      208.9      55.0     140.2   +0.341   FAIL
  10        DDDU       28.8       0.75       4.23      212.8      59.6     143.5   +0.358   FAIL
  15        DDDU       27.5       0.83       4.54      213.9      56.8     128.8   +0.395   FAIL
  30        DDDU       22.8       1.29       6.50      217.9      57.8     117.4   +0.000   FAIL
--------------------------------------------------------------------------------------------
Summary: 30 steps  |  total_reward=+11.123  |  SLO violations=30/30 (100.0%)
```

---

### 9. Pytest Automated Test Suite

Run all unit and integration test suites:

```bash
pytest -q
```

**Expected PPT Output**:
```text
138 passed in 14.03s
```

---

### 10. Saved Image Artifacts in Workspace

Direct image files available in the project root to copy/paste directly into your PPT:
* `grafana_dashboard_output.png` — Real-time Grafana 6-panel dashboard with CPU, memory, RPS, latency, and replica curves under load.
* `prometheus_graph_output.png` — Prometheus Web UI PromQL request rate curve across services.

---

## ⚡ "Run Everything" Verification Flow

Execute this sequence from a fresh terminal to verify all system components end-to-end:

### Terminal 1 (Main Execution)
```bash
# 1. Navigate and activate virtual environment
cd ~/flexascale
source .venv/bin/activate

# 2. Run full pytest test suite (138 tests across all 10 test modules)
pytest -v

# 3. Validate dual SIM/LIVE schema contract match
python3 scripts/validate_schema.py

# 4. Run sanity cluster simulation (offline Alibaba trace)
python3 scripts/run_sanity_simulation.py --episodes 2

# 5. Run Phase 4 Safety & HPA fallback verification demo against Minikube
python3 scripts/run_safety_controller.py --live --demo

# 6. Run Autonomous Kubernetes Operator demo (standard demo fleet)
python3 scripts/run_operator.py --demo

# 7. Run Autonomous Operator on arbitrary custom application (zero-code demo)
python3 scripts/run_operator.py --demo --custom-app

# 8. Launch FastAPI Server & React Dashboard (Port 8080)
python3 scripts/run_api.py --port 8080 &

# 9. Run Locust multi-scenario load testing (lunch_spike, quiet_night, burst)
python3 scripts/run_locust_scenarios.py --scenario all --mock

# 10. Execute FlexaScale vs. Standard HPA benchmark comparison
python3 scripts/run_hpa_vs_rl_benchmark.py --episodes 3

# 11. Run Full Closed-Loop Controller demonstration (standard demo fleet)
python3 scripts/run_closed_loop.py --demo

# 12. Run Full Closed-Loop Controller on custom microservices (zero-code demo)
python3 scripts/run_closed_loop.py --demo --custom-app

# 13. Validate Reusable Helm Chart packaging
helm lint helm/flexascale
helm template flexascale helm/flexascale --set targetNamespace=production
```

### Terminal 2 (Prometheus Port-Forward)
```bash
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n flexascale-monitoring 9090:9090
```

### Terminal 3 (Grafana Port-Forward)
```bash
kubectl port-forward svc/monitoring-grafana -n flexascale-monitoring 3000:80
```

### Terminal 4 (FlexaScale Live Dashboard & API)
```bash
# Dashboard UI: http://localhost:8080
# OpenAPI Docs: http://localhost:8080/docs
python3 scripts/run_api.py --live --port 8080
```

---

## ✅ Verification Checklist

- [x] Python virtual environment configured (`.venv`)
- [x] Dependencies installed and `flexascale` editable package verified
- [x] All 296 pytest tests pass with 0 failures (re-verified 2026-10-26 20:55; 138 at the time this checklist was first written)
- [x] Minikube cluster and namespaces (`flexascale-apps`, `flexascale-monitoring`) operational
- [x] Helm repositories added (`prometheus-community`, `grafana`, `bitnami`)
- [x] Microservice container images built (`frontend`, `orders`, `inventory`, `payments`)
- [x] Microservices deployed and chain execution verified (`/api/checkout`)
- [x] Prometheus stack deployed and scraping microservices at 5-second interval
- [x] Grafana dashboard deployed with valid PromQL panels for CPU, Mem, RPS, Latency, Error Rate, Replicas
- [x] Alibaba trace pipeline builds and validates `alibaba_service_state.csv`
- [x] Extended 5-category state schema implemented with raw vs derived metrics
- [x] Dual SIM and LIVE schema contract validated
- [x] Gymnasium multi-service cluster environment (`FlexaScaleEnv`) operational
- [x] PyTorch Geometric GNN dependency encoder passes gradient and convolution tests
- [x] Stable-Baselines3 PPO agent trains cleanly with GNN extractor
- [x] Confidence proxy and safety fallback evaluate against heuristic baseline
- [x] Phase 4 Mutual-exclusion lock (`ScalingLockManager`) with lease TTL and K8s ConfigMap sync
- [x] Native Kubernetes HPAs deployed (`deploy/kubernetes/hpa.yaml`) across all 16 microservices
- [x] Conflict-free HPA freezing (`min=N, max=N`) during RL ownership verified live
- [x] Automatic fail-safe fallback to dynamic HPA on low confidence, invalid inputs, or crash/lease expiry
- [x] Hysteresis and cooldown logic verified to prevent controller thrashing
- [x] **Phase 3**: Dynamic dependency graph inference with online EMA decay implemented and tested (`test_graph_inference.py`)
- [x] **Phase 3**: Live state builder with multi-service observation schema project implemented and tested (`test_live_builder.py`)
- [x] **Phase 4**: Autonomous Kubernetes operator control loop implemented and tested (`test_operator.py`, `run_operator.py`)
- [x] **Phase 5**: High-performance FastAPI backend with `/api/status`, `/api/metrics`, `/api/history`, `/api/decisions`, `/api/graph`, `/api/config`, `/api/fallback` (`test_api.py`)
- [x] **Phase 5**: Modern dark-mode React glassmorphic web dashboard with live SVG telemetry charts, call graph, and SLO tuning panel (`http://localhost:8080`)
- [x] **Phase 6**: Full closed-loop end-to-end autonomous controller wired (`run_closed_loop.py`)
- [x] **Phase 6**: Realistic Locust load scenarios implemented: `lunch_spike`, `quiet_night`, `burst` (`run_locust_scenarios.py`)
- [x] **Phase 6**: FlexaScale vs Standard Kubernetes HPA benchmark runner with automated report generation (`reports/benchmark_report.md`, `reports/benchmark_summary.json`)
- [x] **Application-Agnostic Core**: Dynamic workload discovery (`ServiceDiscovery`) via Kubernetes API and Prometheus (`test_discovery.py`)
- [x] **Application-Agnostic GNN** *(corrected 2026-10-22)*: the GNN encoder accepts any node count, but its `node_policy_head` is **not trained by PPO** and is no longer used for decisions. Arbitrary service counts are now handled by applying the trained PPO policy on dependency-graph neighbourhood windows (`flexascale.rl.policy_runtime`, `tests/test_policy_and_operator.py`)
- [x] **Application-Agnostic Telemetry** *(corrected)*: cAdvisor + kube-state-metrics telemetry, CPU as % of request (HPA semantics). The former network-I/O "request rate" and CPU-derived "latency" fallbacks fabricated values and were removed: missing metrics are now reported as missing
- [x] **Reusable Production Helm Chart**: Package installable via `helm install` into any Kubernetes cluster where the `flexascale` image is available, configurable via `values.yaml` (`helm lint helm/flexascale`). The images are built locally, not published to a registry, so on a new cluster build and load them first (section U, step 3). Verified in-cluster on 2026-10-26: install, upgrade to live, rollback and uninstall (`logs/helm_verify.out`)
- [x] **Phase 7 — Shopping Microservices Discovery**: Discovered all seven backend services (`api-gateway`, `user-service`, `catalog-service`, `cart-service`, `order-service`, `inventory-service`, `payment-service`) with non-scalable services (`postgres`, `shopping-frontend`) cleanly filtered
- [x] **Phase 7 — Live State Observation Schema**: Prometheus client collects CPU, Memory, Replicas, RPS, and Latency for all 7 services, building exact 35-dimensional float32 observation vectors (`scripts/validate_schema.py`)
- [x] **Phase 7 — Missing Telemetry Exposure**: Telemetry status and missing-data flags explicitly tracked in `ServiceState` without silent zero masking
- [ ] ~~**Phase 7 — GNN Node Policy Inference**~~ *(withdrawn)*: `predict_node_actions` produced actions from untrained weights. Replaced by trained-weight neighbourhood inference (see section V)
- [x] **Phase 7 — Live Mutual-Exclusion Safety**: Lease lock ConfigMap (`flexascale-safety-lock`) and HPA freezing (`min=N, max=N`) verified live on Minikube
- [x] **Phase 7 — Closed-Loop Control**: Prometheus metrics → Live State Builder → GNN Inference → Safety Controller → Replica Scaling / HPA Fallback verified live (`scripts/run_closed_loop.py --live`)
- [x] **Phase 7 — Locust Shopping Traffic**: Realistic multi-user load generated across catalog browsing, customer checkout saga, payment delay, and flash-sale contention
- [x] **Phase 7 — Empirical Benchmark** *(superseded)*: the 60 s run in `reports/shopping_benchmark_report.md` used the untrained node head and the fraction-unit model; its FlexaScale numbers do not reflect a trained policy. Current live results: `reports/live_benchmark_report.md`

---

## U. Installing FlexaScale on any Kubernetes application

FlexaScale needs no change to the application's code. It reads Deployments and HPAs from the Kubernetes API and telemetry from Prometheus (cAdvisor + kube-state-metrics; `http_requests_total` / `http_request_duration_seconds` are optional and add request-rate and latency features).

1. **Prerequisites:** Kubernetes ≥ 1.27, Prometheus scraping cAdvisor and kube-state-metrics (e.g. kube-prometheus-stack), Helm 3, and CPU/memory requests set on the target Deployments (CPU utilisation is measured against the request, as HPA does).
2. **Metrics available?** `kubectl -n <ns> top pods` and, in Prometheus, `container_cpu_usage_seconds_total{namespace="<ns>"}` and `kube_deployment_spec_replicas{namespace="<ns>"}`.
3. **Build and load the operator image** (Minikube shown; ≈1.4 GB, CPU-only PyTorch; image 0.6.0 contains the v5, v7 and v9 models):
   ```bash
   docker build -f deploy/flexascale/Dockerfile -t flexascale:0.6.0 .
   minikube -p flexascale image load flexascale:0.6.0
   ```
   Build with enough free memory (after a fresh start, with no experiment running). On the second laptop a build inside the Minikube node, run while the host was out of memory and still copying the 7.4 GB Alibaba trace into the image (fixed in `.dockerignore`), restarted the node's control plane and every pod (`docs/POLICY_V9.md` §8, 2026-10-30 02:44). The v9 graph policy for the shop is selected with `-f helm/flexascale/values-v9.yaml`.
4. **Install in observation mode** (the default: no cluster changes, read-only RBAC):
   ```bash
   helm upgrade --install flexascale helm/flexascale -n flexascale-system --create-namespace \
     --set policy.name=myapp --set policy.namespace=<app-namespace> \
     --set policy.label_selector='app.kubernetes.io/part-of=myapp' \
     --set policy.prometheus_url=http://<prometheus-svc>.<ns>.svc:9090
   ```
   The same schema can be used locally: `python scripts/run_operator.py --policy config/apps/<app>.yaml --validate-only`.
5. **Select the target application:** `policy.include` / `policy.exclude` / `policy.label_selector`. Datastore images (postgres, redis, …), FlexaScale itself and monitoring are skipped automatically. Nothing outside `policy.namespace` is ever touched.
6. **Validate discovered services and metrics:** `kubectl -n flexascale-system logs deploy/flexascale-operator | head`.
7. **Inspect proposed decisions:** `kubectl -n flexascale-system exec deploy/flexascale-operator -- tail /var/log/flexascale/decisions.jsonl` (`proposed_replicas`, `policy.confidence`, `safety_reasons`, `applied: false`).
8. **Enable live control explicitly:** `helm upgrade flexascale helm/flexascale -n flexascale-system --reuse-values --set policy.mode=live`. This also adds the write permissions to the Role.
9. **Observe scaling:** `kubectl -n <ns> get hpa,deploy -w`. Frozen HPAs carry `flexascale.io/frozen-by` and the original bounds as annotations. The Lease is `flexascale-<name>`.
10. **Restore HPA / disable FlexaScale:** `--set policy.mode=observe` (the operator restores every frozen HPA on shutdown).
11. **Uninstall:** `helm uninstall flexascale -n flexascale-system`. The application, its HPAs (restored) and its data are not removed. Check with `python -m flexascale.lab.procctl ownership`.

Upgrades and rollbacks use `helm upgrade` / `helm rollback`. The operator uses the `Recreate` strategy, so an old and a new operator never run together, and the Lease would refuse a second controller anyway. Before every upgrade, rollback and uninstall, a hook Job (chart 0.4.1, `operator.handbackHook`) scales the operator to 0 and waits, so a live operator restores the frozen HPAs and releases the Lease while it still has its write permissions. Without it, Helm changed the Role at the same moment and the HPAs stayed frozen (found in the in-cluster test, `reports/final_readiness_report.md` defect 19). If a controller ever dies without handing back, `python -m flexascale.lab.procctl safe-state` restores every frozen HPA.

The whole lifecycle is scripted on the second application: `bash scripts/helm_lifecycle_test.sh 2>&1 | tee logs/helm_lifecycle_0.6.0.out`. It installs in observe mode, upgrades to live with the v9 model, rolls back and uninstalls. After every step it checks HPA bounds and markers, the Lease and the RBAC, and it ends with a pass/fail count.

Second application used to verify portability: `examples/bookstore/` (5 services, different names, sizes, topology and HPA naming; 3 of 5 services have an HPA). Deploy with:
```bash
docker build -t bookstore-svc:1.0 examples/bookstore && minikube -p flexascale image load bookstore-svc:1.0
kubectl apply -f examples/bookstore/k8s.yaml
python scripts/run_operator.py --policy config/apps/bookstore.yaml --prometheus-url http://localhost:9090 --max-steps 1 --decision-log /tmp/bookstore.jsonl
```

## V. Live Autoscaling Lab and reproducible evaluation

* Dashboard server: `python scripts/run_lab.py` (127.0.0.1:8090, same-origin API only). Configuration: `config/lab.yaml` (apps, Prometheus URL, results directory, end-to-end p95 SLO).
* Each experiment: preflight → comparable reset (HPAs held at their minimum, Deployments scaled to minimum, HPAs restored, settle check) → controller setup (HPA: lease free and nothing frozen; FlexaScale: operator in live mode with the lease) → Locust scenario (`load-testing/scenarios.py`) → 5 s sampling → teardown (stop Locust and operator, restore HPAs, verify ownership) → `reports/experiments/<run>/run.json`, `telemetry.csv`, `decisions.jsonl`, `locust_*.csv`.
* Batch of comparable runs through the same API: `python scripts/run_lab_experiments.py --scenarios flash_sale,steady_browsing --users 25 --duration 300`, or a repeated six-scenario batch with `./scripts/run_live_batch.sh <repeats> <log>` (`FLEXASCALE_CONTROLLERS=hpa,auto` or `hpa,hpa_fast` to choose the arms). Each run takes about 11–17 min including the settle wait. On a laptop, prevent suspend for the whole batch: `systemd-inhibit --what=sleep:idle:handle-lid-switch <command>`.
* Deployments without an HPA: before FlexaScale first scales one, it records the count in the `flexascale.io/original-replicas` annotation, and it restores that count on shutdown.
* Host conditions after a batch: `python scripts/check_host_load.py` → `reports/host_load_by_run.csv`. For each run it reports the host CPU used outside the Kubernetes containers during the load window (Prometheus) and any time on battery (upower history). Runs on battery or with more than 2.0 cores of outside load are host-affected (`docs/POLICY_V6.md` §5.2); move such pairs to `reports/experiments_invalid/` with the reason, and rerun them. Live benchmarks need AC power and no other heavy jobs on the laptop.
* Aggregate report: `python scripts/build_live_report.py` → `reports/live_benchmark_report.md`
* Cost: `cost` block of the app policy. With no prices it reports a unitless resource-cost proxy (vCPU-h + 0.125 × GiB-h of *requested* resources). With prices it reports an estimate. It never reports a bill.
* Policy inference: the trained model has a fixed 4-service input. For N ≠ 4 services each service is evaluated in a 4-node window (itself + nearest neighbours in the dependency graph, padded with idle nodes) with the same trained weights (`ppo_neighborhood` in the decision log).

## W. Retraining and evaluating the policy

**Current policy (v5):** `systemd-inhibit --what=sleep:idle:handle-lid-switch ./scripts/train_v5.sh` (HPA-imitation warm start + PPO fine-tuning, 4-run grid, 500k steps each, ~20 min on 16 cores), then `python scripts/evaluate_v5.py` (selection on validation services → `models/flexascale_v5/best_model`, then one test run → `reports/simulation_evaluation_v5.md`). See `docs/POLICY_V5.md`.

**Previous policy (v4):** `./scripts/train_v4.sh` (4-run grid, 1M steps each, ~25 min on 16 cores; run it under `systemd-inhibit` on a laptop, a suspend stalls it) and then `python scripts/evaluate_v4.py` (selection on validation services → `models/flexascale_v4/best_model`, then one test run → `reports/simulation_evaluation_v4.md`). See `docs/POLICY_V4.md`.

Previous policy (v3, original simulator):

```bash
# ~20 min on 16 CPU cores. Writes models/<dir>/best_model, checkpoints, eval_logs, model_card.json
python -m flexascale.rl.train --timesteps 150000 --service-sampling random --demand-model normalized \
  --max-replicas 10 --randomize-initial-replicas --cost-weight 0.5 --n-steps 512 --batch-size 64 \
  --seed 42 --save-dir models/flexascale_v3
python scripts/evaluate_policies.py --episodes 200      # held-out test split -> reports/simulation_evaluation.md
python scripts/data_quality_report.py                   # -> reports/data_quality_report.md
```
Checkpoint selection uses the validation split; the test split is only used by `evaluate_policies.py`.

## X. FlexaScale v7: fair HPA baseline, application twin, graph policy (docs/POLICY_V7.md)

Result: on par with a fairly tuned native HPA (`docs/V7_REPORT.md`).

All steps are scripted and write their results to `reports/v7/`. The rules each step applies (calibration, selection, verdict) were fixed in `docs/POLICY_V7.md` before the step ran.

```bash
# 1. Twin: fit the application model to the live runs, then check it against live native HPA
python scripts/fit_twin.py                        # -> config/twin/shopping.json
python scripts/analysis/validate_twin.py          # twin vs live replica-hours / p95 per scenario
python scripts/analysis/twin_headroom.py          # what HPA settings and simple rules can reach

# 2. Train and select the v7 graph policy on the twin (~45 min per run on AC; live runs freeze it in their load windows)
nohup nice -n 5 python -u scripts/train_v7.py >> logs/train_v7.out 2>&1 &     # 4 runs, then selection and the twin test sets
#    or select as soon as the two main runs are done, and train the ablations later (the test sets then run once, after them):
python -u scripts/train_v7.py --runs focal_bc_s1,focal_bc_s2 --select-only    # -> reports/v7/training_v7.json "selected"

# 3. Calibrate HPA-tuned on the separate calibration workload (8 live runs + one rerun per invalid run, ~2 h, needs AC power)
python scripts/v7_plan.py calibration             # -> reports/v7/calibration_plan.json (order: seed 7)
nohup ./scripts/v7_calibrate.sh >> logs/v7_calibration.out 2>&1 &   # plan, host-load check, reruns, rule -> reports/v7/calibration.md

# 4. Promote the selected model/rule, write the policies and the five evaluation arms
python scripts/promote_v7.py                      # models/flexascale_v7/best_model, config/apps/shopping_v7*.yaml, reports/v7/arms.json
python scripts/v7_plan.py evaluation --arms reports/v7/arms.json   # 12 blocks x 5 arms, order seed 2610+block
./scripts/stop_review.sh && ./scripts/start_review.sh             # reload config/lab.yaml (variants, hpa_tuned)

# 5. Live evaluation (~11 h) and the pre-registered verdict
nohup ./scripts/v7_evaluate.sh >> logs/v7_evaluation.out 2>&1 &    # plan, host-load check, reruns, verdict -> reports/v7/evaluation.md

# 6. Clock-controlled replication (POLICY_V7 §3.7; 12 blocks x 4 arms, ~11 h). Live comparisons on a laptop need the
#    `performance` power profile: under `balanced` the application runs faster when the host is busier (V7_REPORT §4.1).
python scripts/v7_plan.py replication --arms reports/v7/arms.json
nohup ./scripts/v7_replicate.sh >> logs/v7_replication.out 2>&1 &  # sets `performance`; plan, reruns, verdict -> reports/v7/replication.md
busctl call org.freedesktop.UPower.PowerProfiles /org/freedesktop/UPower/PowerProfiles org.freedesktop.DBus.Properties \
  Set ssv org.freedesktop.UPower.PowerProfiles ActiveProfile s balanced    # afterwards: back to the normal profile
```

* **New lab controller `hpa_tuned`:** it sets every HPA's CPU target (`hpa_cpu_target_pct`) and scale-down window (`hpa_scale_down_window_s`) for one run, and stores the originals on the HPA (`flexascale.io/original-metrics`, `flexascale.io/original-behavior`). Teardown restores them, and so does `procctl safe-state` after a crash. Auto and FlexaScale runs may pass the same two fields to choose the native HPA that takes over on hand-back.
* **Policy variants:** `config/lab.yaml` → `apps.<app>.variants` maps a name to another policy file (e.g. `v7`, `v7_rule`). Pass it as `policy_variant` in the API, or pick it in the dashboard's "FlexaScale policy" selector.
* **Rule arm:** a policy with `controller_rule: {type: limit_target, target: t, down: d}` makes the operator use that hand-written rule instead of a model, under the same guards. It separates the learned policy's contribution from the operator's (POLICY_V7 §3.2).
* **After a reboot or a dead battery:** `./scripts/v7_resume.sh` brings the environment back (`start_review.sh`) and resumes whatever is unfinished: the calibration (`v7_calibrate.sh`), the evaluation once promoted (`v7_evaluate.sh`), and training until a model is selected. Plans resume from their progress files; training runs already recorded in `reports/v7/training_v7.json` are skipped. Live runs need AC power; training pauses below 35% battery.
* **Invalid runs (POLICY_V7 §3.4):** `scripts/rerun_plan.py <plan>` reads the host-load flags of `scripts/check_host_load.py`, moves each invalid run (host-affected, incomplete, not settled) to `reports/experiments_invalid/` and writes `<plan>.reruns.json`, which is run once. Reruns are never rerun. `v7_calibrate.sh` and `v7_evaluate.sh` do this automatically.
* **CPU-heavy work next to live runs:** `python scripts/lab_quiet.py -- <command>` (e.g. `-- python -m pytest -q`) runs the command in its own process group and keeps it stopped during every lab load window, so it cannot make a run host-affected (more than 2.0 cores outside Kubernetes).
* **Plan runner (`scripts/run_plan.py`):** runs one at a time, resumable through `<plan>.progress.json`. It waits while the laptop is on battery or while `.runtime/pause_live_runs` exists. With `--suspend <pattern>` it freezes matching processes (e.g. training) during each run's settle and load window.
