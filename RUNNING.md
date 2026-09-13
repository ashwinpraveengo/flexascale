# FlexaScale — End-to-End Execution & Verification Guide

This guide provides the complete, authoritative run instructions to set up, deploy, simulate, monitor, and train the FlexaScale RL-based intelligent auto-scaling framework from a fresh terminal.

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
15. [Output Commands (Review PPT & Defense)](#output-commands)
16. [Run Everything Verification Flow](#-run-everything-verification-flow)
17. [Verification Checklist](#-verification-checklist)

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

# Run full pytest test suite (101 tests across all modules)
pytest -v
```

Expected output: All 101 test cases across `test_package.py`, `test_schema.py`, `test_flexascale_env.py`, `test_gnn_encoder.py`, and `test_safety.py` pass with `0` failures.

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

## E. Deploy & Test Demo Microservices

The demo application implements a 4-tier microservice dependency chain:
$$\text{Frontend Gateway} \longrightarrow \text{Orders Service} \longrightarrow \text{Inventory Service} \longrightarrow \text{Payments Service}$$

### 1. Build & Deploy Microservices

```bash
# Point shell to Minikube's Docker daemon (if using Minikube docker driver)
eval $(minikube docker-env -p flexascale)

# Build container images
docker build -t frontend:latest ./frontend
docker build -t orders:latest ./orders
docker build -t inventory:latest ./inventory
docker build -t payments:latest ./payments

# Deploy microservices to flexascale-apps namespace
kubectl apply -f k8s/frontend.yaml -n flexascale-apps
kubectl apply -f k8s/orders.yaml -n flexascale-apps
kubectl apply -f k8s/inventory.yaml -n flexascale-apps
kubectl apply -f k8s/payments.yaml -n flexascale-apps

# Verify all pods are Running
kubectl get pods -n flexascale-apps -o wide
kubectl get svc -n flexascale-apps
```

### 2. Send End-to-End Test Request Through the Service Chain

```bash
# Terminal 1: Port-forward Frontend gateway
kubectl port-forward svc/frontend -n flexascale-apps 8000:8000

# Terminal 2: Send test checkout request
curl -X POST http://localhost:8000/api/checkout
```

Expected response:
```json
{
  "service": "frontend",
  "message": "Checkout successful",
  "order_data": {
    "service": "orders",
    "order_id": 4821,
    "inventory_data": {
      "service": "inventory",
      "status": "reserved",
      "payment_data": {
        "service": "payments",
        "status": "success",
        "transaction_id": "txn_839210"
      }
    }
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
kubectl apply -f k8s/grafana-dashboard-configmap.yaml

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
kubectl apply -f k8s/hpa.yaml

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

### 6. Emergency Cluster Fallback to HPA

To immediately release all scaling locks and return all services to native HPA control:

```bash
python3 -c "from flexascale.safety import SafetyCoordinator; c = SafetyCoordinator(live=True); c.fallback_all_to_hpa('manual_reset')"
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
locust -f locust/locustfile.py --headless -u 30 -r 6 --run-time 45s --host http://localhost:8000
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
python3 scripts/evaluate_baseline_vs_rl.py --split test --episodes 3 --threshold 0.8
```

**Expected PPT Output (Comparison Table)**:
```text
================================================================================
EVALUATION COMPARISON: BASELINE (HPA Heuristic) vs RL (PPO + Confidence Proxy)
================================================================================
Metric                    | Baseline (Heuristic)      | RL + Proxy               
--------------------------------------------------------------------------------
Avg Total Reward          | 1.193                     | 1.193                    
SLO Violation Rate        | 100.00%                   | 100.00%                  
Avg Fallbacks (per ep)    | N/A                       | 20.0                     
================================================================================
```

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
101 passed, 191 warnings in 5.05s
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

# 2. Run full pytest test suite (101 tests across all modules)
pytest -v

# 3. Run dedicated Phase 4 safety tests
pytest tests/test_safety.py -v

# 4. Validate dual SIM/LIVE schema contract match
python3 scripts/validate_schema.py

# 5. Run sanity cluster simulation (offline Alibaba trace)
python3 scripts/run_sanity_simulation.py --episodes 2

# 6. Apply native Kubernetes HPAs
kubectl apply -f k8s/hpa.yaml

# 7. Run Phase 4 Safety & HPA fallback verification demo against Minikube
python3 scripts/run_safety_controller.py --live --demo

# 8. Inspect cluster safety lock ConfigMap
kubectl get configmap -n flexascale-apps flexascale-safety-lock -o yaml

# 9. Train PPO agent with GNN encoder
python3 src/flexascale/rl/train.py --timesteps 2000 --extractor gnn

# 10. Evaluate baseline vs RL with confidence proxy
python3 scripts/evaluate_baseline_vs_rl.py --episodes 2
```

### Terminal 2 (Prometheus Port-Forward)
```bash
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n flexascale-monitoring 9090:9090
```

### Terminal 3 (Grafana Port-Forward)
```bash
kubectl port-forward svc/monitoring-grafana -n flexascale-monitoring 3000:80
```

---

## ✅ Verification Checklist

- [x] Python virtual environment configured (`.venv`)
- [x] Dependencies installed and `flexascale` editable package verified
- [x] All 101 pytest tests pass with 0 failures across all 5 test suites
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
- [x] Native Kubernetes HPAs deployed (`k8s/hpa.yaml`) across all 4 microservices
- [x] Conflict-free HPA freezing (`min=N, max=N`) during RL ownership verified live
- [x] Automatic fail-safe fallback to dynamic HPA on low confidence, invalid inputs, or crash/lease expiry
- [x] Hysteresis and cooldown logic verified to prevent controller thrashing
