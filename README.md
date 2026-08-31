# FlexaScale

**Reinforcement Learning-Based Intelligent Auto-Scaling Framework for Distributed Microservices on Kubernetes**

FlexaScale is an adaptive, proactive, and dependency-aware autoscaling framework designed to overcome the limitations of reactive threshold-based autoscalers (such as traditional Kubernetes HPA). By combining Graph Neural Networks (GNNs) for inter-service dependency representation and Proximal Policy Optimization (PPO) reinforcement learning, FlexaScale performs multi-objective optimization across latency, resource utilization, cloud infrastructure cost, and SLO compliance.

---

## 🏗️ Architecture Pipeline

```
Prometheus Live Metrics + Historical Workload
                     │
                     ▼
          Dependency State Builder (Call Graph)
                     │
                     ▼
           Graph Neural Network (GNN)
                     │
                     ▼
              PPO Policy Agent
                     │
                     ▼
          Safety Layer & HPA Fallback
                     │
                     ▼
            Kubernetes Cluster (Pods/Deployments)
```

---

## 👥 Project Team & Responsibilities

| Name | Role / Subtask Focus |
|---|---|
| **G O Ashwin Praveen** | Repo + Tooling Setup, Python Dependencies, Core Scaffolding |
| **Dattanand U D** | Minikube Cluster Architecture, Helm Setup, Cluster Automation Scripts |
| **Ghanshyam S Sunil** | Demo Microservices (`frontend` → `orders` → `inventory` → `payments`) |
| **Atmakrishna K Raghavan** | Prometheus & Grafana Monitoring Stack, Metric Scraping Configuration |

**Faculty Guide**: Lakshmi Mohan (Dept. of Computer Science & Engineering, Amrita Vishwa Vidyapeetham)

---

## 🚀 Quickstart & Setup

### 1. Python Environment Setup
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### 2. Kubernetes Cluster Setup (Minikube + Helm)

Ensure Docker Desktop is running, then execute the automated setup script:

```powershell
.\scripts\setup_cluster.ps1
```

This script automatically:
1. Verifies Docker, Minikube, kubectl, and Helm.
2. Creates and starts the Minikube cluster under the dedicated profile `flexascale` (4 CPUs, 6GB RAM).
3. Enables core addons: `metrics-server`, `ingress`, and `dashboard`.
4. Provisions project namespaces:
   - `flexascale-apps`: For the demo microservices application.
   - `flexascale-monitoring`: For Prometheus and Grafana.
5. Adds and updates standard Helm repositories (`prometheus-community`, `grafana`, `bitnami`).

### 3. Verify Cluster Health
```powershell
.\scripts\verify_cluster.ps1
```

### 4. Teardown / Stop Cluster
```powershell
# To temporarily stop the cluster
.\scripts\teardown_cluster.ps1

# To delete the cluster profile completely
.\scripts\teardown_cluster.ps1 -Delete
```

---

## 📊 Datasets & Evaluation

- **Alibaba Cluster Trace Dataset**: Large-scale production trace data for simulating dynamic cloud workloads and offline RL policy training.
- **Online Synthetic Microservices**: Live microservice chain running on Kubernetes for real-time validation and comparison against standard HPA.

---

## 🧪 Testing

Run test suite:
```powershell
pytest
```
