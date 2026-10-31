# FlexaScale — The Project Explained from Zero

*A textbook for one reader: you. It assumes you know nothing about the project, Kubernetes or reinforcement learning,
and it ends with you able to explain every component, file, formula and result of FlexaScale.*

**How this document was written.** Every statement about FlexaScale was checked against the source code, the
configuration files, the trained models' cards, the raw experiment files and the reports in this repository (October
2026, commit `d8416a2` plus the files added since). File paths are given so you can open the code yourself.
Four labels are used throughout:

| Label | Meaning |
|---|---|
| **Implemented** | In the code and used by the running system |
| **Verified live** | Implemented *and* shown working on the real Kubernetes cluster, with the evidence named |
| **Experimental / historical** | In the repository but not used by the final system (kept for reproducibility) |
| **Planned / not done** | Proposed in the design phase or future work; not in the code |

The companion document, `docs/learning/FLEXASCALE_COMPLETE_VIVA_GUIDE.md`, goes deeper on every metric and every
number in the results, gives code walkthroughs line by line, and contains the viva questions. Read this document first.

---

## Contents

1. [Introduction: the problem and the idea](#1-introduction-the-problem-and-the-idea)
2. [Fundamental concepts](#2-fundamental-concepts)
3. [The complete architecture](#3-the-complete-architecture)
4. [Folders and source files](#4-folders-and-source-files)
5. [The Alibaba dataset](#5-the-alibaba-dataset)
6. [The metrics pipeline](#6-the-metrics-pipeline)
7. [Simulation](#7-simulation)
8. [The graph neural network in depth](#8-the-graph-neural-network-in-depth)
9. [PPO in depth](#9-ppo-in-depth)
10. [How the GNN and PPO work together](#10-how-the-gnn-and-ppo-work-together)
11. [Safety controller and Kubernetes execution](#11-safety-controller-and-kubernetes-execution)
12. [The three controller modes](#12-the-three-controller-modes)
13. [The sixteen microservices](#13-the-sixteen-microservices)
14. [Infrastructure: Prometheus, Grafana, Helm, Minikube, Docker, manifests](#14-infrastructure)
15. [Locust and the benchmarking method](#15-locust-and-the-benchmarking-method)
16. [The dashboard](#16-the-dashboard)
17. [End-to-end walkthrough of one decision](#17-end-to-end-walkthrough-of-one-decision)
18. [All important formulas and design decisions](#18-all-important-formulas-and-design-decisions)
19. [Results, contribution, limitations and future work](#19-results-contribution-limitations-and-future-work)
20. [Implementation status table](#20-implementation-status-table)

---

## 1. Introduction: the problem and the idea

### 1.1 The real-world problem

Imagine an online shop. During a flash sale, ten times more people arrive within seconds; at 3 a.m. almost nobody does.
The shop's software must be fast for everyone during the sale, yet it should not pay for idle computers at night.
Adding and removing computing capacity automatically, according to load, is called **autoscaling**.

Modern shops are not one big program. They are many small programs ("microservices"), each doing one job: the
catalogue, the cart, payments, inventory, and so on. They run on **Kubernetes**, which keeps a requested number of
copies ("replicas") of each program running. Kubernetes has a built-in autoscaler, the **Horizontal Pod Autoscaler
(HPA)**. For each service separately, every 15 seconds, it compares the service's average CPU use with a target and
sets the number of copies proportionally.

That rule has three weaknesses that this project set out to address:

1. **It looks at one service and one signal at a time.** It does not know that the order service calls the payment
   service, and it cannot see a service that is slow for a reason other than CPU (for example, waiting for a database).
2. **One fixed target suits no service perfectly.** A target that is right for one service wastes capacity on another.
3. **It is reactive and slow to release capacity.** It scales after CPU has risen, and by default it keeps extra
   copies for five minutes after load falls (its "scale-down stabilisation window").

### 1.2 The idea

FlexaScale replaces the per-service rule with a **learned policy** that looks at every service *and how the services
call each other*, then decides how many replicas each service should have. The policy is a **graph neural network**
(which reads the call graph) feeding a **Proximal Policy Optimization (PPO)** reinforcement-learning agent (which
chooses actions). Because a learned policy can be wrong, everything it proposes passes a **safety layer**, and the
native HPA always remains available as a fallback. An **Auto mode** chooses, for each service separately, whether
FlexaScale or the HPA should be in charge at any moment.

### 1.3 Objectives (as finally evaluated)

| No. | Objective | How it was checked |
|---|---|---|
| O1 | An autoscaling add-on for Kubernetes microservices that needs no application code change | Runs on the 16-service shop and on a separate 5-service bookstore through a policy file |
| O2 | A reinforcement-learning decision engine trained on simulated workloads and used on live metrics | Training reports, model cards, live decision logs (`ppo_graph`) |
| O3 | Dependency-aware decisions over the service call graph | Graph vs no-graph ablation on held-out simulated test sets |
| O4 | Safe operation: bounded actions, exclusive ownership, automatic fallback to HPA | Unit tests; live fault injection; cleanup checks after every run |
| O5 | A fair comparison with native HPA on latency, cost and SLO | Pre-registered paired live evaluation with 95% confidence intervals |
| O6 | Real-time monitoring and deployability | Dashboard, Grafana, Helm install/upgrade/rollback/uninstall test |

### 1.4 What came out, in one paragraph

FlexaScale works end to end on a real cluster, safely, and explains every decision. In a pre-registered evaluation it
used 7.3% (pure RL) and 7.7% (Auto) fewer replica-hours than the **default** HPA, with confidence intervals entirely
below zero, but its latency was not shown to be as good, so the formal verdict was "on par / inconclusive". Against a
**carefully tuned** HPA it was on par in two independent studies. The graph input showed no measurable benefit in an
ablation. These are honest results, and Section 19 explains exactly what they mean.

---

## 2. Fundamental concepts

Each concept is explained in plain words first, then how FlexaScale uses it.

### 2.1 Microservice

**Plain meaning.** A small program that does one job and talks to other small programs over the network, usually with
HTTP requests ("GET this product", "POST this order").

**Why it exists.** A single giant program (a *monolith*) must be scaled as a whole, and one slow part slows everything.
With microservices you can give more resources only to the part that is busy.

**In FlexaScale.** The test application is an online shop with 16 Python microservices (FastAPI), a React website and
a PostgreSQL database (`apps/services/`, Helm chart `charts/shopping-app`, version 1.1.0). Section 13 describes each.

### 2.2 Container and Docker

**Plain meaning.** A *container* packages a program with everything it needs (Python, libraries, files) so that it runs
the same way on any machine. *Docker* is the tool that builds container *images* (the package) and runs containers (a
running instance of an image).

**Analogy.** An image is a sealed lunch box recipe; a container is one lunch box made from it. Ten containers from one
image are ten identical lunch boxes.

**In FlexaScale.** Every shop service has a `Dockerfile` (`apps/services/<name>/Dockerfile`, base image
`python:3.11-slim`); `scripts/build_shop_images.sh` builds them inside Minikube's Docker daemon. The FlexaScale operator
has its own image, `flexascale:0.6.0` (`deploy/flexascale/Dockerfile`), with CPU-only PyTorch, `kubectl` and the trained
models.

### 2.3 Kubernetes, cluster, node

**Plain meaning.** Kubernetes is software that runs containers on a group of machines and keeps them running. A
*cluster* is that group of machines; each machine is a *node*. You declare what you want ("3 copies of the cart
service") and Kubernetes continuously makes reality match.

**In FlexaScale.** A single-node cluster created by **Minikube** (a tool that runs a small Kubernetes on a laptop),
profile name `flexascale`, Kubernetes v1.31.0. The shop lives in the *namespace* (a named folder inside the cluster)
`flexascale-apps`; monitoring lives in `flexascale-monitoring`; the in-cluster FlexaScale release in `flexascale-system`.

### 2.4 Pod

**Plain meaning.** The smallest thing Kubernetes runs: one or more containers that live and die together. In this
project each pod holds one service container.

**In FlexaScale.** A pod's name looks like `cart-service-6d567c9496-sd5t4`: deployment name, a hash, a random suffix.
FlexaScale uses exactly this pattern to know which service a CPU measurement belongs to (regular expression `POD_SUFFIX`
in `src/flexascale/metrics/workload_metrics.py`).

### 2.5 Deployment and replicas

**Plain meaning.** A *Deployment* is an instruction: "keep N identical pods of this program". N is the number of
**replicas**. If a pod dies, the Deployment creates another.

Two numbers matter everywhere in this project:

* **Desired replicas** (`spec.replicas`): how many pods Kubernetes has been *asked* for.
* **Ready replicas** (`status.readyReplicas`): how many are *actually started and passing their readiness check*.

After a scale-up from 1 to 2, desired becomes 2 immediately; ready becomes 2 only when the new pod is up. Measured on
this cluster: median 10 s, 90th percentile 15 s over 510 scale-ups (`src/flexascale/simulator/twin.py`, docstring).

### 2.6 Resource requests and limits

Every container declares two CPU numbers:

* **Request**: the CPU the scheduler *reserves* for it. Shop services request **100 millicores (0.1 CPU core)**.
* **Limit**: the most it may *use*. Shop services are limited to **500 millicores (0.5 core)**. Above that the
  container is *throttled* (slowed down by the operating system).

Memory has the same two numbers (shop services: request 128 MiB, limit 256 MiB; PostgreSQL 256/768 MiB).

**Why this matters later.** The HPA measures CPU *as a percentage of the request*. A pod using 0.35 cores is at
350% of its 0.1-core request but only 70% of its 0.5-core limit. This distinction explains a lot of the results.

### 2.7 Autoscaling and the HPA

**Autoscaling**: changing capacity automatically with load. **Horizontal** scaling changes the *number* of pods;
**vertical** scaling changes the *size* of each pod. FlexaScale does horizontal scaling only.

The **Horizontal Pod Autoscaler** computes, every sync period (15 s by default):

```
desired = ceil( current_replicas × current_CPU% / target_CPU% )
```

`ceil` rounds up. If the ratio is within ±10% of 1 (the *tolerance*), nothing changes. Scale-ups are limited per
period (at most double, or +4 pods), and scale-downs use the **highest** recommendation of the last 300 seconds (the
*stabilisation window*), so the HPA releases capacity slowly.

**Worked example.** Order service: 1 replica, CPU 86.8% of request, target 70%:
`ceil(1 × 86.8 / 70) = ceil(1.24) = 2`. This exact case appears in the verification run `20261031-035531` (the
"HPA recommendation 2" in the decision log for order-service at step 4).

In the shop every service has an HPA called `<service>-hpa` with bounds 1–10 and target 70% (`deploy/kubernetes/hpa.yaml`
and the shop chart). The HPA is FlexaScale's **baseline** (what it is compared with) and its **safety net** (what takes
over whenever FlexaScale is not in control).

### 2.8 Distributed systems ideas you need

* **Request path / call graph.** One user click can travel through several services: `api-gateway → order-service →
  payment-service`. Drawn with services as dots and calls as arrows, this is a **directed graph**.
* **Latency.** Time from sending a request to receiving the answer (milliseconds, ms).
* **Throughput.** Completed requests per second (req/s).
* **Tail latency (p95, p99).** The time below which 95% (99%) of requests finished. Users notice the slow tail, so
  autoscaling aims at percentiles, not averages.
* **SLO (service-level objective).** An internal target, here **end-to-end p95 ≤ 1000 ms**. The dashboard calls it
  "SLA" loosely; strictly an SLA is a contract built on SLOs.
* **Back-pressure.** When a downstream service is slow, callers wait and pile up, so slowness spreads upstream.
* **Shared bottleneck.** All 16 shop services use one PostgreSQL database; adding replicas of a service does not make the
  database faster.

### 2.9 Reinforcement learning (RL), intuitively

**Plain meaning.** A way for a computer to learn decisions by trial and error. An **agent** observes a situation, takes
an **action**, receives a **reward** (a score), and gradually learns which actions lead to higher total reward.

**Analogy.** Training a new shop manager by letting them run a simulated shop thousands of times. Each time they hire
too many cashiers they lose money; each time queues get long they lose customers. Over time they learn when to hire.

The words, defined once (used everywhere below):

| Term | Meaning | In FlexaScale |
|---|---|---|
| Environment | The world the agent acts in | A simulator of the shop (training); the real cluster (use) |
| State / observation | What the agent sees | 10 numbers per service, plus the call graph |
| Action | What the agent can do | Change a service's replicas by −1, 0, +1, +2 or +3 |
| Reward | The score after an action | A penalty for replicas, slow responses, SLO breaches, errors and churn |
| Policy | The decision rule | A neural network: observation → probability of each action |
| Episode | One complete simulated run | e.g. a 300-second flash sale |
| Step | One decision moment | Every 10 seconds |
| Return | Sum of future rewards (discounted) | What the agent tries to maximise |

### 2.10 Neural networks in one minute

A neural network is a function with many adjustable numbers (*weights*). A *linear layer* computes `y = W·x + b` (a
matrix times a vector plus a vector). A *non-linearity* such as **ReLU** (`max(0, x)`, "keep positives") or **tanh**
(squashes to −1…1) between layers lets the network represent curved relationships. *Training* adjusts the weights to
reduce a *loss* (an error measure) using gradients (the direction in which each weight should move). FlexaScale's
deployed network has **42,566 weights** (Section 8.7 shows the exact count).

### 2.11 Graph neural network (GNN), intuitively

A GNN is a neural network that works on a graph. Each node (service) starts with its own numbers; then, in rounds of
**message passing**, each node mixes in information from its neighbours. After two rounds, a service "knows" about its
neighbours and its neighbours' neighbours. Section 8 explains the exact implementation.

### 2.12 PPO, intuitively

**Proximal Policy Optimization** is a popular RL algorithm. It improves the policy in small, safe steps: it makes good
actions more likely and bad ones less likely, but refuses to change any action's probability by more than a set
fraction per update ("proximal" = stay close). It uses two networks: an **actor** (chooses actions) and a **critic**
(estimates how good a situation is). Section 9 gives the mathematics.

---

## 3. The complete architecture

### 3.1 The big picture

```
                         ┌────────────────── Kubernetes cluster (Minikube) ───────────────────┐
  Locust users ──HTTP──▶ │  Ingress → api-gateway → 15 other services → PostgreSQL             │
                         │  each service: /metrics (request counter + latency histogram)       │
                         │  each service: Deployment + HPA (1–10 replicas, 70% CPU target)     │
                         │  kubelet/cAdvisor: CPU and memory of every pod                      │
                         └──────────────┬──────────────────────────────────▲──────────────────┘
                                        │ scrape (cAdvisor 10 s,           │ scale sub-resource,
                                        │  services 15 s)                  │ HPA patches, Lease
                                        ▼                                  │
                                   Prometheus ──PromQL (1-min rates)──▶ FlexaScale operator (every 10 s)
                                        │                                  │  discovery → telemetry → features
                                        ▼                                  │  → call graph → GNN+PPO → Auto
                                     Grafana                               │  → safety guards → execution → log
                                                                           ▼
                                     FlexaScale lab server + React dashboard (http://127.0.0.1:8090)
```

### 3.2 The components and how they talk

| # | Component | Code | Talks to | How |
|---|---|---|---|---|
| 1 | Shop (16 services + DB + frontend) | `apps/`, `charts/shopping-app/` | Each other | HTTP (httpx) inside the cluster; SQL to PostgreSQL |
| 2 | Locust (load generator) | `load-testing/` | Shop | HTTP through the Minikube ingress |
| 3 | Prometheus | Helm release `monitoring` (kube-prometheus-stack 92.11.0) | cAdvisor, services | Pulls (*scrapes*) metrics: cAdvisor every 10 s, ServiceMonitors every 15 s, annotation job every 30 s (checked live on the Fedora laptop) |
| 4 | Grafana | same release | Prometheus | PromQL; dashboard in `observability/grafana/` |
| 5 | Workload discovery | `discovery/workloads.py` | Kubernetes API | `kubectl get deployments,hpa -o json` |
| 6 | Telemetry client | `metrics/workload_metrics.py` | Prometheus | HTTP `/api/v1/query` with batched PromQL |
| 7 | Feature tracker | `rl/features_v3.py` | — | Pure computation |
| 8 | Call graph | policy file `topology`, or `state/graph_inference.py` | Prometheus (only if inferring) | List of (caller, callee) edges |
| 9 | Policy runtime (GNN + PPO) | `rl/policy_runtime.py`, `rl/graph_policy.py` | — | PyTorch forward pass |
| 10 | Auto arbiter | `operator/auto_mode.py` | — | Pure computation |
| 11 | Safety guards | `operator/app_operator.py::_decide` | — | Pure computation |
| 12 | Execution | `safety/hpa_manager.py`, `safety/lease.py`, `safety/lock.py` | Kubernetes API | `kubectl patch hpa`, `kubectl scale`, `kubectl create/replace lease` |
| 13 | Decision log and status | `app_operator.py::_log/_write_status` | Disk | `decisions.jsonl`, `status.json` |
| 14 | Lab (experiment runner) | `lab/experiments.py` | All of the above | Starts Locust and the operator as processes, samples every 5 s |
| 15 | Lab server (API) | `lab/server.py` | Dashboard | FastAPI on 127.0.0.1:8090 |
| 16 | Dashboard | `dashboard/src/` (React, TypeScript) | Lab server | Polls `/api/lab/...` JSON |
| 17 | Launcher | `fsctl`, `lab/launcher.py` | Everything | One command to start/stop and verify |
| 18 | Training pipeline | `simulator/twin*.py`, `scripts/train_v7.py`, `rl/imitation_v7.py` | — | Offline, produces model zips |

### 3.3 The control loop in one sentence per step

Every 10 seconds the operator (1) discovers the services, (2) reads their telemetry from Prometheus, (3) turns it into
10 features per service, (4) places them on the call graph, (5) runs the GNN+PPO policy to get a proposed replica change
for every service, (6) in Auto mode decides who owns each service, (7) passes the change through the safety guards, (8)
if it owns the service and is in live mode, freezes the service's HPA and scales the Deployment, and (9) writes every
decision, applied or not, to the log. The lab samples the cluster every 5 seconds for the dashboard and the results.

### 3.4 Why an operator and not a change to Kubernetes

An **operator** is an ordinary program that watches Kubernetes objects and changes them through the Kubernetes API.
FlexaScale does not modify Kubernetes or the shop's code; it controls the shop from outside by changing the same field
(`spec.replicas`) the HPA changes. This is what makes it an installable add-on (Objective O1).

---

## 4. Folders and source files

All Python paths below are under `src/flexascale/` unless they start with `scripts/`, `apps/`, `config/` and so on.
"Status" uses the four labels from the top of the document.

### 4.1 Repository map

| Folder | What lives there | Status |
|---|---|---|
| `src/flexascale/` | The FlexaScale Python package (about 14,000 lines) | Implemented |
| `apps/services/` | The 16 shop microservices (FastAPI, about 4,700 lines) | Implemented |
| `apps/shopping-frontend/` | React storefront of the shop | Implemented |
| `apps/database/` | Database seeding (`seed.py`: demo users and products) | Implemented |
| `charts/shopping-app/` | Helm chart that deploys the shop (16 Deployments, HPAs, ServiceMonitors, PostgreSQL, ingress) | Implemented |
| `helm/flexascale/` | Helm chart that installs FlexaScale itself in a cluster (operator, RBAC, hand-back hook) | Implemented, verified (chart 0.5.1) |
| `config/apps/*.yaml` | Application policies (one per app or variant: shop, v5, v7, v9, rules, verification variant, bookstore) | Implemented |
| `config/twin/*.json` | Fitted application twins (`shopping.json` = first laptop, `shopping_v9.json` = second laptop) | Implemented |
| `config/lab.yaml` | Lab settings: apps, variants, SLO, sampling interval, tuned-HPA settings | Implemented |
| `dashboard/` | React + TypeScript + Vite + Tailwind source of the control center | Implemented |
| `load-testing/` | Locust user journeys (`locustfile.py`) and scenario shapes (`scenarios.py`) | Implemented |
| `data/processed/` | Processed Alibaba dataset (CSV) and its provenance | Implemented |
| `models/` | Trained policies v2–v9 with model cards; stopped/failed attempts kept under their own names | Implemented (v9 deployed default; v7 for the Fedora laptop) |
| `scripts/` | Training, evaluation, experiment batches, results building, verification, Helm tests | Implemented |
| `reports/` | Raw runs (`reports/experiments/`), invalid and demo runs, pre-registered analyses (`v7/`, `v9/`) | Data |
| `results/` | Curated results with charts, data and verification evidence | Data |
| `docs/` | Pre-registrations (`POLICY_V4`–`V9`), reports, runbook, these learning guides | Documentation |
| `tests/` | 373 automated tests (pytest) | Implemented |
| `examples/bookstore/` | A second, 5-service application used to show the framework is application-agnostic | Implemented |
| `deploy/` | Operator Dockerfile and plain Kubernetes manifests from the early phase | Implemented / partly historical |
| `observability/` | Grafana dashboard and Prometheus scrape configuration | Implemented |

### 4.2 The control loop files (the most important ones)

#### `config/app_policy.py` — the application policy

* **Class `AppPolicy`** (a dataclass): every setting the operator needs for one application. Important fields, with the
  shop's values from `config/apps/shopping.yaml`:

| Field | Shop value | Meaning |
|---|---|---|
| `name`, `namespace` | `shopping`, `flexascale-apps` | Application name (also names the Lease `flexascale-shopping`) and its namespace |
| `label_selector` | `app.kubernetes.io/part-of=flexascale-ecommerce` | Which Deployments belong to the app |
| `exclude`, `exclude_datastores` | `[shopping-frontend]`, `true` | Not autoscaled: the frontend and the database |
| `mode` | `observe` | `observe` = log only; `live` = may change the cluster |
| `min_replicas`, `max_replicas` | 1, 10 | Per-service bounds |
| `max_step`, `max_scale_down_step` | 3, 1 | Largest change per step up / down |
| `max_total_replicas` | 48 | Replica budget for the whole application |
| `cpu_target_pct` | 70 | HPA target used for comparisons and Auto's default |
| `scale_down_block_cpu_pct` | 400 | No scale-down while CPU ≥ 400% of request (= 80% of the 0.5-core limit) |
| `scale_down_block_memory_pct` | 90 | No scale-down while memory ≥ 90% |
| `slo_latency_ms` | `null` | No per-service latency SLO for the shop (important in Section 19) |
| `confidence_threshold`, `deactivation_threshold` | 0.0, 0.0 | Confidence gates (set to 0: never block) |
| `scale_up_cooldown_seconds`, `scale_down_cooldown_seconds` | 20, 30 | Minimum time between scale-ups / scale-downs of a service |
| `hpa_fallback` | `true` | May hand services back to HPA |
| `lease_seconds`, `poll_interval_seconds`, `stale_after_seconds` | 30, 10, 120 | Lease duration, control period, telemetry age limit |
| `model_path` | `models/flexascale_v9/best_model/best_model.zip` | Trained policy |
| `topology` | 25 edges | The call graph (caller, callee) |
| `cost` | $0.04048/vCPU-h, $0.004445/GiB-h | AWS Fargate list prices for estimated cost |
| `auto` | `cpu_risk_pct 400, hpa_target_pct 350, dwell_steps 2, sla_latency_ratio 1.0` | Auto-mode rule parameters |

* **Functions:** `AppPolicy.load(path)` reads YAML/JSON; `validate()` returns a list of errors (for example a negative
  bound); `assert_valid()` raises if any; `bounds_for(name)` gives a service's (min, max); `slo_for(name)` gives its
  latency SLO; `live` is a property (`mode == "live"`).

#### `discovery/workloads.py` — which services exist

* **Class `WorkloadDiscovery`**, method **`discover()`** → list of **`WorkloadInfo`** (name, desired and ready
  replicas, CPU/memory requests and limits, container images, labels, and the attached **`HPAInfo`**).
* The HPA is found through its `spec.scaleTargetRef` (the Deployment it scales), not by guessing from names.
* Databases are excluded by image name (`DATASTORE_IMAGE_MARKERS`, e.g. `postgres`), and anything in `exclude`.
* It also defines the **annotation names** FlexaScale writes on HPAs: `flexascale.io/original-min-replicas`,
  `flexascale.io/original-max-replicas`, `flexascale.io/frozen-by` (Section 11).

#### `metrics/workload_metrics.py` — telemetry from Prometheus

* **Class `WorkloadMetricsClient`**, method **`collect(namespace, deployments, cpu_request_cores, memory_capacity_bytes)`**
  → `{deployment: WorkloadMetrics}`. Section 6 explains every query.
* **Dataclass `WorkloadMetrics`**: `cpu_cores`, `cpu_pct`, `memory_bytes`, `memory_pct`, `request_rate`, `error_rate`,
  `latency_mean_ms`, `latency_p50/p90/p95/p99_ms`, `sample_age_s`, `stale`, `no_traffic`, `latency_capped`, `missing`.
* **Function `histogram_quantile(q, buckets)`**: percentile from histogram buckets (Section 6.4).
* **Function `deployment_of(pod, deployments)`**: maps a pod name to its Deployment.

#### `rl/features_v3.py` — the ten features

* **Class `FeatureTracker`**: keeps short histories per service and computes the 10 features with **`update(now,
  service, cpu_cores, ready, desired, cpu_limit, rps, latency_ms)`** → `numpy` array of 10 numbers. `note_scale()`
  records when a service last scaled up or down.
* **`pack(features, services, edges, n_max)`**: builds the flat observation vector (Section 8.2).
* **`obs_dim(n_max)`**, **`unpack(obs, n_max)`**: sizes and inverse of `pack`.
* The same code runs in the simulator and in the live operator, so "feature 3 = 1.0" means the same in both.

#### `rl/graph_policy.py` — the neural network

* **`GraphExtractor`**: input layer + message passing (Section 8).
* **`GraphFocalExtractor`**: the deployed variant: one service ("focal") at a time.
* **`GraphPolicy`**, **`PerNodeHead`**, **`_Split`**: the *joint* variant (all services in one output). Trained for
  v7 as an alternative, stopped, not deployed (`models/flexascale_v7_joint_stopped/`).

#### `rl/policy_runtime.py` — loading and running a trained model

* **Class `PolicyRuntime(model_path)`**: loads the Stable-Baselines3 zip, reads `model_card.json`, computes the file's
  SHA-256 fingerprint, and checks that the model's features and input size match this operator.
* **`predict_graph(features, edges)`** → `PolicyOutput(actions, confidences, mode="ppo_graph", probabilities, windows)`.
  Used for v7/v9 (observation version 3).
* **`predict(...)`**: the older path for v1–v6 models (5 features per service; "neighbourhood windows").
* **`info()`**: metadata shown on the dashboard's Models page (path, sha256, observation size 640, deltas, …).

#### `operator/auto_mode.py` — Auto mode

* **`AutoConfig`**: the `auto:` block (`sla_latency_ratio`, `cpu_risk_pct`, `dwell_steps`, `hpa_target_pct`,
  `hpa_tolerance`).
* **`hpa_recommendation(current, cpu_pct, target_pct, tolerance, lo, hi)`**: the HPA formula for one step.
* **`AutoArbiter.decide(...)`** → `AutoDecision(owner, rule, reason, candidate, hpa_recommendation,
  flexascale_proposal, streak, inputs)`. Section 12.3 walks through it line by line.

#### `operator/app_operator.py` — the operator

* **Class `AppOperator(policy, kube, metrics, runtime, decision_log, status_file, identity, load_model, auto)`**.
* **`start()`**: in live mode, refuses without a model, then tries to take the Lease; otherwise stays in observe mode.
* **`step()`**: one full control cycle (Section 17). Returns a `StepResult` with one decision per service.
* **`_policy_inputs()`**: builds the 10 features with `FeatureTracker` (graph models) or the older 5-feature vectors.
* **`_decide()`**: guards + ownership + execution for one service; returns the decision record that is logged.
* **`_auto()`**: calls the Auto arbiter and stores its decision in the record.
* **`_rule_output()`**: a hand-written rule instead of the model (used only for the "rule arm" in experiments).
* **`_fallback_all(reason)`**: releases every lock and restores every frozen HPA.
* **`shutdown()`**: on stop, restores every HPA and releases the Lease; idempotent (safe to call twice).
* **`run()`**: the loop: `start()`, then `step()` every `poll_interval_seconds`; any exception in a step triggers
  `_fallback_all("step_exception")`; `shutdown()` always runs at the end (`finally`).
* **`heuristic_actions()`**: a CPU-threshold rule used only when no model can be loaded (then live mode is refused).

#### `safety/hpa_manager.py`, `safety/lease.py`, `safety/lock.py` — safe execution

* **`HPAManager`**: `freeze_hpa(name, n)`, `scale_deployment(name, n)`, `ensure_hpa_active(name)`,
  `restore_hpa(hpa)`, `restore_all_frozen()`, `restore_unmanaged_replicas()`, plus the lab's
  `set_scale_down_window()`, `set_cpu_target()` and their `restore_all_*` counterparts.
* **`ControllerLease`**: `acquire()` (also used as `renew`), `release()`, `status()`, `force_release()`.
* **`ScalingLockManager`**: per-service ownership bookkeeping (`ControlMode.HPA / RL / LOCKED`), mirrored into a
  ConfigMap `flexascale-<app>-ownership` for observability.

#### `k8s/kube.py` — the Kubernetes client

* **Class `Kube`**: a thin wrapper around the `kubectl` command (`get_json`, `list_items`, `patch`, `scale`, `apply`,
  `create`, `replace`). Using `kubectl` keeps credentials and cluster selection identical to what a person would use.
  `parse_cpu("100m") = 0.1`, `parse_memory("256Mi") = 268435456`.

### 4.3 The lab and dashboard files

| File | Role | Key functions |
|---|---|---|
| `lab/experiments.py` | Runs one experiment end to end | `Lab.start(ExperimentRequest)`; `Experiment._prepare()` (comparable start), `_start_operator()`, `_start_workload()` (Locust), `_sample()` (every 5 s), `_check_operator()` (watchdog), `_teardown()`, `_finalize()` (summary), `_write_files()`; `Lab.compare(a, b)`, `Lab.live(app)`; `read_locust_history()`, `read_locust_final()` |
| `lab/benchmark.py` | Pairs runs and computes pooled statistics and verdicts | `benchmark()`, `mean_ci()`, `t95()`, `model_tag()` |
| `lab/server.py` | FastAPI server for the dashboard (127.0.0.1 only) | Endpoints `/api/lab/health`, `/overview`, `/scenarios`, `/apps/{app}/live`, `/apps/{app}/history`, `/experiments` (POST start, GET list), `/experiments/stop`, `/experiments/active`, `/experiments/{id}`, `/compare`, `/benchmark`, `/models` |
| `lab/launcher.py` | `./fsctl start/stop/status` | `cmd_start()` (8 checked steps), `cmd_stop()`, `cmd_status()` |
| `lab/processes.py`, `procctl.py`, `portforward.py` | Start/stop child processes safely (never by killing whatever is on a port) | `ProcessManager.start/stop/is_running` |
| `evaluation/cost.py` | Replica-hours, allocated and used CPU/memory, estimated cost, scaling stability | `summarize_resources()`, `percent_change()`, `scaling_stability()` |
| `dashboard/src/pages/*.tsx` | The seven pages | Overview, TopologyPage, LiveLab, AutoPage, Compare, Experiments, Models |
| `dashboard/src/timeline/` | Live Autoscaling Timeline | `ScalingTimeline.tsx` (drawing), `data.ts` (data model), `feeds.ts` (incremental polling) |

### 4.4 Learning and simulation files

| File | Role | Status |
|---|---|---|
| `data/alibaba.py`, `build_dataset.py`, `preprocessing.py`, `schema.py` | Alibaba trace → processed CSV with a fixed schema | Implemented (used for v1–v6) |
| `simulator/flexascale_env.py` | v1–v3 environment: trace replay, 4 services, 3 actions | Historical |
| `simulator/dependency_env.py` | v4–v5 environment: dependency chain, unit-free features, focal control | Historical |
| `simulator/control_env.py` | v6 environment: realistic control loop (delays, guards, HPA background) | Historical |
| `simulator/twin.py` | v7/v9 application twin (fitted simulator of the shop) | Implemented |
| `simulator/twin_control.py` | Native HPA, the operator loop and rules inside the twin | Implemented |
| `simulator/twin_env.py` | Gymnasium environment and multi-agent vector env for training | Implemented |
| `simulator/twin_workloads.py` | Random workloads and random applications for training | Implemented |
| `rl/imitation_v7.py` | Warm start: imitate a rule before PPO | Implemented |
| `rl/gnn_encoder.py` | PyTorch Geometric GNN extractor (GCN/GAT/SAGE) used by v1–v6 | Historical |
| `rl/ppo_agent.py`, `rl/train.py`, `rl/imitation.py` | Training code of v1–v6 | Historical |
| `rl/confidence_proxy.py` | Early confidence-fallback helper | Historical (the operator's confidence gate replaced it) |
| `scripts/fit_twin.py` | Fits the twin to live runs | Implemented |
| `scripts/train_v7.py` | Trains, selects and tests v7/v9 | Implemented |
| `scripts/promote_v9.py`, `scripts/v9_gate.py` | Writes model card and policy files; gate check | Implemented |

### 4.5 Older modules you may be asked about

* `operator/operator.py` (**FlexaScaleOperator**), `safety/coordinator.py`, `state/live_builder.py`, `api/` (a REST
  API): the first-phase operator and API for a 4-service prototype. **Historical.** They still run in demo mode
  (`scripts/run_operator.py --demo`), but the evaluated system is `AppOperator` started with `--policy`. The Helm
  chart's `api` component is disabled by default because it exposes mutation endpoints.
* `state/graph_inference.py` (**LiveGraphInference**): infers call edges from traffic. It reads the counter
  `gateway_forward_total` (exported by the shop's api-gateway) and keeps an exponential moving average of each edge's
  traffic, `W(t) = α·traffic(t) + (1−α)·W(t−1)`. **Implemented, used only when a policy has no `topology`** (the
  bookstore). The shop always uses its configured 25 edges. If no traffic counters exist at all, it falls back to a weak
  heuristic that links services in name order; treat that fallback as a placeholder, not as real inference.

---

## 5. The Alibaba dataset

### 5.1 What it is

Alibaba published traces from its production microservice clusters: `cluster-trace-microservices-v2021`
(https://github.com/alibaba/clusterdata). FlexaScale used the first 30-minute shard of two file types:

| Raw file | Size | Content (columns used) |
|---|---|---|
| `MSResource_0.csv` | 2.9 GB | Per instance, every 30 s: `timestamp`, `msname` (service id), `msinstanceid` (container), `instance_cpu_usage`, `instance_memory_usage` (fractions 0–1 of the allocation) |
| `MSRTQps_0.csv` | 2.8 GB | Per instance and metric, every 60 s: `timestamp`, `msname`, `msinstanceid`, `metric`, `value`. Only two metrics are used: `providerRPC_MCR` (request rate served) and `providerRPC_RT` (response time, ms) |

The raw files (about 7.4 GB including the archive) are **not** in Git; `data/raw/alibaba/v2021/` is where they go.
The call-graph files (`MSCallGraph`) were **not** downloaded, so the Alibaba-trained policies (v1–v6) used a synthetic
call chain, not Alibaba's real call graph (`reports/data_quality_report.md`).

### 5.2 Processing step by step (`data/build_dataset.py`)

1. **Read in chunks** (the files are too large for memory).
2. **Align time:** keep only resource rows whose timestamp is a multiple of 60,000 ms, to match the 60 s request data.
3. **Instance level:** average CPU and memory per (timestamp, service, instance).
4. **Service level:** per (timestamp, service): mean CPU, mean memory, and **`replica_count` = number of distinct
   instance ids**.
5. **Units:** multiply CPU and memory by 100 (fractions → percent). This step was missing at first; the first model (v1)
   was trained on near-zero CPU. The fix and the before/after maxima are recorded in `data/processed/PROVENANCE.json`
   (`fraction_to_percent_v1`).
6. **Requests:** keep provider-side metrics; per (timestamp, service) average `providerRPC_MCR` → `request_rate` and
   `providerRPC_RT` → `latency_ms`.
7. **Join** resources and requests on (timestamp, service).
8. **Enrich** to the project's `ServiceState` schema (`preprocessing.enrich_service_state_schema`). This adds generic
   columns so one schema could describe other datasets too. For Alibaba most are *derived placeholders*, not
   measurements: `source = "alibaba"`, `submit_time = start_time = timestamp`, `completion_time = makespan = jct =
   latency_ms`, `finish_time = start_time + completion_time`, `wait_time = 0`, `cpu_memory_ratio = cpu / memory`,
   `cpu_capacity = replica_count`, `gpu_* = 0`, `acceptance_ratio = 1`, `successful_requests = request_rate`,
   `failed_requests = 0`, `error_rate = 0`, `success_rate = 1`. **In a viva: only the first seven columns carry trace
   information; the rest are filled by rule.**
9. **Split** temporally into train / validation / test files (Section 5.4) and validate a sample of rows against the
   schema.

### 5.3 The output

`data/processed/alibaba_service_state.csv`: **36,355 rows = 1,213 services × 30 one-minute timestamps** (29 minutes).

| Column | Unit | Mean | Median | Max |
|---|---|---:|---:|---:|
| `cpu_utilization` | % of the container's CPU allocation | 13.66 | 11.14 | 87.45 |
| `memory_utilization` | % of memory allocation | 61.23 | 62.34 | 95.73 |
| `replica_count` | instances | 75.72 | 23 | 2,716 |
| `request_rate` | calls per … (providerRPC_MCR) | 65.69 | 15.78 | 1,981 |
| `latency_ms` | ms | 37.14 | 11.92 | 2,902.5 |

(From `reports/data_quality_report.md`.) Notice: CPU is low (median 11%) and replica counts are far above the shop's
1–10, which is why the v4–v6 simulators rescaled each service's demand into a 1–10 replica range ("normalized demand
model").

### 5.4 Splits — two different ones, do not confuse them

* **The CSV files** are split **by time**: train = the first 21 timestamps (25,446 rows), validation = the next 4
  (4,847), test = the last 5 (6,062); no timestamp appears in two files (no "leakage" of the future into training).
* **The v4–v6 training environments** split **by service** (`split_method: service` in their model cards): the test
  episodes use services never seen in training, which tests generalisation to new services.

### 5.5 Why the final model does not use Alibaba

The v1–v6 policies, trained on Alibaba-driven simulators, did not beat native HPA on the real shop (Section 19.4). The
causes were diagnosed: the trace services are not the shop's services, and the earlier simulators made HPA's rule
nearly optimal by construction. v7 and v9 were therefore trained on an **application twin** fitted to the shop's own
measurements (Section 7.4). The Alibaba data is still part of the project (v1–v6, the data-quality report), and it is
honest to say so in the viva.

---

## 6. The metrics pipeline

### 6.1 Where the numbers come from

| Signal | Produced by | Scraped by Prometheus | Interval (checked live, Fedora laptop) |
|---|---|---|---|
| CPU seconds used, memory working set | **cAdvisor** inside the kubelet (per container / per pod cgroup) | Job `kubelet`, endpoint `/metrics/cadvisor` | 10 s |
| `http_requests_total{service, method, endpoint, status}` | Each service (`apps/services/*/src/metrics.py`, `prometheus_client` Counter) | 16 ServiceMonitors (shop chart) | 15 s |
| `http_request_duration_seconds` histogram, buckets 5 ms … 10 s | Each service | same | 15 s |
| The same metrics again | Annotation-based job `kubernetes-pods` | `prometheus.io/scrape` annotation | 30 s |
| Desired/ready replicas, HPA state | Kubernetes API | Not via Prometheus: read with `kubectl` | each step |

The histogram's bucket bounds are **0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10 seconds** (plus +Inf).

### 6.2 The PromQL queries (`WorkloadMetricsClient.collect`, window `w = 1m`)

| Quantity | Query (simplified) | Meaning |
|---|---|---|
| CPU cores per pod | `sum by (pod) (rate(container_cpu_usage_seconds_total{namespace=ns, container!="", container!="POD"}[1m]))`, else the pod-level series `container=""` | `rate(...)` turns a growing "CPU seconds" counter into cores in use (CPU-seconds per second) |
| Memory per pod | `sum by (pod) (container_memory_working_set_bytes{...})` | Bytes in use (working set) |
| Sample age | `time() - max by (pod) (timestamp(container_cpu_usage_seconds_total{...}))` | How old the newest CPU sample is |
| Requests/s per pod | `max by (pod) (sum by (pod, job) (rate(http_requests_total{namespace=ns}[1m])))` | Sum per (pod, job), then the max over jobs |
| 5xx errors/s | same with `status=~"5.."` | Server errors only |
| Latency sum and count | same pattern on `http_request_duration_seconds_sum` / `_count` | For the mean latency |
| Latency buckets | same pattern on `..._bucket`, grouped by `pod, le` | For percentiles |
| Scrape health | `max by (pod) (up{namespace=ns})` | 1 if the pod's `/metrics` endpoint answered |

### 6.3 From queries to one record per service

For each Deployment (pods matched by name with `deployment_of`):

* `cpu_cores = Σ pods' cores`.
* **`cpu_pct = 100 × (cpu_cores / number_of_pods) / CPU_request_per_pod`**: the HPA's definition (average over pods,
  as % of request). Example: 2 pods using 0.07 and 0.09 cores, request 0.1 → `100 × 0.08 / 0.1 = 80%`.
* `memory_pct = 100 × (memory_bytes / pods) / memory_limit_per_pod` (the request if there is no limit).
* `request_rate = Σ pods' req/s`; `error_rate = Σ pods' 5xx/s`.
* **`latency_mean_ms = 1000 × Σ duration_sum_rate / Σ duration_count_rate`** (seconds → ms).
* `latency_p50/p90/p95/p99_ms` from the merged buckets (Section 6.4).
* `stale = sample_age > 120 s` or no CPU series at all.

### 6.4 Percentiles from a histogram (`histogram_quantile`)

A histogram does not store individual request times; it counts how many requests were at or below each bucket bound
("cumulative counts"). To estimate the q-th percentile: find the rank `q × total`, find the first bucket whose cumulative
count reaches it, and **interpolate linearly** inside that bucket.

**Worked example (illustrative numbers).** In one minute: 40 requests ≤ 50 ms, 90 ≤ 100 ms, 100 ≤ 250 ms (total 100).
p95: rank = 95. The bucket (100 ms, 250 ms] holds requests 91–100 (10 requests). 95 is 5 of the 10 into it, so
`p95 = 100 + (250 − 100) × 5/10 = 175 ms`. The real value may be anywhere in that bucket; interpolation assumes they are
spread evenly. That is why per-service percentiles are estimates, while Locust's end-to-end percentiles come from actual
response times (rounded by Locust to two significant digits above 100 ms, e.g. 130, 170, 5300).

**Capped percentiles.** If the rank falls in the +Inf bucket (more than 10 s), the true value is unknown; the code
returns the last finite bound (10 s) and adds the percentile to `latency_capped`; the dashboard shows "≥ 10000".

### 6.5 Three real problems handled in this code

Each one silently corrupted data on a real cluster before it was fixed (`docs/POLICY_V9.md` §1.1):

1. **Pod-level cAdvisor only.** With Docker on cgroup v2, CPU is reported per pod cgroup without a `container` label.
   The code prefers container-level series and falls back to pod-level ones, per pod (`_prefer`).
2. **Counted twice.** A pod scraped by a ServiceMonitor *and* the annotation job appears twice. Summing per (pod, job)
   and taking the max over jobs counts it once. (Before this fix, request rates on the first laptop were 2× too high.)
3. **Zero versus missing.** A scraped pod (`up = 1`) with no request series has genuinely served 0 requests: rate 0,
   latency undefined (`no_traffic`). A pod that is not scraped is *missing* (`request_rate` in `missing`). Nothing is
   invented: missing values stay `None` and the dashboard shows "—".

### 6.6 From records to the policy's input

The operator converts each service's record into the 10 features of `FeatureTracker.update` (Section 8.1). It also keeps
a separate 5-number vector `[cpu_pct, memory_pct, replicas, request_rate, latency_mean_ms]`
(`WorkloadMetricsClient.observation`), which is logged as `features` in every decision record for readability; the
graph policy itself uses the 10 features (logged as `policy_input`).

---

## 7. Simulation

### 7.1 Why a simulator

Reinforcement learning needs millions of trial decisions. On the real cluster one decision takes 10 seconds, so a
million decisions would take about four months, and the bad decisions of an untrained agent would break the shop. A
**simulator** imitates the shop so the agent can practise quickly and safely. The trained policy is then used on the
real cluster without further learning.

### 7.2 Gymnasium in two paragraphs

**Gymnasium** is the standard Python interface for RL environments. An environment has an `observation_space` (shape
and range of observations), an `action_space`, `reset()` (start a new episode, return the first observation) and
`step(action)` (apply the action, advance time, return `observation, reward, terminated, truncated, info`).

Stable-Baselines3 (the PPO library) talks to any environment through this interface, or through a *vectorised*
environment (`VecEnv`) that steps many environments at once and returns stacked arrays.

### 7.3 Four generations of simulator (history you should know)

| Generation | File | Used by | Key idea | Why it was replaced |
|---|---|---|---|---|
| 1 | `simulator/flexascale_env.py` (`FlexaScaleEnv`) | v1–v3 | Replays Alibaba trace demand for 4 services; actions −1/0/+1; one step = 1 trace minute | Taught "always scale up": a single 100 ms SLO many trace services could never reach, latency only from own queueing, raw units |
| 2 | `simulator/dependency_env.py` (`FlexaScaleEnvV2`) | v4, v5 | Chain of 4 services (slot i calls slot i+1), latency that replicas cannot remove, a shared bottleneck, per-service SLOs, unit-free features, "focal" control (agent decides for slot 0) | v5 beat an HPA-like rule in simulation but not native HPA live |
| 3 | `simulator/control_env.py` (`FlexaScaleEnvV3`) | v6 | Adds the live control loop: decisions every 15 s, pod start delay, 1-minute CPU windows, operator guards, native-HPA background services | Still Alibaba services, still not the shop |
| 4 | `simulator/twin.py`, `twin_env.py` | **v7, v9** | An **application twin** fitted to the shop's own measurements | Current |

### 7.4 The application twin (`simulator/twin.py`)

The twin is a simulator of *this* shop, built from what the live runs measured (`scripts/fit_twin.py`).

* **Time:** one tick = 5 s (the lab's sampling interval); the operator decides every 2 ticks (10 s), the simulated HPA
  syncs every 3 ticks (15 s).
* **CPU demand per service** = `cpu_per_req × arrival_rate + idle_cores × replicas`, fitted by least squares on 3,758
  samples per service (R² 0.74–0.95). `cpu_per_req` is CPU-seconds per request; `idle_cores` is what a replica uses at
  rest.
* **Capacity per replica** = the CPU **limit** (0.5 core). Work above capacity goes into a queue (a backlog of
  CPU-seconds), so latency rises steeply only near the limit, as measured live.
* **Serial services** (user-service's password hashing, bcrypt) handle one request at a time per replica, so bursts
  queue even when average CPU is moderate.
* **Latency per service** = its measured low-load latency + CPU queueing (processor-sharing formula `S / (1 − u)`, with
  `S` the service time and `u` the utilisation) + queue wait + the *excess* latency of the services it calls, weighted
  by the fraction of its requests that call them (`fanout`).
* **Closed loop:** Locust users wait for responses, so a queue can never hold more requests than there are waiting users.
* **Pod start:** a new pod is ready 10 s after creation (15 s with probability 0.3).
* **What controllers see:** FlexaScale sees a 1-minute Prometheus rate refreshed every 30 s (a modelling assumption;
  live, cAdvisor is scraped every 10 s); the simulated HPA sees a metrics-server value with 60 s resolution.
* **End-to-end latency** is generated per Locust request class (browse, cart, checkout, orders, login), each a lognormal
  distribution (σ = 0.8) around its fitted base latency plus the excess latency on its path. The run's p95 is the 95th
  percentile of the traffic-weighted mixture, like Locust's aggregated p95. Requests above 10 s count as failures.

**How good is it?** On the second laptop's calibration runs (native HPA at four CPU targets), the v9 twin's mean
absolute error was **2.0% in replica-hours, 8.9% in p95 latency, 4.4% in mean latency** (`reports/v9/twin_check.md`).
The v7 twin, fitted to the first laptop, had 20.5% p95 error on the second laptop: a twin is only valid for the machine
it was fitted to.

### 7.5 The training environment (`simulator/twin_env.py`)

* **`TwinEnv`** (one simulation, all services at once):
  * `observation_space = Box(low=−1, high=4, shape=(640,))`: 20 slots × 10 features + 20 × 20 adjacency + 20 mask.
  * `action_space = MultiDiscrete([5] × 20)`: one of 5 actions per slot; **action index → replica change**
    `ACTION_DELTAS = (−1, 0, +1, +2, +3)`, so index 1 is "hold".
  * `reset()`: with probability 0.25 a **random synthetic application** (`twin_workloads.random_app`), otherwise the
    shop with its parameters **perturbed** (CPU per request ×e^U(ln 0.7, ln 1.3), idle CPU ±30%, base latency ±15%) so
    the policy cannot memorise exact constants; a **random workload** around the six scenarios (peak 8–45 users, 300–600
    s, random spikes or drops). The first decision comes after 10 s, as live.
  * `step(action)`: the proposed changes go through the **same guards** as the live operator (`OperatorLoop.apply`:
    step limits, bounds, readiness, cooldowns, scale-down block at 400% CPU), the twin advances 10 s, the reward is
    computed. The episode ends when the workload ends (30–60 steps).
* **`TwinAgentsVecEnv`** (what v7/v9 actually trained on): **4 simulations × 20 agent slots = 80 parallel "agents"**.
  Agent (k, j) is service j of simulation k. Its observation is the whole application (640 numbers) **plus a one-hot
  vector of length 20 marking itself** (660 numbers); its action is one replica change (`Discrete(5)`); its reward is
  **its own share** of the step's penalty. Padded slots (no service) get reward 0 and their actions are ignored.

### 7.6 The reward (`RewardConfig`, `reward_v7`, `per_service_rewards`)

Global reward per 10-second step, in "replica-equivalents" (so every weight answers "how many replicas is avoiding this
worth?"):

```
R_t = −0.1 × ( 1.0  × Σ_services (replicas − minimum)            [over-provisioning]
             + 6.0  × min(4, max(0, p95 / p95_with_ample_capacity − 1))   [latency inflation, capped]
             + 10.0 × fraction of the step with end-to-end p95 > 1000 ms  [SLO violation]
             + 5.0  × percent of requests failing                  [errors]
             + 0.25 × number of replica changes applied )          [churn]
```

* The **cap of 4** on inflation was added after rare overload episodes (inflation up to 620) dominated training and
  taught "scale everything up" (amendment in `docs/POLICY_V7.md` §4.2).
* **Worked examples.** Three extra replicas, no slowdown, one change: −0.1 × (3 + 0.25) = −0.325. No extra replicas but
  p95 doubled (inflation 1) and the SLO broken half the step: −0.1 × (6 + 5) = −1.1. The learner therefore prefers
  paying for the replicas.
* **Per-service split (credit assignment).** With one global score, a service cannot tell whether *its* decision helped.
  `per_service_rewards` gives each service its own replicas and its own changes, plus a **share** of the latency
  penalty proportional to `(fraction of requests that reach it) × (its own excess latency)`. The shares sum to the
  global reward. If no service has excess latency, the latency penalty is split equally.

### 7.7 Baselines inside the twin (`simulator/twin_control.py`)

* **`NativeHPA(target_pct, window_s)`**: the Kubernetes algorithm (15 s sync, 10% tolerance, scale-up limit max(2×,
  +4), scale-down = highest recommendation in the window).
* **`limit_target_policy(t, d)`**: scale up to `ceil(cores / (t × limit))` when above target; scale down by one if the
  remaining replicas would stay below fraction `d` of the limit. The best of 8 versions (t ∈ {0.4, 0.5, 0.6, 0.7},
  d ∈ {0.2, 0.3}) on validation was **`limit_target(0.6/0.3)`**; it became the teacher for imitation and the "rule arm"
  in live experiments.
* **`threshold_policy`**: the operator's ±1 CPU heuristic.

### 7.8 Test sets (run once, after training and selection)

* **T1** — the six live scenarios at 25 users, 5 seeds each (30 episodes).
* **T2** — 60 random shop workloads.
* **T3** — 40 random synthetic applications.
* **Validation** (used for selection, so not a fair test) — 40 fixed random shop workloads.

---

## 8. The graph neural network in depth

### 8.1 What enters: the ten features per service (`rl/features_v3.py`)

| # | Name | Formula | Range | Why it exists |
|---|---|---|---|---|
| 0 | `cpu_limit_frac` | CPU cores ÷ ready replicas ÷ CPU **limit** | 0–2 | How close a pod is to throttling (the request is not where a pod saturates) |
| 1 | `cpu_limit_trend` | feature 0 now − feature 0 at the previous decision | −1–1 | Is CPU rising or falling |
| 2 | `rps_trend` | request rate now ÷ rate about 60 s ago (1 if unknown; 3 if it was 0 and now > 0) | 0–3 | Is traffic growing |
| 3 | `latency_inflation` | log₂(mean latency ÷ lowest latency seen in the last 30 min) | −1–4 | Slowdown relative to the service's *own* normal, not one SLO for all |
| 4 | `replica_frac` | desired ÷ max replicas (10) | 0–1 | Where the service is in its range |
| 5 | `ready_frac` | ready ÷ desired | 0–1 | Are pods still starting |
| 6 | `cpu_per_request` | log₁₀(CPU-ms per request, smoothed) ÷ 3 | 0–1 | Tells cheap services from expensive ones |
| 7 | `burstiness` | log₂(peak ÷ mean request rate over 5 min) | 0–3 | Spiky or steady traffic |
| 8 | `since_scale_up` | seconds since last scale-up ÷ 60 | 0–1 | Recent action memory (cooldowns) |
| 9 | `since_scale_down` | seconds since last scale-down ÷ 60 | 0–1 | Same, downward |

All values are clipped to their ranges and NaN/∞ become 0. Every feature is **unit-free** (a ratio, log ratio or
fraction), so a fast and a slow service, or a small and a big cluster, produce comparable numbers.

**Decoding a real input.** In run `20261031-035531`, step 4, order-service's logged `policy_input` was
`[0.1736, 0.104, 1.0, 0.0, 0.1, 1.0, 0.4133, 1.0, 1.0, 1.0]`:

* CPU was 86.79% of its 0.1-core request = 0.0868 cores on 1 ready pod; ÷ 0.5-core limit = **0.1736** (feature 0).
* CPU rose by 0.104 since the last decision (feature 1).
* Traffic trend 1.0 (no 60 s history yet), latency at its own minimum (log₂ 1 = 0), 1 of 10 replicas (0.1), all ready.
* `cpu_per_request` 0.4133 → 10^(0.4133 × 3) ≈ **17.4 CPU-ms per request** (smoothed estimate).
* Burstiness 1.0 → recent peak ≈ 2 × mean rate; no recent scaling (features 8, 9 = 1).

### 8.2 Graph, nodes, edges, adjacency matrix, mask

* **Graph:** services are **nodes**; "A calls B" is a **directed edge** A → B. The shop has 16 nodes and 25 edges
  (`config/apps/shopping.yaml`, `topology`).
* **Node order** is always the sorted service names, so node *i* is always the same service.
* **Adjacency matrix** `A` (20 × 20): `A[i, j] = 1` if service i calls service j, else 0. Rows = callers, columns =
  callees. Self-loops are not added.
* **Padding and mask:** the network has 20 node slots (`n_max = 20`). The shop uses 16; slots 17–20 are zero and the
  **mask** (length 20) is 1 for real services, 0 for padding. An application with more than 20 services is rejected.
* **`pack()`** concatenates: `X` (20 × 10 = 200 numbers) + `A` (400) + mask (20) = **640**. For the focal policy a
  one-hot vector of length 20 marking the deciding service is appended: **660 inputs per decision**.

### 8.3 What happens inside (`GraphExtractor.embed` + `GraphFocalExtractor.forward`)

Notation: `x_i` = node i's 10 features, `h_i` = its 64-number embedding, `m_i` = mask, `N_out(i)` = services i calls,
`N_in(i)` = services that call i.

**Step 0 — input projection.**

```
h_i⁽⁰⁾ = ReLU(W_in · x_i + b_in) · m_i          W_in: 64 × 10
```

**Steps 1 and 2 — two rounds of message passing (k = 0, 1).**

```
z_i = W_self⁽ᵏ⁾·h_i + b⁽ᵏ⁾                                         (the node itself)
    + W_callee⁽ᵏ⁾ · mean{ h_j : j ∈ N_out(i) }                      (what it calls)
    + W_caller⁽ᵏ⁾ · mean{ h_j : j ∈ N_in(i) }                       (who calls it)
h_i⁽ᵏ⁺¹⁾ = ( h_i⁽ᵏ⁾ + ReLU(LayerNorm(z_i)) ) · m_i
```

In code: `torch.bmm(adj, h) / deg_out` is the mean over callees (row i of `A·H` sums the embeddings of i's callees,
divided by the number of callees, at least 1); `torch.bmm(adj.transpose(1, 2), h) / deg_in` is the mean over callers.

Terms explained:

* **Message** = a neighbour's embedding; **aggregation** = the mean of the messages (mean, so a service with nine callees
  is not drowned by them).
* **Separate weights per direction** (`W_callee`, `W_caller`): "my callee is overloaded" and "my caller is getting busy"
  mean different things for scaling, so they are learned separately.
* **LayerNorm**: rescales the 64 numbers of each node to mean 0, variance 1 (with learned scale and shift), which keeps
  training stable.
* **Residual connection** (`h + …`): the new embedding is the old one plus an update, so a node never loses its own
  information.
* **Mask multiplication**: padded slots stay exactly zero.

**Readout.**

```
pooled = Σ_i m_i h_i⁽²⁾ / Σ_i m_i                      (mean over real services: application context)
own    = Σ_i focal_i h_i⁽²⁾                             (the focal service's embedding)
output = [own, pooled]                                  128 numbers
```

### 8.4 What comes out and what it means

128 numbers per decision: 64 describing the deciding service *after* it has heard from its neighbours (up to two hops
away), and 64 describing the application as a whole. These go to the PPO heads (Section 9).

**Receptive field (two hops).** After round 1, order-service's embedding contains its callees (catalog, inventory,
payment, cart, shipping, fraud, notification) and its caller (api-gateway). After round 2 it also contains what *those*
services heard: for example cart-service's callee pricing-service, and api-gateway's other callees.

### 8.5 A tiny numeric example (illustrative numbers, 2-dimensional embeddings)

Chain `gateway → order → payment`. Suppose after step 0: `h_gateway = (1, 0)`, `h_order = (0, 1)`, `h_payment = (2, 2)`,
and imagine all weights are identity matrices and we skip LayerNorm/ReLU to see the flow:

* order: self (0, 1) + mean of callees = payment (2, 2) + mean of callers = gateway (1, 0) → z = (3, 3).
* gateway: self (1, 0) + callees = order (0, 1) + callers = none (0, 0) → z = (1, 1).
* payment: self (2, 2) + callees none + callers = order (0, 1) → z = (2, 3).

After the residual, order's embedding mixes both neighbours. In round 2, gateway receives order's *new* embedding, which
already contains payment, so gateway "sees" payment two hops away. The real network does the same with learned 64 × 64
matrices.

### 8.6 The no-graph ablation

`use_graph=False` skips the callee and caller terms: each service decides from its own features plus the pooled mean.
v9 trained one such run (`focal_bc_nograph_s1`). On the three held-out test sets the graph minus no-graph reward
differences were −0.001 [−0.026, +0.024] (T1), +0.157 [−0.363, +0.677] (T2) and +0.708 [−3.304, +4.720] (T3): every
interval includes 0, so **the graph showed no measurable benefit** on this shop (`reports/v9/ablation.md`). This is
reported as a finding, not hidden.

### 8.7 Exact parameter count (42,566)

| Part | Shape | Parameters |
|---|---|---:|
| Input layer `W_in`, `b_in` | 10 → 64 | 704 |
| Per round: `W_self` + bias | 64 → 64 | 4,160 |
| Per round: `W_callee` (no bias) | 64 → 64 | 4,096 |
| Per round: `W_caller` (no bias) | 64 → 64 | 4,096 |
| Per round: LayerNorm (scale + shift) | 64 | 128 |
| Two rounds | | 24,960 |
| **Graph extractor total** | | **25,664** |
| Actor hidden layer | 128 → 64 | 8,256 |
| Critic hidden layer | 128 → 64 | 8,256 |
| Action head | 64 → 5 | 325 |
| Value head | 64 → 1 | 65 |
| **Total** | | **42,566** |

### 8.8 The older GNN (v1–v6)

`rl/gnn_encoder.py` (**historical**) used PyTorch Geometric graph convolutions (`GCNConv`, also `GATConv`/`SAGEConv`
options) over a fixed 4-service chain with 5 raw features per service. v7 replaced it with the custom extractor above
because the shop has 16 services, the real call graph is not a chain, and directed caller/callee messages were needed.
That is why PyTorch Geometric (planned in the design phase) is not used by the final model.

---

## 9. PPO in depth

### 9.1 The pieces

* **Agent:** the policy network plus the PPO learning procedure.
* **Environment:** `TwinAgentsVecEnv` (training); the cluster (use).
* **Observation:** 660 numbers for one service's decision (Section 8.2).
* **Action:** an index 0–4 → replica change −1, 0, +1, +2, +3.
* **Actor (policy head):** 128 → 64 (tanh) → 5 numbers called **logits**.
* **Probability distribution:** `softmax(logits)`: `p_a = e^{logit_a} / Σ_b e^{logit_b}`, five probabilities that sum to
  1 (a *categorical distribution*).
* **Critic (value head):** 128 → 64 (tanh) → 1 number `V(s)`: the expected discounted sum of future rewards from this
  state. Used only in training.
* Actor and critic **share** the graph extractor (Stable-Baselines3 `ActorCriticPolicy`, `net_arch = {pi: [64], vf:
  [64]}`, default activation tanh).

### 9.2 Return, discount, value and advantage

* **Return** from step t: `G_t = r_t + γ r_{t+1} + γ² r_{t+2} + …`, with discount **γ = 0.97**. A reward 33 steps (≈ 5.5
  minutes) ahead counts about e⁻¹ ≈ 37% as much as one now (effective horizon `1 / (1 − γ) ≈ 33` steps). This is long
  enough to see the effect of a pod starting (1–2 steps) and of cooldowns (2–3 steps).
* **Value** `V(s)`: the critic's estimate of `G` from state s.
* **Advantage**: "how much better was this action than usual in this state". FlexaScale uses **Generalised Advantage
  Estimation (GAE)** with **λ = 0.95**:

```
δ_t = r_t + γ · V(s_{t+1}) − V(s_t)                     (one-step surprise)
Â_t = δ_t + (γλ) δ_{t+1} + (γλ)² δ_{t+2} + …            (smoothed sum of surprises)
```

λ trades bias for variance: λ = 0 trusts the critic fully; λ = 1 uses actual returns. 0.95 is the common default.

**Small example (illustrative).** r_t = −0.3, V(s_t) = −2.0, V(s_{t+1}) = −1.6: δ = −0.3 + 0.97 × (−1.6) − (−2.0) =
+0.148. The action led to a better-than-expected state, so its advantage is positive and PPO will make it a little more
likely.

### 9.3 The clipped objective

For each action taken during data collection, PPO compares the **new** policy with the **old** one that collected it:

```
ρ_t(θ) = π_θ(a_t | s_t) / π_θ_old(a_t | s_t)          (probability ratio)
L_clip(θ) = mean_t [ min( ρ_t Â_t , clip(ρ_t, 1 − ε, 1 + ε) Â_t ) ]
```

**Why the min and the clip.** If an action was good (Â > 0), raising its probability helps, but only until ρ = 1 + ε;
beyond that the clipped term is smaller and wins the min, so the gradient stops. If it was bad (Â < 0), lowering it
helps only until ρ = 1 − ε. Each update can therefore move each action's probability only a limited amount.

**Numeric example.** ε = 0.1 (FlexaScale's fine-tuning value), Â = +2, old probability 0.30, new 0.45: ρ = 1.5. Unclipped
term 1.5 × 2 = 3.0; clipped term 1.1 × 2 = 2.2; the objective uses 2.2, and no further push comes from this sample.

**The full loss Stable-Baselines3 minimises:**

```
loss = −L_clip + vf_coef × mean (V(s_t) − G_t)² − ent_coef × entropy
     = −L_clip + 0.5 × value error              − 0.01 × entropy
```

Entropy `H = −Σ p_a log p_a` measures how spread out the action probabilities are; subtracting it rewards keeping some
uncertainty, which encourages **exploration**. Advantages are normalised per mini-batch (SB3 default), gradients are
clipped to a total norm of 0.5, and the optimiser is Adam.

### 9.4 Exploration versus exploitation

* **Training (exploration):** actions are **sampled** from the probabilities, so a 25% action is tried about a quarter
  of the time; the entropy bonus keeps probabilities from collapsing too early.
* **Use (exploitation):** the operator takes the **most likely action** (argmax, `PolicyRuntime.predict_graph`) and
  reports its probability as the **confidence**.

### 9.5 Training procedure for v9 (from `scripts/train_v7.py` and `models/flexascale_v9/model_card.json`)

1. **Fit the twin** to the second laptop's calibration runs (`config/twin/shopping_v9.json`).
2. **Warm start by imitation** (`rl/imitation_v7.warm_start_focal`): run the teacher rule `limit_target(0.6/0.3)` for 400
   twin episodes with 20% random deviations (for coverage); every service decision becomes a sample (focal observation,
   the rule's action, the service's own discounted return). Train the actor with **class-weighted cross-entropy** (the
   rule almost never scales up: 17 of 24,647 labels were +1 in one check, so rare actions get larger weights, capped at
   50) and the critic with mean-squared error to the returns (weight 0.5); copies of samples with rescaled CPU and the
   rule's own relabelling teach the rare scale-ups (`augment = 3`). 15 epochs, batch 1024, Adam lr 1e-3.
3. **PPO fine-tuning** on `TwinAgentsVecEnv` (4 simulations × 20 agents = 80 parallel decisions per environment step):

| Setting | Value | What it means |
|---|---|---|
| `n_steps` | 64 | Environment steps collected per update, per agent slot → 64 × 80 = **5,120 decisions per update** |
| `batch_size` | 512 | Mini-batch → 10 mini-batches per epoch |
| `n_epochs` | 10 | Passes over the 5,120 samples → 100 gradient steps per update |
| `learning_rate` | 1 × 10⁻⁴ (warm-started runs; 3 × 10⁻⁴ from scratch) | Adam step size |
| `clip_range` ε | 0.1 (warm-started; 0.2 from scratch) | Probability ratio limit |
| `target_kl` | 0.02 (warm-started) | Stop an update early if the policy moved too far (KL divergence) |
| `gamma`, `gae_lambda` | 0.97, 0.95 | Discount, GAE |
| `ent_coef`, `vf_coef`, `max_grad_norm` | 0.01, 0.5, 0.5 | Entropy bonus, value-loss weight, gradient clipping |
| Total | 2,000,000 agent-steps per run | ≈ 390 updates |

4. **Evaluate every 250,000 agent-steps** on the 40 validation workloads with the deterministic policy inside the same
   operator loop and guards; save the best checkpoint of the run.
5. **Four runs:** `focal_bc_s1` (seed 1), `focal_bc_s2` (seed 2), `focal_bc_nograph_s1` (ablation),
   `focal_bc_v5reward_s1` (older reward, ablation). GPU (RTX 3050), 9.7–12.1 minutes each; 63 minutes in total including
   evaluation (`docs/POLICY_V9.md` §8).
6. **Select** the best run on validation: `focal_bc_s2`, reward **−2.466** (better than the rule's −2.99).
7. **Gate:** it must beat the previous model (v7) on the same validation set: −2.47 vs −2.91 → passed. (Selection and
   gate used the same set, which flatters v9; the held-out tests are the fair comparison.)
8. **Promote** (`scripts/promote_v9.py`): copy to `models/flexascale_v9/best_model/`, write the model card (SHA-256
   `2f95764b…`), update the policy files. No earlier model was overwritten.

### 9.6 Training versus inference

| | Training | Inference (live) |
|---|---|---|
| Where | Twin simulator, offline | Real cluster, every 10 s |
| Actions | Sampled | Argmax |
| Weights | Change | Fixed |
| Critic | Used | Not used |
| Device | GPU for v9 (1.79× faster than the best CPU setting) | CPU, milliseconds |

**Not implemented:** online learning on the live cluster (the Phase 2 design proposed PPO updates from live rewards). The
live policy never changes during or between experiments; a policy that changes mid-experiment cannot be evaluated fairly.

---

## 10. How the GNN and PPO work together

### 10.1 The whole chain for one step (live)

1. `AppOperator.step()` discovers 16 services and collects their telemetry.
2. `_policy_inputs()` calls `FeatureTracker.update()` for each service → 16 vectors of 10 numbers.
3. `PolicyRuntime.predict_graph(features, edges)`:
   * sorts the service names; `pack()` → one 640-number observation of the whole application;
   * builds a **batch of 16 rows**, each = the 640 numbers + the one-hot of one service (660 numbers);
   * one forward pass: graph extractor → [own, pooled] → actor → softmax → a 16 × 5 probability table;
   * for each service: action = argmax, confidence = its probability.
4. `_delta()` maps each action index to a replica change through the model card's `action.deltas` (−1, 0, +1, +2, +3).
5. `_decide()` clips the change to the step limits and bounds (this is `policy_replicas`, the policy's proposal), applies
   the safety guards, asks the Auto arbiter (in Auto mode) and, if FlexaScale owns the service in live mode, freezes the
   HPA and scales the Deployment.

### 10.2 Where dependency information enters

Only in the message-passing terms of Section 8.3: the adjacency matrix decides whose embeddings are averaged into whose.
The one-hot vector then decides *which* node's embedding is read out. If the graph were empty (no edges), each service
would decide from its own features and the application mean, exactly as in the no-graph ablation.

### 10.3 A real decision, end to end

From `reports/experiments/20261031-035531-shopping-auto-flash_sale/decisions.jsonl`, step 4, order-service:

```json
"policy": {"mode": "ppo_graph", "action": 2, "action_label": "scale_up", "delta": 1, "confidence": 0.4883,
           "probabilities": [0.01, 0.4879, 0.4883, 0.0137, 0.0]},
"current_replicas": 1, "hpa_recommendation": 2, "policy_replicas": 2,
"auto": {"owner": "flexascale", "rule": "efficiency", "reason": "no SLA risk; FlexaScale and HPA agree"},
"controller": "flexascale", "proposed_replicas": 2, "safety_reasons": ["accepted"], "applied": true, "hpa_note": "frozen"
```

Read it like this: the probabilities over (−1, 0, +1, +2, +3) were (1%, 48.79%, **48.83%**, 1.37%, 0%). "Scale up by one"
won by four hundredths of a percent over "hold", so the confidence was only 0.4883. The policy proposed 2 replicas; in
this controlled run HPA's rule (target 70%) also said 2; Auto kept FlexaScale as owner (efficiency rule); safety accepted;
the HPA was frozen at 2 and the Deployment scaled. Kubernetes reported 2 desired replicas 6.1 s later and 2 ready 16.1
s later (`results/verification/README.md`). It is a good viva example because it shows how close to a tie a learned
policy's decision can be.

---

## 11. Safety controller and Kubernetes execution

### 11.1 Why a safety layer at all

A learned policy can be wrong, especially on situations it never saw in training. The safety layer makes sure a wrong
proposal cannot do serious harm and that the native HPA is never left disabled. Every guard can only **reduce or
block** a change, never enlarge it, and every decision records the reasons (`safety_reasons`) or `accepted`.

### 11.2 The guards, in the order the code applies them (`AppOperator._decide`)

Let `current` = desired replicas now, `delta` = the policy's change.

| # | Check | Code effect | Logged reason |
|---|---|---|---|
| 0 | Telemetry: CPU missing or older than 120 s | No FlexaScale decision; service goes to HPA | `telemetry_unavailable` / `telemetry_stale` |
| 1 | Step limits | `delta` clipped to [−1, +3] (`max_scale_down_step`, `max_step`) | (silent) |
| 2 | Bounds | `proposed = clip(current + delta, min, max)` = 1…10. This value is logged as `policy_replicas` | — |
| 3 | Current outside bounds | Bring back inside | `restore_replica_bounds` |
| 4 | Replica budget | Total of the application may not exceed 48; a multi-replica step shrinks to the room left | `scale_up_clipped_replica_budget` / `scale_up_blocked_replica_budget` |
| 5 | Readiness (up) | No scale-up while ready < current (pods still starting) | `scale_up_waiting_for_readiness` |
| 6 | Scale-up cooldown | No scale-up within 20 s of the last one | `scale_up_cooldown` |
| 7 | CPU block (down) | No scale-down while CPU ≥ 400% of request | `scale_down_blocked_cpu` |
| 8 | Memory block (down) | No scale-down while memory ≥ 90% | `scale_down_blocked_memory` |
| 9 | SLO block (down) | No scale-down while latency > the service's SLO (if one is set; not for the shop) | `scale_down_blocked_slo` |
| 10 | Scale-down cooldown | No scale-down within 30 s of the last one | `scale_down_cooldown` |
| 11 | Readiness (down) | No scale-down while pods are not ready | `scale_down_waiting_for_readiness` |
| 12 | Ownership (Auto or confidence gate) | Decide who owns the service (Section 12) | `auto_<rule>` / `confidence_below_*` / `ownership_cooldown` |
| 13 | No-fallback policy | If `hpa_fallback: false`, hold under FlexaScale instead of handing back | `hold_no_hpa_fallback` |

**Why each exists:** cooldowns because Prometheus rates are 1-minute averages that need time to reflect the last change;
readiness because adding pods while earlier ones are still starting double-counts; the budget so the single node cannot be
overloaded; the CPU block so the policy cannot remove capacity from a busy service; step limits so one bad decision is
small.

### 11.3 Ownership: three mechanisms that together guarantee "never two controllers"

1. **The Kubernetes Lease** (`safety/lease.py`). A `coordination.k8s.io/v1` Lease object named `flexascale-<app>` (for
   the shop: `flexascale-shopping`) records a holder identity and a renew time; duration 30 s. The operator takes it in
   `start()` and renews it at the start of every step. Taking and renewing use `kubectl replace` with the object's
   `resourceVersion`, so if two operators race, the API server accepts only one (*optimistic concurrency*). A lease whose
   holder stopped renewing for 30 s is expired and can be taken over. **Purpose: only one FlexaScale instance controls an
   application.** If renewal fails, every service goes back to HPA and the operator drops to observe mode
   (`lease_lost`).
2. **The HPA freeze** (`HPAManager.freeze_hpa`). Before FlexaScale changes a service, it patches that service's HPA so
   that `minReplicas = maxReplicas = the new count`, and stores the original bounds in annotations
   (`flexascale.io/original-min-replicas`, `…-max-replicas`, `flexascale.io/frozen-by`). A frozen HPA keeps running but
   can only ask for the count FlexaScale chose. **Purpose: the HPA and FlexaScale never act on the same Deployment at the
   same time.**
3. **The lock manager** (`safety/lock.py`). Per-service bookkeeping of the current owner (`HPA` / `RL`), mirrored into a
   ConfigMap `flexascale-<app>-ownership` so ownership is visible in the cluster.

### 11.4 Execution: the actual Kubernetes calls

For a service FlexaScale owns, in live mode (`_decide`, end):

```
acquire_rl_lock(service)                       # bookkeeping
freeze_hpa(service, proposed)                  # kubectl patch hpa <svc>-hpa (min=max=proposed + annotations)
if proposed != current:
    scale_deployment(service, proposed)        # kubectl scale deployment/<svc> --replicas=<proposed>
    remember the time (for cooldowns); FeatureTracker.note_scale(...)
record["applied"] = True
```

`kubectl scale` uses the Deployment's **scale sub-resource**: it changes only `spec.replicas`. Kubernetes then creates or
deletes pods; the readiness probe (`/readyz`) decides when a new pod counts as ready.

For a service handed to HPA: `release_rl_lock(service)` and, if it was FlexaScale's or its HPA is frozen,
`ensure_hpa_active(service)`, which restores the original bounds from the annotations and removes them.

A Deployment with **no HPA** is a special case: FlexaScale records its original replica count in an annotation
(`flexascale.io/original-replicas`) before the first change, and `restore_unmanaged_replicas()` puts it back on
hand-back, because nothing else would.

### 11.5 Every fallback path (when FlexaScale lets go)

| Trigger | Scope | Who acts | Verified live? |
|---|---|---|---|
| Missing or stale CPU telemetry for a service | That service | Operator (guard 0 / Auto rule 1) | **Yes**: Prometheus cut for 60 s → all 16 services to HPA in the same step (`20261031-030452`) |
| Policy confidence below threshold | That service | Operator | Not exercised: thresholds are 0 in the shop's policy |
| Auto SLA-risk rule | That service | Operator | **Yes**: `20261031-035531` (34 decisions) |
| A step raises an exception | All services | Operator `run()` → `_fallback_all` | Unit-tested |
| Lease renewal fails | All services | Operator | Unit-tested |
| Operator stopped (SIGTERM/SIGINT) | All services | Operator `shutdown()` | Yes: every run's cleanup |
| Operator killed (SIGKILL) or hung | All services | **Lab watchdog** `_check_operator`: process exited, or status file not updated for 4 poll intervals (40 s) | **Yes**: SIGKILL at +104.8 s → fallback event with all 16 HPAs restored at +106.2 s (`20261031-031625`) |
| Helm upgrade, rollback or uninstall | All services | Helm hook Job scales the operator to 0 first, so it hands back while it still has permissions | Yes: Helm lifecycle test |
| End of every experiment | All services | Lab `_teardown`: restores HPAs, behaviour and targets; checks no frozen HPA and no live Lease → `cleanup.safe` | Yes: every run |

### 11.6 Observe mode

`mode: observe` (the default of every policy and of the Helm chart): the operator computes and logs every decision but
never touches the cluster (`record["note"] = "observation only"`), takes no Lease, and in the Helm chart its RBAC role has
no write permissions at all. In the dashboard this is "FlexaScale shadow mode".

---

## 12. The three controller modes

All three run the same shop under the same load; what differs is who may change replicas.

### 12.1 Mode 1 — Native HPA (`controller = hpa`)

* **Who scales:** Kubernetes' HPA, every service, CPU target 70% of request, bounds 1–10, scale-down window 300 s.
* **FlexaScale's role:** optional **shadow mode**: the operator runs with `--mode observe` and logs what it *would*
  propose. No Lease, no frozen HPA. Its proposals appear on the dashboard as "would propose".
* **Variants in the lab:** `hpa_fast` (scale-down window 60 s) and `hpa_tuned` (calibrated CPU target and window: 350%,
  60 s on the second laptop; 250%, 60 s on the first). The lab patches every HPA's `spec.behavior` and `spec.metrics` for
  the run, stores the originals in annotations, and restores them in `_teardown`.
* **Verified live:** run `20261031-001033`: HPA scaled order and catalog 1→3 and api-gateway and inventory 1→2;
  FlexaScale logged 496 proposals and applied 0.

### 12.2 Mode 2 — FlexaScale (`controller = flexascale`)

* The operator starts with `--mode live`, takes the Lease, and owns every service whose telemetry is fresh. The shop's
  confidence thresholds are 0, so no service is handed back for low confidence.
* Every proposal goes through the guards; a FlexaScale-owned service's HPA is frozen at FlexaScale's count.
* **Verified live:** ownership, safety and execution worked in three runs on the Fedora laptop (all 16 services owned,
  every decision accepted, cleanup safe), but **the policies held every service at 1 replica**, so no scale change was
  applied in those runs (explained in Section 19.3). Scale changes in this mode were verified earlier on the same laptop
  (`20261028-061846`: order-service 1→2 at +115 s, ready at +130 s, back to 1 at +255 s) and in the v9 evaluation on the
  second laptop (E2: two applied changes).

### 12.3 Mode 3 — Auto (`controller = auto`)

The operator runs with `--mode live --auto`. For **every service at every step**, `AutoArbiter.decide` (in
`operator/auto_mode.py`) chooses the owner. Line by line:

```python
prev = self.owner(service)                                     # previous owner, "hpa" at the start
hpa_rec = hpa_recommendation(current, cpu_pct, self.cpu_target_pct, 0.1, lo, hi)   # HPA's formula, one sync
# Rule 1: controller health → HPA immediately
if not model_available:    return done("hpa", "controller_health", ..., immediate=True)
if not telemetry_ok:       return done("hpa", "controller_health", ..., immediate=True)
if not lease_held:         return done("hpa", "controller_health", ..., immediate=True)
# Rule 2: policy confidence (threshold depends on who owns it now)
threshold = deactivation if prev == "flexascale" else activation
if confidence < threshold: return done("hpa", "policy_confidence", ..., immediate=(prev == "flexascale"))
# Rule 3: SLA risk, capacity first → HPA immediately
at_risk = (latency > ratio × SLO) or (cpu_pct >= cpu_risk_pct)
if at_risk and hpa_rec > flexascale_proposal:
                           return done("hpa", "sla_risk", ..., immediate=True)
# Rule 4: efficiency → FlexaScale (needs dwell)
return done("flexascale", "efficiency", ..., immediate=False)
```

`done()` implements **hysteresis** (resistance to flapping): if the chosen owner equals the previous one, nothing
changes; an *immediate* switch (to HPA for health or SLA risk) happens at once; a non-immediate switch (to FlexaScale)
happens only after the same choice on `dwell_steps = 2` consecutive steps. While waiting, the reason says "(waiting 1/2
steps before switching)".

Important details for the viva:

* `flexascale_proposal` is FlexaScale's proposal **after** the safety guards.
* `hpa_recommendation` is computed at `auto.hpa_target_pct` (350% in the shop's default policy, the tuned value), not at
  the HPA objects' 70%. It is a **recommendation**, never an action.
* The shop has no per-service latency SLO (`slo_latency_ms: null`), so in practice rule 3 fires only on CPU.
* Ownership is enforced by the same Lease + freeze mechanism as Mode 2: Auto only decides *who*, the execution path is
  the same.

**Verified live (all on the Fedora laptop, flash sale, 40 users; `results/verification/README.md`):**

| Run | What happened |
|---|---|
| Default policy `20261031-002805` | Auto chose FlexaScale (efficiency) for every service; the policy proposed a scale-up of order-service at +289 s; safety accepted; HPA frozen; desired 1→2 after 5.9 s, ready after 15.9 s. 480 FlexaScale-owned and 16 HPA-owned decisions (the 16 HPA decisions are the first step, while the 2-step dwell was still running) |
| Controlled SLA-risk variant `20261031-035531` (`config/apps/shopping_verify_sla.yaml`: CPU risk 60%, HPA at 70%) | Mixed ownership in 21 of 31 steps: api-gateway, cart, catalog, inventory and order moved to HPA by `sla_risk` while 11 services stayed with FlexaScale; HPA scaled the risky services to 3; FlexaScale applied 7 changes |
| Prometheus cut `20261031-030452` | All 16 services → HPA in the same step (`controller_health`); FlexaScale retook them after 2 steps and applied 6 scale-downs |
| Operator SIGKILL `20261031-031625` | Killed at +104.8 s; the lab watchdog logged the fallback with all 16 HPAs restored at +106.2 s, about 1.4 s later; HPA then scaled order-service to 4 and catalog to 3 |

---

## 13. The sixteen microservices

All services are Python FastAPI applications (`apps/services/<name>/src/main.py`), packaged with `python:3.11-slim`, each
with `/healthz` (alive), `/readyz` (ready), `/metrics` (Prometheus) and a metrics middleware that counts every request
(except those three paths) into `http_requests_total{service, method, endpoint, status}` and times it into
`http_request_duration_seconds{service, method, endpoint}`. They share one PostgreSQL 16 database (`ecommerce`, 2 GiB
volume, `max_connections 300`). Calls between services use `httpx` with service URLs from environment variables.

| Service | Responsibility | Main endpoints | Calls |
|---|---|---|---|
| **api-gateway** | Single entry point; forwards `/api/<area>/…` to the right service; counts forwards in `gateway_forward_total` | `/`, `/api/system/status`, routes for users, products, categories, cart, orders, inventory, payments, search, recommendations, reviews, pricing, shipping, wishlist | All 12 routed services |
| **user-service** | Registration, login (bcrypt password hashing: CPU-heavy and serial per worker), JWT tokens, profiles | `POST /api/users/register`, `/login`, `GET /me`, `/verify-token` | — |
| **catalog-service** | Products and categories | `GET/POST/PUT/DELETE /api/products…`, `/api/categories…` | — |
| **cart-service** | Shopping carts | `GET /api/cart/{user}`, add/update/remove items, clear | catalog, inventory, pricing |
| **order-service** | Checkout (the longest path) and order history | `POST /api/orders/checkout`, `GET /api/orders/user/{id}`, cancel | cart, catalog, inventory, fraud, payment, shipping, notification |
| **inventory-service** | Stock, reservations (two-phase: reserve → confirm or release) | `GET/PUT /api/inventory…`, `/reserve`, `/confirm`, `/release` | — |
| **payment-service** | Simulated payment processing (with optional delays and declines) | `POST /api/payments/process` | — |
| **fraud-service** | Risk check before payment | `POST /api/fraud/check` | — |
| **shipping-service** | Shipping quotes | `POST /api/shipping/quote` | — |
| **notification-service** | Order confirmations | `POST /api/notifications/order`, `GET /recent` | — |
| **pricing-service** | Price quotes with promotions | `POST /api/pricing/quote` | promotion |
| **promotion-service** | Active promotions | `GET /api/promotions/active` | — |
| **search-service** | Ranked product search | `GET /api/search` | catalog, pricing |
| **recommendation-service** | "Customers also viewed" | `GET /api/recommendations/{product}` | catalog, review |
| **review-service** | Product reviews and summaries | `GET/POST /api/reviews/{product}` | — |
| **wishlist-service** | Wishlists | `GET/POST/DELETE /api/wishlist…` | catalog |

**Checkout request flow** (`order-service`, `checkout`): read the cart (cart-service) → fetch each product's price
(catalog) → shipping quote and fraud screening → reserve stock (inventory) → charge (payment) → confirm or release stock
→ empty the cart → notify. An idempotency key prevents duplicate orders.

**A design property that matters for the results.** `checkout` is an `async` handler but uses a **synchronous**
SQLAlchemy database session. While it waits for the database it blocks the event loop of its worker, so under load the
order service's latency rises sharply while its CPU stays moderate. Adding replicas helps less than CPU suggests
(`docs/POLICY_V8.md`). This is why CPU-based policies under-react to it (Section 19.3).

**Deployment and scaling:** each service is a Deployment (start 1 replica) with a Service, a ServiceMonitor and an HPA
(`<name>-hpa`, 1–10, 70% CPU), all from `charts/shopping-app` (release `shopping-app`, chart 1.1.0). The frontend and the
database are not autoscaled.

**Honest note:** the chart contains demo credentials (database password, JWT secret) in `values.yaml`. Acceptable for a
local laboratory, not for production.

---

## 14. Infrastructure

### 14.1 Minikube

One-node Kubernetes on the laptop: profile `flexascale`, Docker driver, containerd runtime, Kubernetes v1.31.0 (Fedora
laptop: about 9 GiB memory; second laptop: 4 vCPU, 6 GB). The shop is reached through the Minikube **ingress** (an HTTP
entry point) at `http://<minikube ip>/`.

### 14.2 Docker images

* Shop images: built by `scripts/build_shop_images.sh` inside Minikube's Docker daemon (no registry), with the tags the
  shop chart expects; `imagePullPolicy: IfNotPresent` then uses the local images.
* Operator image `flexascale:0.6.0` (`deploy/flexascale/Dockerfile`): `python:3.11-slim`, `kubectl` v1.31.0, CPU-only
  PyTorch, the package, `scripts/run_operator.py`, and the v5, v7 and v9 models; runs as user 65534 (non-root). Built
  locally and loaded into Minikube; not published to a registry.

### 14.3 Prometheus and Grafana

Installed by the Helm release `monitoring` (chart kube-prometheus-stack 92.11.0) in `flexascale-monitoring`, which also
brings kube-state-metrics, node-exporter, Alertmanager and the Prometheus Operator (which turns **ServiceMonitor**
objects into scrape jobs). Port-forwarded to `localhost:9090` (Prometheus) and `localhost:3000` (Grafana) by `./fsctl
start`. Grafana's FlexaScale dashboard is `observability/grafana/dashboard-configmap.yaml`. `metrics-server` (which feeds
the HPA, not Prometheus) runs with `--metric-resolution=60s` (checked on the second laptop).

### 14.4 Kubernetes manifests

* `charts/shopping-app/templates/`: namespace, ConfigMap, Secret, Deployments, Services, ServiceMonitors, ingress,
  PostgreSQL Deployment/Service/PVC. HPAs come from `deploy/kubernetes/hpa.yaml` (`autoscaling/v2`, CPU utilisation 70%).
* `deploy/kubernetes/`: the earlier plain manifests (namespace, configmap, secret, services, postgres, ingress, hpa).

### 14.5 The FlexaScale Helm chart (`helm/flexascale`, chart 0.5.1, image 0.6.0)

| Template | Creates | Notes |
|---|---|---|
| `policy-configmap.yaml` | The application policy as a file | From `values.policy` |
| `operator-deployment.yaml` | The operator (1 replica, `Recreate` strategy, non-root, read-only file system) | Selector includes the release name (fixed in 0.5.1 so two releases never select each other's pods) |
| `rbac.yaml` | ServiceAccount, Role, RoleBinding | **Observe mode: read-only.** Live mode adds patch on Deployments and HPAs, `deployments/scale`, Lease create/update, the ownership ConfigMap |
| `handback-hook.yaml` | A Job that runs before upgrade, rollback and uninstall | Scales the operator to 0 and waits, so it restores HPAs and releases the Lease while it still has permissions |
| `api-*.yaml` | Legacy REST API | Disabled by default |

Verified: the lifecycle script (`scripts/helm_lifecycle_test.sh`) installed, upgraded, rolled back and uninstalled the
chart for the bookstore app and passed 33/33 checks; the shop's own release was upgraded 0.4.1 → 0.5.1, rolled back and
upgraded again with the shop and its database volume preserved (`logs/helm_*`).

### 14.6 `fsctl` — one command for everything

`./fsctl start` runs eight checked steps (`lab/launcher.py::cmd_start`): 1 tools, 2 Docker and Minikube, 3 namespaces and
workloads ready, 4 shop ingress reachable, 5 monitoring and model, port-forwards, 6 Prometheus targets and metrics, 7
FlexaScale prerequisites and **controller ownership** (no frozen HPA, no Lease held), 8 the control center. Each step
stops with a clear message and a fix if it fails. `./fsctl stop` stops the lab, Locust and the operator, restores every
HPA and verifies no Lease is held. `./fsctl status` prints who owns scaling.

---

## 15. Locust and the benchmarking method

### 15.1 Locust

**Locust** is a load-testing tool: you write Python classes describing *users*; Locust starts many of them and records
every request's response time and success.

* A **user** (virtual user) is a loop: pick a task by weight, perform its HTTP requests, wait (`wait_time`), repeat.
  Locust is **closed-loop**: a user waits for each response before continuing, so a slow shop also receives fewer
  requests. That is why throughput must be compared at the same offered load.
* **Spawn rate**: users started per second. **Peak users**: maximum simultaneous users.

User journeys (`load-testing/locustfile.py`):

| Class | Wait between tasks | What it does (task weights) |
|---|---|---|
| `BrowsingUser` | 1–3 s | List products (5), search (3), product detail + reviews + recommendations (4), categories (2) |
| `ShoppingCustomerUser` | 1.5–4 s | Logs in once at start; add to cart and view (4), checkout (2), wishlist (2), shipping quote (1), order history (1) |
| `FlashSaleUser` | 0.1–0.5 s | Rapid checkout of the same top products (stock contention) |
| `FailedCheckoutUser` | 1–3 s | Checkout with a card that is declined (tests rollback) |
| `HighLatencyPaymentUser` | 1–2.5 s | Checkout with 300 ms simulated payment delay |

Scenarios (`load-testing/scenarios.py`, chosen with environment variables `FLEXASCALE_SCENARIO`, `FLEXASCALE_USERS`,
`FLEXASCALE_SPAWN_RATE`, `FLEXASCALE_DURATION`):

| Scenario | User mix (relative weights) | Shape over time |
|---|---|---|
| `steady_browsing` | Browsing 8, Shopper 2 | Constant peak |
| `gradual_ramp` | Browsing 6, Shopper 4 | Six equal steps up to the peak, then a plateau |
| `flash_sale` | Browsing 4, Shopper 2, FlashSale 4 | 20% of peak for the first 25%, peak until 65%, back to 20% |
| `checkout_heavy` | Browsing 2, Shopper 7, FlashSale 1 | Constant peak |
| `traffic_drop` | Browsing 6, Shopper 4 | Peak for 45%, then 10% |
| `payment_degradation` | Browsing 3, Shopper 3, SlowPayment 3, DeclinedPayment 1 | Constant peak |

Example: flash sale, 25 users, 300 s → 5 users for 75 s, 25 users until 195 s, then 5 users. Each phase change is
printed as `FLEXASCALE_PHASE <name> <users>` in the Locust log, which the lab turns into timeline markers.

Locust writes three CSV files per run (columns explained in the viva guide): `locust_stats.csv` (whole-run totals per
request name and an `Aggregated` row), `locust_stats_history.csv` (a row every few seconds with percentiles of a recent
~10 s window), `locust_failures.csv` (errors by type).

### 15.2 How one experiment runs (`lab/experiments.py`)

1. **Preflight:** check the app; restore any HPA left frozen or modified by an earlier run.
2. **Comparable start** (`_reset_app_data`, `_reset_replicas`): restock inventory to 5,000, empty test carts, freeze every
   HPA at its minimum, scale every service to its minimum, wait until all pods are ready, wait until the previous run's
   load ended at least 300 s ago (so the HPA has no memory of it), restore the HPAs, and verify the replicas stay settled.
3. **Configure the controller:** for `hpa_fast`/`hpa_tuned`, patch every HPA's behaviour/target (originals saved).
4. **Start the operator** (live / live + Auto / observe for shadow) and **Locust**.
5. **Sample every 5 s** (`_sample`): Deployments and HPAs, telemetry of every service, the latest Locust window, new
   operator decisions (turned into events), and the host's CPU and battery state. The watchdog (`_check_operator`) runs
   with each sample for FlexaScale and Auto runs.
6. **Teardown:** stop Locust and the operator, restore every HPA (bounds, behaviour, target), verify no frozen HPA and no
   live Lease → `cleanup.safe`.
7. **Finalize:** compute the summary (Section 18) and write `run.json`, `telemetry.csv`, `decisions.jsonl` and Locust's
   CSVs into `reports/experiments/<run id>/`.

### 15.3 How controllers were compared fairly

* **Paired runs:** a candidate run is compared only with a baseline run of the same app, scenario, users, spawn rate and
  duration, both from a settled start (`Lab.compare` lists any difference as an "issue" and then hides percentages).
* **Pre-registration:** for the v7 and v9 studies, the rules (calibration of the tuned HPA, validity, statistics, verdict
  table) were written in `docs/POLICY_V7.md` / `docs/POLICY_V9.md` *before* the first run, with a time-stamped record of
  everything that happened afterwards. This prevents choosing the analysis after seeing the results.
* **Block design:** 12 blocks (6 scenarios × 2 repeats); in each block all four arms ran back to back in an order drawn
  from a fixed random seed, so slow changes of the laptop affect every arm alike.
* **Validity rule (fixed in advance):** ≥ 95% of the duration completed, settled start, cleanup safe, AC power in every
  sample, and the CPU used outside Kubernetes during the load ≤ idle baseline + 2.0 cores (`scripts/check_host_load.py`).
  An invalid run is rerun once; invalid runs are kept in `reports/experiments_invalid/` with the reason.
* **Statistics:** for each metric, the per-pair difference Δ% = 100 × (candidate − reference) / reference; the mean over
  pairs with a 95% Student-t confidence interval (Section 18).
* **Verdict table** (fixed before the runs, `docs/POLICY_V7.md` §3.5): "beats on cost" needs C1 replica-hours interval
  below 0, C2 p95 not worse (mean ≤ +10% and interval not entirely above 0), C3 failures not worse, C4 throughput mean ≥
  −2%, C5 end-to-end SLO violation mean ≤ +5 s, C6 oscillations ≤ +5, and C7 replica-hours lower in at least 4 of 6
  scenarios. "Beats on performance", "worse" and "on par / inconclusive" are defined similarly.
* **References:** the *tuned* HPA was the primary reference (it is the fair one); the default HPA was secondary.

---

## 16. The dashboard

The control center runs at `http://127.0.0.1:8090/` (`lab/server.py` serves the built React app and a JSON API; the
React code polls the API every few seconds). A full operating manual is in
`docs/learning/FLEXASCALE_DASHBOARD_COMPLETE_GUIDE.md`; this section explains every page and what happens behind its
controls.

**Global rules.** A missing value is shown as "—", never as 0 or an estimate; "no requests" means the service was
measured and served zero requests. The header shows the running experiment, telemetry age, cluster and Prometheus status,
the application selector (shop or bookstore) and a light/dark switch.

### 16.1 Overview

| Element | Shows | Source |
|---|---|---|
| Active controller card | HPA when idle; otherwise the running controller, scenario and time | `/api/lab/overview` |
| Cluster card | Ready nodes, context, Prometheus up/down | `kubectl`, Prometheus `/-/ready` |
| End-to-end SLA card | Locust p95 of the latest ~10 s window vs 1000 ms | Locust history CSV |
| Replicas card | Ready / desired, the 48-replica budget, a sparkline | Discovery |
| Mean CPU card | Mean CPU % of request over reporting services | Telemetry |
| Estimated cost rate | $/hour of what is allocated now (ready replicas × requests × prices) | Cost profile |
| Workload strip | Throughput, p50, p90, p95, p99, error rate, SLA time violated, mean memory | Latest Locust window |
| Compact timeline | Section 16.3 | `/apps/{app}/live` and history |
| Topology | Services, owner colour, CPU, replicas; click for details | Discovery + telemetry |
| Alerts | Prometheus unreachable, latency above SLO, CPU pressure ≥ 85%, 5xx > 5%, HPA left frozen, Lease held outside a run, budget nearly used, fallback happened, cleanup not verified | Live state only |
| Benchmark verdict | Newest pooled comparison with 95% CIs and verdict; "Preliminary" below 6 pairs | `lab/benchmark.py` |
| Cost per experiment | Replica-hours of the last 30 runs | Run summaries |

### 16.2 Live lab (running experiments)

Controls and what each does when you press **Start** (`POST /api/lab/experiments`):

| Control | Backend effect |
|---|---|
| Mode: Native HPA / FlexaScale / Auto / Native HPA 60 s / Native HPA tuned | Chooses `controller`: `hpa`, `flexascale` (operator `--mode live`), `auto` (`--mode live --auto`), `hpa_fast`, `hpa_tuned` (HPAs patched for the run) |
| FlexaScale policy | Default or a variant from `config/lab.yaml` (v5, v7, v9, rules, `verify_sla_risk`) → which policy file the operator loads |
| Workload scenario, peak users, spawn/s, duration | Environment variables for Locust |
| Comparable start | Section 15.2 step 2 |
| FlexaScale shadow mode (HPA modes) | Operator in observe mode; proposals logged as "would propose" |
| Start | Refused if a run is active, Locust or the operator is still running, or a Lease is held |
| Stop → confirm | `POST /api/lab/experiments/stop`: stop processes, restore HPAs, check Lease |

Right column: run header and progress; tiles (elapsed, users, throughput, error rate, p50/p95 with p90/p99, replicas
ready/desired, E2E SLA met/violated); a red **fallback banner** if the watchdog acted; the whole-run result after the run;
the Live Autoscaling Timeline with per-service replica strips; CPU and memory per service; a services table (owner,
ready/desired, HPA range — "frozen; was 1–10" while FlexaScale holds it —, CPU, memory, req/s, latency, p95 with "≥" for
capped values, telemetry status); the FlexaScale policy panel (*proposal batches*, *applied scale requests*, *safety
interventions*); and the event log (preflight, ownership, workload, traffic, metric, policy, scale request, replica
change, ready, safety, auto, fallback, warning, error).

**Policy per laptop:** each model was fitted to one laptop. The default v9 holds every service at its minimum on the
Fedora laptop, so for a visible FlexaScale demo there, choose policy **v7**.

### 16.3 The Live Autoscaling Timeline

Lanes: events (⚡ phase, ◆ FlexaScale scale request, ⇄ Auto handoff, ▲ safety intervention, red ▲ fallback, red bars SLA
violation); **replicas** (white line = desired, teal area = ready, green dashed = FlexaScale proposal — not an action —,
dotted = HPA proposal or, when frozen, the HPA-rule estimate, ▲/▼ = observed changes, owner band beneath); traffic
(Locust req/s and users); latency (p50, p95, the 1000 ms SLO line). Controls: service selector, window (1/5/15 min, All,
or Run), CPU/memory overlay, pause; replays add play/pause, 1×/4×/16× and a scrubber. Gaps mean no telemetry; nothing is
interpolated.

How to read a FlexaScale scale-up: phase marker → req/s rises → CPU rises → green proposal steps up → ◆ appears (safety
approved, request sent) → white desired line steps up with ▲ (Kubernetes accepted) → about 10 s later the teal ready area
reaches it → latency falls. Under native HPA there is no ◆; the dotted HPA line moves first.

### 16.4 Auto mode page

The explanation card (with the HPA formula at the target Auto actually uses), a timeline of the current or last Auto run
with the owner band, four **rule cards** (condition, immediate or after 2 steps, how many decisions each rule made and
its share), the **per-service ownership table** (owner, rule, logged reason, FlexaScale and HPA *recommendations* — not
actions —, desired/ready, CPU, memory, latency/SLO, confidence, telemetry status, last change), the ownership-change list
and the active `auto:` configuration.

### 16.5 Comparison, Experiments, Topology, Models

* **Comparison:** reference (default or tuned HPA), candidate dropdown, verdict badge with the rule printed, tiles with
  mean Δ and 95% CI (replica-hours, cost, p95, failures, throughput), the by-scenario chart, the pairs table, and a manual
  base/candidate comparison of any two runs with every metric (percentages hidden if not comparable).
* **Experiments:** filter by controller, scenario, label (e.g. `v9-b04`, `verify-auto`) and "valid only"; each run's
  configuration, whole-run result, cleanup and a replay.
* **Service topology:** the 25-edge call graph the GNN uses; click a node for details.
* **Models:** the deployed model (path, type, actions, observation, compatibility "16 services ≤ 20 slots", inference
  status, SHA-256), held-out simulation tables (v4–v6), and model cards (v7/v9 with training, validation and gate).

---

## 17. End-to-end walkthrough of one decision

A flash-sale run in Auto mode at 40 users, following one request and one decision.

1. **A user acts.** A Locust `FlashSaleUser` posts `POST /api/orders/checkout` to the ingress → `api-gateway` →
   `order-service`, which calls cart, catalog, shipping, fraud, inventory, payment and notification, and uses PostgreSQL.
2. **Services count it.** Each service's middleware increments `http_requests_total{..., status="200"}` and records the
   duration in its histogram. The kubelet's cAdvisor accumulates the pod's CPU seconds.
3. **Prometheus scrapes** cAdvisor every 10 s and the services every 15 s.
4. **The operator step begins** (every 10 s). It renews the Lease `flexascale-shopping`.
5. **Discovery:** 16 Deployments, each with its HPA, requests and limits.
6. **Telemetry:** batched PromQL over the last minute → order-service `cpu_pct 86.8`, `request_rate 2.6`,
   `latency_mean_ms 172` (numbers from the real step-4 record of run `035531`).
7. **Features:** `FeatureTracker.update` → `[0.1736, 0.104, 1.0, 0.0, 0.1, 1.0, 0.4133, 1.0, 1.0, 1.0]`.
8. **Graph:** 25 edges from the policy; `pack` builds 640 numbers; 16 focal rows of 660.
9. **GNN:** input projection, two message-passing rounds (order-service hears from api-gateway and its seven callees),
   readout [own, pooled].
10. **PPO actor:** probabilities (1%, 48.79%, 48.83%, 1.37%, 0%) → action +1, confidence 0.4883.
11. **Safety guards:** proposal 1 → 2 within bounds and budget; ready = desired; no recent scale-up → accepted.
12. **Auto:** HPA's recommendation at the controlled variant's 70% target is `ceil(1 × 86.8 / 70) = 2`; CPU 86.8% ≥ 60%
    is "at risk", but HPA (2) does not want *more* than FlexaScale (2), so rule 4 (efficiency): FlexaScale keeps it.
13. **Execution:** lock acquired; `kubectl patch hpa order-service-hpa` to min = max = 2 (original 1–10 saved in
    annotations); `kubectl scale deployment/order-service --replicas=2`.
14. **Kubernetes** creates a pod; desired = 2 is observed 6.1 s later; the pod passes `/readyz`; ready = 2 after 16.1 s.
15. **Logging:** the full decision record (inputs, probabilities, owner, rule, reasons, applied = true) is appended to
    `decisions.jsonl`; the status file is rewritten (the watchdog's heartbeat).
16. **The lab samples** every 5 s and turns the new decision into "Policy" and "Scale request" events; it detects the
    desired change ("Replica change") and the ready change ("Ready").
17. **The dashboard** polls the lab and draws the green proposal step, the ◆ marker, the white desired step with ▲ and
    then the teal ready area rising.
18. **Next steps:** CPU per pod falls; cooldowns prevent another change for 20–30 s; later, when the spike ends, the
    policy proposes −1 and, after the cooldown, the service returns to 1 (in this run at +259 s and +289 s).
19. **End of run:** Locust and the operator stop; every HPA is restored to 1–10; the Lease is released; `cleanup.safe =
    true`; the run files are written.

---

## 18. All important formulas and design decisions

### 18.1 Formulas

| Quantity | Formula | Where in code |
|---|---|---|
| HPA desired replicas | `ceil(r × u / u*)`, no change if `|u/u* − 1| ≤ 0.1`, scale-up ≤ max(2r, r+4) | `auto_mode.hpa_recommendation`, `twin_control.NativeHPA` |
| CPU % of request | `100 × (Σ pod cores / pods) / request per pod` | `workload_metrics.collect` |
| Mean latency | `1000 × rate(duration_sum) / rate(duration_count)` | same |
| Histogram percentile | linear interpolation inside the bucket that reaches rank `q × total` | `histogram_quantile` |
| Feature 0 | `cores / ready / limit` | `FeatureTracker.update` |
| Feature 3 | `log₂(latency / min latency over 30 min)` | same |
| Feature 6 | `log₁₀(EMA of 1000 × cores / rps) / 3`, EMA weight 0.2 on the new value | same |
| Message passing | `h ← (h + ReLU(LN(W_s h + W_out · mean_callees + W_in · mean_callers))) ⊙ m` | `GraphExtractor.embed` |
| Softmax | `p_a = e^{z_a} / Σ_b e^{z_b}` | SB3 categorical distribution |
| Reward (global) | `−0.1 × (Σ(r−r_min) + 6·min(4, p95/p95₀ − 1)⁺ + 10·v + 5·f + 0.25·c)` | `twin_env.reward_v7` |
| Return | `G_t = Σ_k γᵏ r_{t+k}`, γ = 0.97 | SB3 |
| GAE | `Â_t = Σ_l (γλ)ˡ δ_{t+l}`, `δ_t = r_t + γV(s_{t+1}) − V(s_t)`, λ = 0.95 | SB3 |
| PPO objective | `E[min(ρÂ, clip(ρ, 1−ε, 1+ε)Â)]`, ε = 0.1 (fine-tune) | SB3 |
| PPO loss | `−L_clip + 0.5 · value MSE − 0.01 · entropy` | SB3 |
| Replica-hours | `Σ_samples Σ_services ready × Δt / 3600` (left Riemann sum, 5 s samples) | `evaluation/cost.summarize_resources` |
| Allocated vCPU-hours | `Σ ready × CPU request × Δt / 3600` | same |
| Estimated cost (USD) | `allocated vCPU-h × 0.04048 + allocated GiB-h × 0.004445` | same |
| CPU allocation efficiency | `100 × used vCPU-h / allocated vCPU-h` | same |
| Scaling events, oscillations | count of desired-replica changes; count of direction reversals (up→down or down→up), per service, summed | `scaling_stability` |
| SLO violation seconds | `Σ Δt` over samples whose Locust p95 > 1000 ms | `Experiment._finalize` |
| Paired difference | `Δ% = 100 × (candidate − reference) / reference` | `percent_change` |
| 95% CI of the mean | `mean ± t(0.975, n−1) × s / √n` | `benchmark.mean_ci` |
| Effect size | `d_z = mean Δ / s` | `scripts/analyze_v7.py` |

### 18.2 Design decisions and why

| Decision | Reason | Alternative rejected |
|---|---|---|
| Control replicas through the Kubernetes API from outside | Works with any application, no code change (O1) | Modifying the app or Kubernetes |
| Keep the HPA and **freeze** it rather than delete it | The safety net is always there; restoring is one patch | Deleting/recreating HPAs (risky if the operator dies) |
| A **Lease** per application | Two FlexaScale instances can never fight | Trusting there is only one operator |
| `observe` as the default mode | Nothing changes unless someone asks for live control | Live by default |
| Unit-free features | A policy trained in a simulator must read the same numbers live | Raw CPU %, raw req/s (v1–v3 failed this way) |
| CPU relative to the **limit** | Pods saturate at the limit, not the request | CPU % of request (v5 saw it capped at 100%) |
| Latency relative to each service's own baseline | User login is normal at 1 s; one SLO for all is wrong | One absolute SLO (v1–v3) |
| Focal (per-service) decisions with per-service rewards | Each service gets credit for its own decision | One joint decision and one shared reward (tried, stopped) |
| Two message-passing rounds, mean aggregation, directed weights | Two hops reach the checkout fan-out; mean avoids domination by high-degree nodes | Deeper GNN (more data and training needed); sum aggregation |
| Actions −1…+3 | Scale up fast, scale down slowly (asymmetric risk) | ±1 only (falls behind on ramps, seen in v5) |
| Warm start by imitation, then PPO | PPO from scratch learned "scale everything up" or failed to match a simple rule | PPO from scratch |
| Application twin instead of Alibaba replay | The policy must learn *this* shop's dynamics; checked against live runs | Generic trace simulators (v1–v6 did not transfer) |
| Fixed reward weights | Results attributable; training stable | Adaptive weights by traffic phase (Phase 2 design; not implemented) |
| Auto's "capacity first" rule | Under risk, the more generous controller wins | Always trust the policy |
| Pre-registered evaluation with a tuned baseline | Prevents cherry-picking; a default HPA is an easy target | Reporting the best runs against default HPA |

---

## 19. Results, contribution, limitations and future work

The viva guide explains every metric and number in depth; here are the results you must know, with sources.

### 19.1 What kind of value each result is

* **Measured, live:** Locust and Prometheus numbers from runs on the real cluster (`reports/experiments/`).
* **Calculated:** derived from measurements (replica-hours, Δ%, confidence intervals).
* **Estimated:** cost in USD (list prices × allocated resources; not a bill).
* **Simulated:** twin results (rewards, T1–T3 tables, validation) — never presented as live results.

### 19.2 Functional verification (live, Fedora laptop, 2026-10-31)

| Claim | Status | Evidence |
|---|---|---|
| Native HPA mode with FlexaScale in shadow | Verified | `20261031-001033` |
| FlexaScale mode: Lease, freeze, ownership, safety | Verified | `…-001628`, `…-032758`, `…-040706` |
| FlexaScale mode: an applied scale change | Verified earlier (`20261028-061846`) and on the second laptop (E2); **not** in the 2026-10-31 runs (policies held 1 replica) | `results/RESULTS.md` §9 |
| Auto selects FlexaScale and applies scaling | Verified | `…-002805` |
| Mixed ownership under SLA risk | Verified (controlled variant) | `…-035531` |
| Fallback on telemetry loss | Verified | `…-030452` |
| Fallback on operator crash | Verified | `…-031625` |
| No two controllers on one Deployment; cleanup safe | Verified in all 9 runs | `results/verification/*.json` |
| Helm install/upgrade/rollback/uninstall | Verified (33/33) | `logs/helm_lifecycle_0.5.1.linux.out` |
| Tests | 373 passed | `logs/pytest_final_2026-10-31.out` |

### 19.3 The honest finding from verification

At 40 users on the Fedora laptop, order-service's latency rose about tenfold while its CPU stayed at 30–50% of its limit
(database waits inside its event loop). Both learned policies read mainly CPU relative to the limit, so they held one
replica; the default HPA, whose 70%-of-request target is only 14% of the limit, added replicas. In Auto mode, the default
SLA-risk threshold (400% of request, calibrated on the second laptop) did not hand these services to the HPA, and the
shop has no per-service latency SLO; with a controlled threshold of 60% it did. The default Auto verification run had
7.1% failures and an end-to-end p95 of 6 s at 40 users. **Lesson: an autoscaler is only as good as the signal it reads
and the thresholds calibrated for its machine.**

### 19.4 Version history results (all live comparisons against default HPA unless stated)

| Version | Result | Source |
|---|---|---|
| v1 | Trained on mis-scaled data (CPU fractions); its early "benchmark" used an untrained network head and was **withdrawn** | `reports/shopping_benchmark_report.md` (marked withdrawn) |
| v3 | +77.5% replica-hours (3 pairs, preliminary): heavy over-provisioning | `reports/live_benchmark_report.md` |
| v4 | +6.0% replica-hours, on par (6 pairs) | same |
| v5 | +8.0% replica-hours, worse (12 pairs) | same |
| v6 Auto | −3.9% replica-hours [−6.5, −1.3] (18 pairs), "beats on cost" — later found to be partly a CPU power-profile confound | same; `docs/V7_REPORT.md` |
| v7 vs tuned HPA (first batch) | Auto appeared to beat tuned HPA on p95 (−21.6%) — **withdrawn**: the laptop's balanced power profile made the shop faster whenever FlexaScale's control kept the host busy | `docs/V7_REPORT.md` §4.1 |
| v7 vs tuned HPA (clock-controlled replication, 48 runs) | On par: RL and Auto replica-hours +0.1%, Auto p95 +0.1% [−9.3, +9.5] | `reports/v7/replication.md` |
| v9 (second laptop, 46 valid runs) | vs default HPA: RL −7.3% [−11.5, −3.2], Auto −7.7% [−12.3, −3.2] replica-hours, but p95 check failed → on par / inconclusive. vs tuned HPA: +0.3% / +0.2% → on par | `reports/v9/evaluation.md` |

### 19.5 The v9 evaluation in detail (second laptop, 25 users, 300 s)

| Arm | Runs | Replica-h | Cost USD | p50 ms | p95 ms | p99 ms | Failures % | req/s | SLO viol. s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Default HPA | 12 | 1.512 | 0.00685 | 44 | 241 | 838 | 0.29 | 15.13 | 22.9 |
| Tuned HPA (350%, 60 s) | 12 | 1.366 | 0.00618 | 42 | 167 | 510 | 0.25 | 15.37 | 8.0 |
| FlexaScale RL | 11 | 1.368 | 0.00619 | 37 | 395 | 1674 | 0.34 | 15.07 | 25.6 |
| FlexaScale Auto | 11 | 1.365 | 0.00618 | 37 | 200 | 1936 | 0.32 | 15.15 | 15.7 |

Where the saving comes from: **flash sale** (E1: Auto −22.9% replica-hours and p95 −51.2% vs default HPA; E2: RL −20.1%
and −64.5%) because the default HPA kept spike capacity for its 5-minute window; **checkout-heavy** (E3/E4: −15.3% /
−13.8%) because the default HPA scaled services for brief CPU rises, at a p95 cost of about +6%. The tuned HPA achieved
the same savings without a model.

### 19.6 Research contribution (stated carefully)

1. A **safe, explainable, installable framework** for learned autoscaling on Kubernetes: per-service Auto arbitration
   between a learned policy and the native HPA, exclusive ownership (Lease + HPA freeze), verified fallback in every tested
   failure, and a decision log that explains every step.
2. A **dependency-aware graph policy** over the real call graph with per-service credit, trained in an application twin
   fitted to live measurements and checked for fidelity.
3. A **fair, pre-registered evaluation** against both default and calibrated HPA, which found savings against the default
   HPA and **parity** against the tuned one, plus a graph ablation showing no measurable benefit of the graph here.
   Reporting these negative and null results, and the confounds found and withdrawn, is part of the contribution.

What is **not** claimed: that FlexaScale beats a tuned HPA; that the flash-sale advantage over default HPA holds
statistically (single pairs); that results transfer to larger clusters or heavier loads.

### 19.7 Limitations

Single-node Minikube on laptops; 25–40 users; 300 s runs; one main application; per-laptop calibration (twins and
thresholds do not transfer); policies read mainly CPU; large run-to-run variance; costs are estimates; demo credentials in
the shop chart; online learning, adaptive reward weighting and PyTorch Geometric from the Phase 2 design are not
implemented.

### 19.8 Future work

Latency-aware inputs and SLA-risk rule; automatic per-cluster calibration; stronger baselines (per-service tuned HPA,
custom-metric HPA); multi-node clusters and heavier loads; safe online adaptation in shadow mode with the same gate;
publication on fair evaluation of learned autoscalers.

---

## 20. Implementation status table

| Feature | Status |
|---|---|
| Discovery, telemetry, features, graph policy inference, safety guards, Lease, HPA freeze/restore, decision log | Implemented, verified live |
| Auto mode (all four rules, dwell) | Implemented; rules 1, 3, 4 verified live; rule 2 not exercised (thresholds 0) |
| Lab watchdog | Implemented, verified live (SIGKILL) |
| Dashboard (7 pages, timeline, replays) | Implemented, used live |
| Helm chart with RBAC and hand-back hook | Implemented, verified (33/33) |
| Bookstore (second application, inferred topology) | Implemented; used for deployment tests, not for performance evaluation |
| Training pipeline (twin, imitation, PPO, selection, gate) | Implemented; v7 and v9 produced |
| Traffic-based graph inference | Implemented; not used for the shop (fixed topology) |
| Confidence-based hand-back (non-Auto mode) | Implemented; disabled in the shop's policy (thresholds 0) |
| Legacy operator/API (4-service prototype), PyG GNN, v1–v6 simulators | Historical |
| Online PPO learning on the live cluster | Planned, not implemented |
| Adaptive reward weighting by traffic phase | Planned (Phase 2 design), not implemented |
| Multi-node cluster evaluation | Not done |
| Vertical scaling | Out of scope |
