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
14. [Run Everything Verification Flow](#-run-everything-verification-flow)
15. [Verification Checklist](#-verification-checklist)

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

# Run full pytest test suite
pytest -v
```

Expected output: All 90 test cases across `test_package.py`, `test_schema.py`, `test_flexascale_env.py`, and `test_gnn_encoder.py` pass with `0` failures.

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

---

## H. Alibaba Trace Processing Pipeline

Process raw Alibaba cluster traces (`MSResource` and `MSRTQps`) into the unified service state dataset:

```bash
# Run dataset builder pipeline
python3 src/flexascale/data/build_dataset.py
```

Output:
- Saves merged, validated dataset to `data/processed/alibaba_service_state.csv` (~5.4 MB).
- Validates 500 sampled rows against the `ServiceState` schema.

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
python3 scripts/run_sanity_simulation.py --episodes 3 --seed 42
```

Expected output:
- Simulates 4 services across trace timestamps.
- Evaluates heuristic scaling decisions (Scale UP on high CPU, Scale DOWN on low CPU, MAINTAIN otherwise).
- Reports per-step actions, replica counts, CPU%, Mem%, RPS, Latency, composite rewards, and SLO compliance.

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

Train the PPO actor-critic agent integrated with the GNN dependency feature extractor:

```bash
# Train PPO agent with GNN encoder for 5,000 steps
python3 src/flexascale/rl/train.py --timesteps 5000 --extractor gnn --conv-type gcn --hidden-dim 64
```

Output:
- Checkpoints saved in `models/checkpoints/`
- Best evaluation model saved in `models/best_model/`
- Final trained model saved to `models/ppo_flexascale_final.zip`
- Tensorboard telemetry written to `logs/tb/`

---

## M. Training Loop & Baseline Comparison

Evaluate the trained PPO agent with confidence-proxy safety fallback against the standard Kubernetes HPA heuristic baseline:

```bash
python3 scripts/evaluate_baseline_vs_rl.py --episodes 5 --threshold 0.8
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

## ⚡ "Run Everything" Verification Flow

Execute this sequence from a fresh terminal to verify all system components end-to-end:

### Terminal 1 (Main Execution)
```bash
# 1. Navigate and activate environment
cd ~/flexascale
source .venv/bin/activate

# 2. Run unit and integration tests
pytest -v

# 3. Validate dual SIM/LIVE schema match
python3 scripts/validate_schema.py

# 4. Run sanity cluster simulation
python3 scripts/run_sanity_simulation.py --episodes 2

# 5. Train PPO agent with GNN encoder
python3 src/flexascale/rl/train.py --timesteps 2000 --extractor gnn

# 6. Evaluate baseline vs RL with confidence proxy
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
- [x] All 90 pytest tests pass with 0 failures
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
