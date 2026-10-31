# FlexaScale — The Complete Guide

*Everything about the FlexaScale final-year project in one document: how it works from zero, and everything you need
for the viva (every term, code walkthroughs, every metric and every number in the results, the papers, the bugs, the
questions). How to operate the dashboard is in its own file, `docs/learning/FLEXASCALE_DASHBOARD_COMPLETE_GUIDE.md`.*

**How to read it.** Read **Part One** from start to finish first: it assumes you know nothing about the project,
Kubernetes or reinforcement learning. Use **Part Two** to study for the viva; it goes deeper on every metric, number and
design question. Keep the dashboard guide (`FLEXASCALE_DASHBOARD_COMPLETE_GUIDE.md`) open while you use the dashboard.

**How it was written.** Every statement was checked against the source code, configuration files, model cards, raw
experiment files and reports in this repository (October 2026), and file paths are given so you can open the code
yourself. Four labels are used throughout:

| Label | Meaning |
|---|---|
| **Implemented** | In the code and used by the running system |
| **Verified live** | Implemented *and* shown working on the real Kubernetes cluster, with the evidence named |
| **Experimental / historical** | In the repository but not used by the final system (kept for reproducibility) |
| **Planned / not done** | Proposed in the design phase or future work; not in the code |

Values are also labelled as **measured** (live cluster or Locust), **calculated** (derived from measurements),
**estimated** (cost from list prices) or **simulated** (application twin). Anything that could not be verified is marked
**unverified**. Where FlexaScale did not win, this document says so.

## Overall contents

* [Part One — How FlexaScale works](#part-one--how-flexascale-works) (Sections 1–20)
* [Part Two — Viva preparation](#part-two--viva-preparation) (Sections A–J: glossary, analogies, code walkthroughs,
  components, diagrams, **results and metrics masterclass**, papers, bugs, questions and answers, talk scripts)

---

# Part One — How FlexaScale works

## Contents of Part One

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

Locust writes three CSV files per run (columns explained in Part Two, Section F.3): `locust_stats.csv` (whole-run totals per
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
React code polls the API every few seconds). The full operating manual is `docs/learning/FLEXASCALE_DASHBOARD_COMPLETE_GUIDE.md`; this section explains every page and what happens behind its
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

Part Two (Section F) explains every metric and number in depth; here are the results you must know, with sources.

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

---

# Part Two — Viva preparation

## Contents of Part Two

* [Section A — Glossary: every term in simple English](#section-a--glossary-every-term-in-simple-english)
* [Section B — Analogies for the difficult ideas](#section-b--analogies-for-the-difficult-ideas)
* [Section C — Code walkthroughs, line by line](#section-c--code-walkthroughs-line-by-line)
* [Section D — Every component: input, processing, output, why, and what if it were missing](#section-d--every-component)
* [Section E — Diagrams and flowcharts](#section-e--diagrams-and-flowcharts)
* [Section F — Results and metrics masterclass](#section-f--results-and-metrics-masterclass)
* [Section G — Research papers and novelty](#section-g--research-papers-and-novelty)
* [Section H — Mistakes, bugs, debugging and troubleshooting](#section-h--mistakes-bugs-debugging-and-troubleshooting)
* [Section I — Viva questions and answers](#section-i--viva-questions-and-answers)
* [Section J — Explaining the project in 2, 5, 10 and 15 minutes](#section-j--explaining-the-project-in-2-5-10-and-15-minutes)

---

## Section A — Glossary: every term in simple English

Alphabetical. "→" points to where the term matters in FlexaScale.

| Term | Simple meaning | In FlexaScale |
|---|---|---|
| **Ablation** | Remove one part of a system and measure the difference, to see what that part contributes | The no-graph policy (`use_graph=False`) → graph showed no measurable benefit |
| **Action** | What an RL agent does at one step | Replica change −1, 0, +1, +2, +3 for one service |
| **Action head** | The last layer that turns features into action scores | 64 → 5 logits |
| **Actor** | The part of an actor-critic network that chooses actions | 128 → 64 (tanh) → 5 |
| **Actor-critic** | An RL design with a decision network (actor) and a judging network (critic) | SB3 `ActorCriticPolicy` |
| **Adam** | A popular gradient-descent optimiser that adapts the step size per weight | Used by SB3 and the warm start |
| **Adjacency matrix** | A table with a 1 where node i connects to node j | 20 × 20, `A[i, j] = 1` if i calls j |
| **Advantage** | How much better an action was than expected in that state | GAE with γ 0.97, λ 0.95 |
| **Aggregation** | Combining many neighbours' messages into one | Mean over callees, mean over callers |
| **Allocated resources** | What the scheduler reserves (requests), whether used or not | vCPU-hours = ready replicas × 0.1 core × time |
| **Annotation** | A free-text key/value note on a Kubernetes object | `flexascale.io/original-min-replicas` stores the HPA bounds while frozen |
| **API (application programming interface)** | A defined way for programs to talk | Kubernetes API, the lab's `/api/lab/...` |
| **Argmax** | The position of the largest value | The action with the highest probability (live decision) |
| **Auto mode** | FlexaScale's per-service choice between itself and native HPA | `operator/auto_mode.py` |
| **Autoscaling** | Changing capacity automatically with load | Horizontal, replicas only |
| **Back-pressure** | Slowness of a downstream service making its callers slow | Why the call graph matters |
| **Baseline** | What a new method is compared against | Default HPA (70%, 300 s) and tuned HPA (350%, 60 s) |
| **Batch / mini-batch** | A group of samples used for one gradient step | 512 decisions per mini-batch |
| **Behaviour cloning (imitation)** | Training a network to copy a teacher's actions | Warm start from `limit_target(0.6/0.3)` |
| **Block (experimental design)** | A group of runs done back to back under the same conditions | 12 blocks × 4 arms in the v9 study |
| **Bucket (histogram)** | A range of values that a histogram counts | Latency buckets 5 ms … 10 s |
| **Burstiness** | How spiky traffic is | Feature 7: log₂(peak / mean rate over 5 min) |
| **cAdvisor** | The part of the kubelet that measures containers' CPU and memory | Source of `container_cpu_usage_seconds_total` |
| **Calibration** | Choosing a parameter by a rule fixed in advance | The tuned HPA target (350% / 250%) |
| **Call graph** | Which service calls which | 16 nodes, 25 edges |
| **Categorical distribution** | Probabilities over a fixed set of choices | Softmax over 5 actions |
| **Checkpoint** | Saved network weights at one point in training | `best_model.zip` |
| **Churn** | Changing replicas often | Reward term 0.25 per change |
| **Clip range (ε)** | PPO's limit on how far the probability ratio may move per update | 0.2 from scratch, 0.1 after warm start |
| **Closed-loop load** | Users wait for each response before the next request | Locust; a slow shop gets fewer requests |
| **Cluster** | A group of machines run by Kubernetes | Single-node Minikube |
| **Comparable start** | Every run starts from the same settled state | Data reset, all services at 1 ready replica |
| **Confidence** | The policy's probability of the action it chose | e.g. 0.4883 |
| **Confidence interval (95%)** | A range that would contain the true mean in 95% of repetitions | t-interval over pairs |
| **Confound** | A hidden factor that changes results and is mistaken for the effect | The laptop's power profile (v7 first batch) |
| **Container** | A packaged program with its dependencies | One per pod |
| **Controller (Kubernetes)** | A loop that makes the actual state match the desired state | HPA, Deployment controller, FlexaScale operator |
| **Cooldown** | A waiting time after an action before the next | 20 s after scale-up, 30 s after scale-down |
| **CPU limit / request** | Maximum CPU a container may use / CPU reserved for it | 500 m / 100 m |
| **Critic** | The network part that estimates how good a state is | 128 → 64 (tanh) → 1; training only |
| **Decision log** | One JSON line per service per step | `decisions.jsonl` |
| **Deployment** | "Keep N identical pods" | One per service |
| **Desired replicas** | The count Kubernetes was asked for (`spec.replicas`) | White line in the timeline |
| **Discount factor (γ)** | How much less a future reward counts | 0.97 per 10 s step |
| **Dwell** | Consecutive steps a new choice must persist before it takes effect | 2 steps before Auto hands a service to FlexaScale |
| **Embedding** | A list of numbers that summarises something for a network | 64 numbers per service |
| **Entropy** | How spread out a probability distribution is | Bonus 0.01 to keep exploring |
| **Episode** | One complete simulated run | 300–600 s of simulated load |
| **Exploitation / exploration** | Using the best-known action / trying others to learn | Argmax live / sampling in training |
| **Feature** | One input number | 10 per service |
| **Focal service** | The service a decision is being made for | One-hot vector of length 20 |
| **Freeze (HPA)** | Set an HPA's min = max so it cannot move replicas | Before FlexaScale scales a service |
| **GAE** | Generalised Advantage Estimation, a smoothed advantage | λ = 0.95 |
| **Gate** | A rule a new model must pass before deployment | v9 must beat v7 on validation: −2.47 vs −2.91 |
| **GNN** | Graph neural network: a network that passes information along a graph | `GraphFocalExtractor` |
| **Gradient clipping** | Limiting the size of a training step | Max norm 0.5 |
| **Gymnasium** | The standard Python interface for RL environments | `TwinEnv` |
| **Held-out test set** | Data never used for training or selection | T1, T2, T3 |
| **Helm / chart / release** | Kubernetes package manager / a package / an installed copy | `helm/flexascale` 0.5.1; release `flexascale` |
| **Hook (Helm)** | A job Helm runs at a lifecycle moment | Hand-back before upgrade/rollback/uninstall |
| **HPA** | Horizontal Pod Autoscaler, Kubernetes' built-in CPU-based autoscaler | Baseline and safety net |
| **Hysteresis** | Different thresholds or delays for switching on and off, to avoid flapping | Auto dwell; activation vs deactivation thresholds |
| **Inference** | Using a trained model (no learning) | Every 10 s on the cluster |
| **Ingress** | The HTTP entry point into a cluster | The shop's URL |
| **KL divergence** | A measure of how different two probability distributions are | `target_kl = 0.02` stops large updates |
| **kubectl** | The Kubernetes command-line tool | FlexaScale's `Kube` class wraps it |
| **Latency** | Response time | ms; mean and percentiles |
| **Latency inflation** | Latency relative to a service's own normal | Feature 3, reward term |
| **LayerNorm** | Normalises a vector to mean 0, variance 1 (with learned scale/shift) | In each message-passing round |
| **Lease** | A Kubernetes lock object with an owner and an expiry | `flexascale-shopping`, 30 s |
| **Logits** | Raw scores before softmax | 5 per decision |
| **Mask** | 1 for real items, 0 for padding | 20 node slots, 16 used |
| **Message passing** | Nodes exchanging and combining embeddings along edges | 2 rounds |
| **metrics-server** | Kubernetes component that gives the HPA its CPU numbers | 60 s resolution (second laptop) |
| **Microservice** | A small program doing one job over the network | 16 in the shop |
| **Minikube** | A one-machine Kubernetes for development | Profile `flexascale` |
| **Model card** | A JSON file describing a trained model | `models/flexascale_v9/model_card.json` |
| **Namespace** | A named folder inside a Kubernetes cluster | `flexascale-apps` |
| **Node (graph)** | One item in a graph | A service |
| **Node (Kubernetes)** | One machine in the cluster | One (Minikube) |
| **Observation** | The numbers the agent sees at one step | 660 per focal decision |
| **Observe mode / shadow mode** | FlexaScale computes and logs, changes nothing | Default mode |
| **On par / inconclusive** | The verdict when confidence intervals include zero | FlexaScale vs tuned HPA |
| **Operator** | A program that watches and changes Kubernetes objects | `AppOperator` |
| **Optimistic concurrency** | Updates succeed only if the object has not changed since read (`resourceVersion`) | Lease acquisition |
| **Oscillation** | A reversal of scaling direction | Counted per service per run |
| **Over-provisioning** | More capacity than needed | Wastes replica-hours |
| **p50/p90/p95/p99** | Percentiles: time below which 50/90/95/99% of requests finished | SLO is on p95 |
| **Pairing** | Comparing each candidate run with its own matched baseline run | Same block |
| **Pod** | The smallest unit Kubernetes runs | One service container |
| **Policy** | The decision rule | The neural network |
| **PPO** | Proximal Policy Optimization: RL with clipped, small updates | Stable-Baselines3 |
| **Pre-registration** | Writing the analysis rules before running the experiment | `docs/POLICY_V7.md`, `docs/POLICY_V9.md` |
| **Probability ratio (ρ)** | New probability ÷ old probability of an action | Clipped in PPO |
| **Prometheus / PromQL** | Time-series database / its query language | `rate(...[1m])` |
| **Proposal vs action** | What a controller *would* do vs what was *sent to Kubernetes* | Green dashed line vs ◆ marker |
| **Ready replicas** | Pods that passed their readiness check (`status.readyReplicas`) | Teal area in the timeline |
| **Receptive field** | How far in the graph a node's output can see | 2 hops |
| **Replica** | One copy of a service | 1–10 per service |
| **Replica-hours** | Ready replicas integrated over time, in hours | Primary cost measure |
| **Residual connection** | Adding a layer's input to its output | `h + ReLU(LN(z))` |
| **Return** | Discounted sum of future rewards | What PPO maximises |
| **Reward** | The score after an action | Penalty in replica-equivalents |
| **RBAC** | Role-based access control in Kubernetes | Read-only in observe, write verbs only in live |
| **Rollout** | A batch of experience collected before an update | 5,120 decisions |
| **Scale sub-resource** | The part of a Deployment that holds only its replica count | `kubectl scale` |
| **Scrape** | Prometheus pulling metrics from an endpoint | cAdvisor 10 s, services 15 s |
| **Seed** | The starting number of a random generator; same seed → same randomness | Seeds 1, 2 for training; fixed seeds for test sets |
| **ServiceMonitor** | A Prometheus Operator object that says what to scrape | One per shop service |
| **Settled start** | All services at their minimum and ready before the load begins | Validity rule |
| **SLA / SLO** | Agreement / objective on service quality | End-to-end p95 ≤ 1000 ms |
| **Softmax** | Turns scores into probabilities that sum to 1 | Over 5 actions |
| **Stabilisation window** | HPA uses the highest recommendation of the last N seconds before scaling down | 300 s default, 60 s tuned |
| **Stale telemetry** | Data older than allowed | > 120 s → no FlexaScale decision |
| **Step** | One decision moment | 10 s |
| **Throughput** | Completed requests per second | req/s |
| **Tolerance (HPA)** | Ignore changes when CPU is within ±10% of target | 0.1 |
| **Twin (application twin)** | A simulator fitted to measurements of the real application | `simulator/twin.py` |
| **Under-provisioning** | Less capacity than needed | Raises latency and errors |
| **Unit-free feature** | A ratio or log ratio, with no physical unit | All 10 features |
| **Validation set** | Data used to choose between models (not a fair test) | 40 twin workloads |
| **Value function V(s)** | Expected return from a state | The critic's output |
| **Watchdog** | A monitor that acts when something stops responding | `_check_operator`: restores HPAs |

---

## Section B — Analogies for the difficult ideas

**Kubernetes and replicas — a restaurant.** Each dish station (grill, salad, desserts) is a service; each cook at a
station is a replica. The manager (Kubernetes) keeps the number of cooks you asked for; if one leaves, another is hired.

**HPA — a rule-following floor manager.** Every 15 seconds they look at each station separately: "the grill cooks are
busier than 70% of their reserved effort, add cooks in proportion." They never notice that the dessert station is slow
because the fridge (database) is broken, and after a rush they keep the extra cooks for five more minutes, just in case.

**FlexaScale — an experienced manager who knows the kitchen's flow.** They know that a rush on main courses reaches
desserts later, that some stations are cheap to run and others expensive, and they make decisions for each station
while seeing the whole kitchen. But they are new, so a strict supervisor (the safety layer) checks every hiring decision,
and the rule-following manager stays in the building, ready to take over.

**Auto mode — a shift supervisor choosing who manages each station.** For every station, every 10 seconds: "Is the
experienced manager's information up to date? Are they confident? Is this station at risk, and does the rule-follower
want *more* cooks? If yes, give it to the rule-follower now. Otherwise, after two calm checks in a row, let the
experienced manager run it."

**Freezing the HPA — a key handover.** Only the person holding the station's key may change its staff. FlexaScale takes
the key by setting the HPA's range to exactly one number; it gives the key back by restoring the range written on the
key tag (the annotation).

**The Lease — the duty badge.** Only one FlexaScale manager can wear the badge for a restaurant, and it must be renewed
every shift (30 s). If they stop renewing, the badge expires and someone else can take it.

**Message passing — gossip along the corridors.** In the first round each station hears how its direct neighbours are
doing; in the second round it hears what *they* heard. After two rounds, the dessert station knows the grill is
overwhelmed even though they never talk directly.

**PPO clipping — a cautious driving instructor.** The learner may change their habits after each lesson, but never by
more than a small amount, so one lucky or unlucky lesson cannot ruin everything learned so far.

**Advantage — "better than usual".** Scoring 70 in an exam is great if you usually score 50 (positive advantage) and bad
if you usually score 90. PPO reinforces actions that did better than the critic expected.

**Percentiles — a queue at a ticket office.** p50 is how long the middle person waited; p95 is how long the person at
the 95th place in the "waiting time" ranking waited. Averages hide the few people who waited an hour; p95 and p99 do not.

**Replica-hours — renting chairs.** Two chairs for half an hour and one chair for an hour both cost one chair-hour.

**Pre-registration — writing the marking scheme before seeing the answers.** You cannot change the scheme afterwards to
favour the answer you like.

**A confound — the wrong reason for a win.** Two runners race on different days; one wins, but on their day there was a
tailwind. FlexaScale's apparent win in the first v7 batch came from the laptop running faster (power profile) whenever
FlexaScale was active, not from better scaling.

---

## Section C — Code walkthroughs, line by line

Each snippet is copied from the repository (sometimes shortened with `…`). Read the code, then the numbered notes.

### C.1 Turning telemetry into features — `rl/features_v3.py`, `FeatureTracker.update`

```python
ready_n = max(1, int(ready))                                                    # 1
cpu = None if cpu_cores is None else float(cpu_cores) / ready_n / max(cpu_limit, 1e-6)   # 2
x = np.zeros(F, dtype=np.float32)                                               # 3
x[0] = 0.0 if cpu is None else cpu                                              # 4
prev = self.prev_cpu.get(service)
x[1] = 0.0 if (cpu is None or prev is None) else cpu - prev                    # 5
…
old = [r for t, r in h if now - t >= 0.75 * TREND_S]                            # 6
if rps is None or not old:  x[2] = 1.0
else:
    base = old[-1]
    x[2] = (3.0 if rps > 0 else 1.0) if base <= 0 else float(rps) / base         # 7
rates = [r for _, r in h]
mean = sum(rates) / len(rates) if rates else 0.0
x[7] = math.log2(max(rates) / mean) if rates and mean > 0 else 0.0              # 8
…
if latency_ms and lh:
    base_lat = min(v for _, v in lh)                                            # 9
    x[3] = math.log2(max(latency_ms, 1e-3) / max(base_lat, 1e-3))
x[4] = min(1.0, desired / max(1, self.max_replicas))                            # 10
x[5] = min(1.0, ready / max(1, desired))
if cpu_cores is not None and rps is not None and rps > 1.0:
    est = 1000.0 * float(cpu_cores) / float(rps)                                # 11
    self.cpr[service] = est if service not in self.cpr else 0.8 * self.cpr[service] + 0.2 * est
c = self.cpr.get(service)
x[6] = 0.0 if not c else math.log10(max(c, 1.0)) / 3.0
x[8] = min(1.0, (now - self.last_up.get(service, -1e9)) / 60.0)                 # 12
x[9] = min(1.0, (now - self.last_down.get(service, -1e9)) / 60.0)
return np.clip(np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0), LOW, HIGH)   # 13
```

1. Never divide by zero ready pods.
2. Cores per ready pod as a fraction of the CPU **limit** (`None` stays `None` when telemetry is missing).
3. Ten zeros to fill.
4. Missing CPU becomes 0 here, but the operator never lets a service with missing CPU be owned by FlexaScale (guard 0).
5. Trend = change since the previous decision (10 s ago).
6. Request-rate samples at least 45 s old (0.75 × 60 s).
7. Rate now ÷ rate ~60 s ago; if the old rate was 0 and traffic appears, the maximum 3 is used.
8. Burstiness over the 5-minute history (`BURST_S = 300`).
9. Baseline latency = the lowest latency seen in the last 30 minutes (`BASELINE_S = 1800`); inflation is log₂ of the
   ratio, so 2× slower = 1.0, 4× slower = 2.0.
10. Replica fraction and readiness.
11. CPU-milliseconds per request, smoothed with an exponential moving average (80% old, 20% new), only when there is
    real traffic (> 1 req/s). This "includes idle share": at low traffic it overestimates per-request cost.
12. Time since last scale-up / scale-down, saturating at 60 s.
13. Clean up NaN/∞ and clip every feature to its trained range.

### C.2 Packing the graph — `features_v3.pack`

```python
idx = {s: i for i, s in enumerate(services)}               # services already sorted by the caller
x = np.zeros((n_max, F)); for s in services: x[idx[s]] = features[s]
adj = np.zeros((n_max, n_max))
for u, v in edges:
    if u in idx and v in idx and u != v: adj[idx[u], idx[v]] = 1.0   # caller row, callee column
mask = np.zeros(n_max); mask[: len(services)] = 1.0
return np.concatenate([x.ravel(), adj.ravel(), mask])       # 200 + 400 + 20 = 640 numbers
```

Edges to services that are not present (or self-loops) are ignored, so a partially discovered application still packs.

### C.3 Message passing — `rl/graph_policy.py`, `GraphExtractor.embed`

```python
x, adj, mask = _unpack(obs, self.n_max)                     # (B,20,10), (B,20,20), (B,20)
m = mask.unsqueeze(-1)                                      # (B,20,1) for broadcasting
h = torch.relu(self.inp(x)) * m                             # 10 → 64, padded rows forced to 0
deg_out = adj.sum(-1, keepdim=True).clamp(min=1.0)          # number of callees (≥1)
deg_in  = adj.sum(-2).unsqueeze(-1).clamp(min=1.0)          # number of callers (≥1)
for k in range(self.rounds):                                # 2 rounds
    z = self.self_w[k](h)                                   # own message (with bias)
    z = z + self.callee_w[k](torch.bmm(adj, h) / deg_out) \
          + self.caller_w[k](torch.bmm(adj.transpose(1, 2), h) / deg_in)
    h = (h + torch.relu(self.norm[k](z))) * m               # residual + LayerNorm + ReLU, keep padding at 0
pooled = (h * m).sum(1) / m.sum(1).clamp(min=1.0)           # mean over real services
```

`torch.bmm` is a batched matrix multiply: `adj @ h` gives, for each service, the **sum** of its callees' embeddings;
dividing by the out-degree makes it a **mean**. The transpose swaps rows and columns, so the same operation gives the
mean over callers.

`GraphFocalExtractor.forward` then does:

```python
graph, focal = obs[:, :-self.n_max], obs[:, -self.n_max:]   # 640 | 20-number one-hot
h, _, pooled = self.embed(graph)
own = (h * focal.unsqueeze(-1)).sum(1)                       # picks the focal service's row
return torch.cat([own, pooled], dim=1)                       # 128 numbers
```

### C.4 Running the model live — `rl/policy_runtime.py`, `predict_graph`

```python
services = sorted(features)
obs = features_v3.pack(features, services, edges, self.n_max)            # 640
if self.focal:
    batch = np.concatenate([np.repeat(obs[None, :], len(services), axis=0),
                            np.eye(self.n_max, dtype=np.float32)[: len(services)]], axis=1)  # 16 × 660
    rows = self._distribution_probs(batch)[0]                              # 16 × 5 probabilities
…
for i, s in enumerate(services):
    p = probs[i][0]
    a = int(torch.argmax(p).item())                                       # most likely action
    actions.append(a); confs.append(float(p[a].item()))                   # its probability = confidence
```

`_distribution_probs` calls `model.policy.get_distribution(obs)` inside `torch.no_grad()` (no gradients, inference
only). One batched forward pass decides all 16 services.

### C.5 The guards and ownership — `operator/app_operator.py`, `_decide` (core lines)

```python
telemetry_ok = m.cpu_pct is not None and not m.stale
if not telemetry_ok:
    reasons.append("telemetry_unavailable" if m.cpu_pct is None else "telemetry_stale")
    proposed, owner = current, ControlMode.HPA                            # never act blind
else:
    delta = max(-p.max_scale_down_step, min(p.max_step, self._delta(action, output, idx)))
    proposed = max(lo, min(hi, current + delta))
    record["policy_replicas"] = int(proposed)                             # the policy's own proposal
    if proposed > current and self._planned_total + (proposed - current) > p.max_total_replicas: …budget…
    if proposed > current and workload.ready_replicas < current: proposed = current  # wait for readiness
    if proposed > current and now - self._last_scale_up.get(name, -inf) < p.scale_up_cooldown_seconds: …
    if proposed < current:
        if cpu >= p.scale_down_block_cpu_pct: …blocked_cpu…
        elif memory >= p.scale_down_block_memory_pct: …blocked_memory…
        elif slo and latency > slo: …blocked_slo…
        elif now - self._last_scale_down.get(name, 0) < p.scale_down_cooldown_seconds: …cooldown…
        elif workload.ready_replicas < current: …waiting_for_readiness…
    if self.arbiter is not None:                                          # Auto mode
        dec = self._auto(...); owner = RL if dec.owner == "flexascale" else HPA
    elif …confidence gate with hysteresis…
```

Note the order: the policy's proposal is clipped and recorded *before* safety (so the log shows what the policy wanted),
then safety, then ownership. Execution (end of `_decide`): lock → `freeze_hpa` → `scale_deployment` if changed; or
release → `ensure_hpa_active` when handing back.

### C.6 Auto's hysteresis — `AutoArbiter.decide`, inner function `done`

```python
def done(owner, rule, reason, immediate):
    if owner == prev:                     final, streak = owner, 0            # no change
    elif immediate:                       final, streak = owner, 0            # safe direction: switch now
    else:
        cand, n = self._pending.get(service, (owner, 0))
        n = n + 1 if cand == owner else 1                                     # count consecutive choices
        self._pending[service] = (owner, n)
        if n >= cfg.dwell_steps:          final, streak = owner, n            # switch after 2
        else:                             final, streak = prev, n             # keep old owner for now
            reason += f" (waiting {n}/{cfg.dwell_steps} steps before switching)"
    self._owner[service] = final
```

Example: a service is with HPA; step 1 rule 4 chooses FlexaScale → "waiting 1/2"; step 2 again → FlexaScale takes over.
If on step 2 rule 3 had fired instead, the pending switch is cancelled and the service stays with HPA immediately.

### C.7 Freezing an HPA — `safety/hpa_manager.py`, `freeze_hpa`

```python
hpa = self.find_hpa(service_id)                                    # by scaleTargetRef
annotations = {ANNOTATION_FROZEN_BY: self.holder}
if not hpa.frozen:                                                 # record originals only once
    annotations[ANNOTATION_ORIGINAL_MIN] = str(hpa.min_replicas)
    annotations[ANNOTATION_ORIGINAL_MAX] = str(hpa.max_replicas)
patch = {"metadata": {"annotations": annotations},
         "spec": {"minReplicas": int(target), "maxReplicas": int(target)}}
res = self.kube.patch("hpa", hpa.name, self.config.namespace, patch)   # kubectl patch --type merge
```

Why "only once": if FlexaScale freezes an already-frozen HPA at a new count, the original 1–10 must not be overwritten by
the frozen value. Restoring reads the annotations back and sets them to `null` (a merge patch with `null` deletes a key).

### C.8 Percentiles from buckets — `metrics/workload_metrics.py`, `histogram_quantile`

```python
buckets = sorted(buckets, key=lambda b: b[0]); total = buckets[-1][1]   # +Inf bucket holds the total
rank = q * total
prev_bound, prev_count = 0.0, 0.0
for bound, count in buckets:
    if count >= rank:
        if bound == float("inf"): return prev_bound                      # capped: true value unknown
        return prev_bound + (bound - prev_bound) * (rank - prev_count) / (count - prev_count)
    prev_bound, prev_count = bound, count
```

### C.9 Replica-hours and cost — `evaluation/cost.py`, `summarize_resources`

```python
for cur, nxt in zip(ordered, ordered[1:]):               # consecutive 5 s samples
    dt = nxt["t"] - cur["t"]
    for svc in cur["services"].values():
        ready = int(svc.get("ready") or 0)
        rep_s       += ready * dt                         # replica-seconds
        cpu_alloc_s += ready * svc["cpu_request_cores"] * dt
        mem_alloc_s += ready * svc["memory_request_bytes"] * dt
        cpu_used_s  += svc["cpu_cores"] * dt              # observed (if known)
replica_hours = rep_s / 3600
estimated = alloc_cpu_h * 0.04048 + alloc_gib_h * 0.004445
```

A **left Riemann sum**: a sample's state is assumed to hold until the next sample. Uses **ready** replicas (what serves
and costs), and **requested** CPU/memory (what is reserved).

### C.10 Stability — `scaling_stability`

```python
for series in replica_series.values():                    # one desired-replica list per service
    last_dir = 0
    for a, b in zip(series, series[1:]):
        if b == a: continue
        changes += 1
        direction = 1 if b > a else -1
        if last_dir and direction != last_dir: reversals += 1
        last_dir = direction
```

So a service going 1→2→1 has 2 scaling events and 1 oscillation, however far apart the two changes are.

### C.11 The reward split — `simulator/twin_env.py`, `per_service_rewards`

```python
repl  = (d - floor).mean(axis=0)                          # each service's replicas above minimum
churn = |changes| per service
penalty = 6·p95_inflation + 10·slo_fraction + 5·failure_pct   # the shared latency/error penalty
contrib = (min(1, λ_i / e2e_rps) · own_excess_i).mean()   # share of traffic × own excess latency
share = contrib / contrib.sum()   (equal shares if nobody has excess)
return −0.1 × (1.0·repl + 0.25·churn + share·penalty)
```

The per-service rewards sum to the global reward, so optimising each service's own reward still optimises the
application's.

---

## Section D — Every component

| Component | Input | Processing | Output | Why it exists | Without it |
|---|---|---|---|---|---|
| Shop services | HTTP requests | Business logic, DB calls | Responses; `/metrics` | The system under control | Nothing to scale |
| Locust | Scenario, users, spawn rate, duration | Simulated user journeys | Load; stats CSVs | Repeatable, comparable load | No fair comparison |
| Prometheus | Scrapes | Stores time series; PromQL | Rates, sums, buckets | Measurement | FlexaScale is blind |
| Discovery | Kubernetes API | Filter by label/exclusions; find HPAs | `WorkloadInfo` list | Application-agnostic | Hard-coded service names |
| Telemetry client | PromQL results | Per-pod → per-Deployment; handle double counting, pod-level CPU, zero vs missing | `WorkloadMetrics` | Correct, honest inputs | Wrong or invented numbers |
| FeatureTracker | Telemetry + replica counts + time | Ratios, trends, histories | 10 features per service | Same inputs as in training | Train/live mismatch |
| Topology | Policy file (or traffic inference) | Edges restricted to discovered services | Edge list | Dependency awareness | No graph information |
| GNN extractor | 660 numbers | Embedding + 2 message-passing rounds + readout | 128 numbers | Combine neighbours' state | Each service decides alone |
| PPO actor | 128 numbers | MLP + softmax | 5 probabilities | The decision | No learned decision |
| Safety guards | Proposal + telemetry + history | Clip/block | Approved count + reasons | Bound the damage of a wrong decision | Unsafe scaling |
| Auto arbiter | Both proposals + health + risk | Ordered rules + dwell | Owner + rule + reason | Use each controller where it is safe and efficient | All-or-nothing control |
| Lease | Identity | Create/replace with resourceVersion | Exclusive application control | One FlexaScale per app | Two operators fight |
| HPA freeze/restore | Target count / annotations | `kubectl patch hpa` | HPA held or restored | HPA and FlexaScale never fight | Replica tug-of-war |
| Scaler | Approved count | `kubectl scale` | New `spec.replicas` | The actual change | Proposals only |
| Decision log | Each decision | JSON lines | `decisions.jsonl` | Explainability, evidence | No audit trail |
| Watchdog | Operator process + status file age | Restore all HPAs | Fallback event | Crashes/hangs cannot leave HPAs frozen | Frozen HPAs after a crash |
| Lab | Experiment request | Comparable start, run, sample, cleanup, summary | Run folder | Repeatable experiments | Manual, error-prone runs |
| Lab server | HTTP | JSON API | Data for the dashboard | One place to operate | Command line only |
| Dashboard | API JSON | Charts and tables | Visual control center | Watch and explain live | Raw logs only |
| Twin | Fitted parameters + workload | Queueing simulation | Simulated metrics | Fast, safe training | Months of risky live training |
| PPO training | Twin experience | Clipped policy updates | Trained weights | Learn the policy | No model |
| Helm chart | Values | Templates | Installed operator + RBAC + hook | Installable add-on | Manual installation |

---

## Section E — Diagrams and flowcharts

### E.1 Sequence of one operator step (live, Auto)

```
Operator            Kubernetes API         Prometheus          Policy (GNN+PPO)      Auto + guards
   │ renew Lease ───────▶│                       │                     │                     │
   │ list deployments,hpa▶│                       │                     │                     │
   │ PromQL (batched) ───────────────────────────▶│                     │                     │
   │◀────────────── per-pod CPU, mem, rps, buckets│                     │                     │
   │ features ×16, pack, 16 focal rows ─────────────────────────────────▶│                     │
   │◀────────────────────────────────────────────── probs 16×5 ─────────│                     │
   │ for each service: proposal → guards → owner ─────────────────────────────────────────────▶│
   │◀────────────────────────────────────────────────────────────── approved, owner, reasons ──│
   │ if FlexaScale & changed: patch hpa (min=max=n) ▶│                                          │
   │                          scale deployment n ───▶│                                          │
   │ if HPA & was frozen: restore hpa bounds ───────▶│                                          │
   │ append decisions.jsonl; write status.json                                                │
```

### E.2 Auto rules flowchart

```
            ┌───────────────────────────────┐
            │ model? CPU fresh? Lease held? │── no ──▶ HPA now  (controller_health)
            └──────────────┬────────────────┘
                          yes
            ┌──────────────▼────────────────┐
            │ confidence ≥ threshold?       │── no ──▶ HPA (policy_confidence)
            └──────────────┬────────────────┘
                          yes
            ┌──────────────▼────────────────┐
            │ (latency > SLO or CPU ≥ risk) │── yes ─▶ HPA now  (sla_risk)
            │  and HPA wants MORE replicas? │
            └──────────────┬────────────────┘
                           no
                           ▼
              FlexaScale (efficiency), after 2 consecutive steps
```

### E.3 Training pipeline

```
live calibration runs ─▶ fit_twin.py ─▶ twin (shopping_v9.json) ─▶ check vs live (2.0% RH, 8.9% p95)
                                                 │
            rule family limit_target(t/d) ─▶ best on validation: (0.6/0.3) ─▶ imitation warm start
                                                 │
                         PPO on 4 sims × 20 agents, 2M agent-steps, eval every 250k
                                                 │
              best checkpoint per run ─▶ select best run (focal_bc_s2, −2.466) ─▶ gate vs v7 (passed)
                                                 │
                          promote: model card + sha256 ─▶ policy files ─▶ live evaluation
```

### E.4 Data and evidence flow of an experiment

```
Locust CSVs ─┐
telemetry ───┼─▶ run.json (samples, events, summary, cleanup) ─▶ live_benchmark_summary.csv ─▶ benchmark (pairs, CI)
decisions ───┘                                                    │                          ─▶ dashboard Comparison
                                                                  └─▶ analyze_v7.py ─▶ reports/v9/evaluation.json/md
                                                                                    ─▶ build_results.py ─▶ results/
```

---

## Section F — Results and metrics masterclass

### F.1 Five kinds of number — always say which one you mean

| Kind | Definition | Examples in FlexaScale |
|---|---|---|
| **Measured (live Kubernetes)** | Read from the real cluster or Kubernetes API | desired/ready replicas, HPA bounds, pod CPU from cAdvisor |
| **Measured (load generator)** | Recorded by Locust from the user's side | requests, failures, end-to-end percentiles, throughput |
| **Calculated** | Computed from measured values by a formula in the code | replica-hours, CPU % of request, Δ%, confidence intervals, SLO-violation seconds |
| **Estimated** | Uses an assumption that is not measured | cost in USD (AWS Fargate list prices × allocated resources) |
| **Simulated** | Produced by the application twin or older simulators | rewards, T1/T2/T3 tables, validation scores, simulated replica-hours |

A sentence like "FlexaScale saves 7.7%" is incomplete. The complete version: "In the pre-registered live evaluation on
the second laptop, FlexaScale Auto used 7.7% fewer replica-hours (calculated from measured ready replicas) than the
default HPA, mean of 11 pairs, 95% CI −12.3% to −3.2%."

### F.2 The metric encyclopedia

Each entry follows the same twelve points: **(1)** name and definition, **(2)** what it measures and why it matters,
**(3)** formula and a calculation, **(4)** raw data, **(5)** generated by, **(6)** high vs low, **(7)** better, **(8)**
influence on autoscaling, **(9)** use for FlexaScale, **(10)** our values, **(11)** HPA vs FlexaScale vs Auto, **(12)**
limitations.

---

#### M1. Total, completed (successful) and failed requests

1. *Total requests*: every request Locust sent and got a result for during the run. *Failed*: those Locust marked as
   failures (HTTP error status, connection error, timeout, or an explicit failure in the user code). *Completed
   successfully* = total − failed (not stored as its own column).
2. The amount of work done and how much of it went wrong. With closed-loop users, a slower shop completes fewer requests.
3. From Locust's `Aggregated` row: `Request Count`, `Failure Count`. Example (run `20261031-035531`): 3,925 requests, 211
   failures → 3,714 succeeded.
4. Locust's HTTP client, per request.
5. `locust_stats.csv` → `read_locust_final()` → `summary.workload.total_requests/total_failures`;
   `results/data/selected_runs.csv` columns `total_requests`.
6. High totals at the same users = the shop kept up. High failures = errors, contention or timeouts.
7. Total: higher (same load). Failures: lower.
8. Not an input to any controller. An *outcome*.
9. Evaluates whether savings cost reliability.
10. E1 (25 users, 300 s): default HPA 4,695, tuned HPA 4,838, Auto 5,084 requests (Auto served more because it was faster). Verification
    runs at 40 users: 3,925–4,825 requests.
11. In v9 the failure rate differences were small (Auto +0.09 pp vs default HPA, CI includes 0).
12. Totals depend on duration and users, so compare only paired runs. Failures in the shop include *business* failures
    (declined payments in `payment_degradation`, 400s from empty carts in flash sales), not only overload.

#### M2. Error rate (failure rate), success rate, timeouts

1. *Failure rate* = failed ÷ total × 100 (Locust, end to end). *Service error rate* = 5xx responses per second per
   service (Prometheus). *Success rate* = 100 − failure rate.
2. Reliability as seen by users.
3. `failure_rate_pct = 100 × 211 / 3925 = 5.38%` (run `035531`). Per service: `error_rate = Σ rate(http_requests_total
   {status=~"5.."}[1m])`.
4. Locust results; service counters.
5. `read_locust_final`; `WorkloadMetricsClient.collect` (`error_rate`).
6. High = users see errors.
7. Lower.
8. Not a controller input (the reward in the twin charges 5 × failure %; the dashboard alerts at > 5% 5xx).
9. Check C3 of the verdict: failures not worse.
10. v9 arms: 0.29% (default HPA), 0.25% (tuned), 0.34% (RL), 0.32% (Auto). Verification at 40 users: 0.99%–7.08%.
11. No statistically supported difference in v9.
12. **Timeout rate is not a separate metric** in this repository: Locust counts a timed-out request as a failure; the
    twin counts requests above 10 s as failures. Success rate is only derivable (also a placeholder column in the Alibaba
    CSV, always 1).

#### M3. Throughput, RPS, request rate

1. *Throughput* = completed requests per second (Locust `Requests/s`). *Per-service request rate* = requests per second
   reaching a service (Prometheus).
2. How much work flows. Per-service rate shows where the load goes (the gateway sees every request; promotion only some).
3. Whole run: Locust's `Requests/s` (total requests ÷ Locust's own elapsed time); E1 Auto: 5,084 requests → 16.95 req/s (≈ 300 s of load). Per service:
   `max by (pod)(sum by (pod, job)(rate(http_requests_total[1m])))`, summed over pods.
4. Locust; service counters.
5. `read_locust_final/history`; `WorkloadMetricsClient.collect`.
6. High = more work done (good *if* the offered load is the same).
7. Higher at equal load (verdict check C4: mean ≥ −2%).
8. Feature 2 (`rps_trend`), feature 6 (CPU per request) and feature 7 (burstiness) use it.
9. Shows whether a controller slowed the shop down.
10. v9 means: 15.13 (default), 15.37 (tuned), 15.07 (RL), 15.15 (Auto) req/s; Auto vs default −1.4% [−4.5, +1.6].
11. Essentially equal.
12. Closed-loop: throughput falls when latency rises, so a controller can look "efficient" by being slow. Always read it
    with latency.

#### M4. Concurrent users, spawn rate, workload intensity

1. *Users* = simultaneous Locust virtual users; *spawn rate* = users started per second; *workload intensity* is set by
   users, the scenario's mix and its shape.
2. The offered load.
3. Flash sale at 25 users: 5 users (20%) → 25 → 5.
4. Locust history `User Count`.
5. `scenarios.py`; `read_locust_history` (`users` in each sample).
6. More users = more load.
7. Neither: it is a controlled input.
8. Not a controller input.
9. Must be identical within a pair.
10. Benchmarks: 25 users, spawn 5/s, 300 s. Verification: 40 users. Above ~40 users the single node runs short of
    memory.
11. —
12. At 25 users most services never need more than one replica, which limits any controller's possible saving.

#### M5. Mean (average) latency

1. Sum of response times ÷ number of requests.
2. Typical speed, but sensitive to outliers.
3. Locust `Average Response Time`. Per service: `1000 × rate(duration_sum[1m]) / rate(duration_count[1m])`. Example: 20 requests taking (ms) 10, 12, 12, 13, 14, 15, 15, 16, 18, 20, 21, 22, 25, 30, 35, 40, 60, 90,
   300, 1200 → sum 1,968 ms, mean 98.4 ms, while the median is about 20 ms: one slow request pulls the mean up.
4. Locust; service histograms' `_sum` and `_count`.
5. `read_locust_final` (`mean_latency_ms`); `collect` (`latency_mean_ms`).
6. High = slow.
7. Lower.
8. Feature 3 (latency inflation) uses per-service mean latency; scale-down block on SLO (if set); Auto rule 3 (if an SLO
   is set).
9. Context.
10. v9: 85 (default), 71 (tuned), 110 (RL), 94 ms (Auto).
11. RL and Auto had higher means, driven by tail events.
12. A few very slow requests dominate. Use percentiles for user experience.

#### M6. Latency percentiles p50, p90, p95, p99 (and Locust's others)

1. pX = the time below which X% of requests completed. Locust also reports 66%, 75%, 80%, 98%, 99.9%, 99.99%, 100% and
   max.
2. User experience across the distribution; p95 is the SLO metric; p99 shows rare stalls.
3. Sort times, take the value at position X% (Locust); interpolate in histogram buckets (Prometheus, Section C.8).
4. Locust per-request timings (end to end); service histograms (per service).
5. Whole run: `locust_stats.csv`; ~10 s windows: `locust_stats_history.csv`; per service: `histogram_quantile`.
6. High = slow tail.
7. Lower.
8. Feature 3 uses the mean, not percentiles. The SLO violation is measured on the window p95.
9. C2 of the verdict (p95 not worse).
10. v9 means: p50 44/42/37/37 ms; p95 241/167/395/200 ms; p99 838/510/1674/1936 ms (default/tuned/RL/Auto).
11. FlexaScale had the **lowest median and the highest tail**: lean replica counts are fast in the common case, but a
    burst that arrives before a scale-up is slow.
12. Locust rounds above 100 ms to two significant figures (130, 170, 5300), so +6% may be one rounding step. Histogram
    percentiles are interpolations and are capped at 10 s ("≥"). The mean of p95 over runs is not the p95 of all
    requests. Three late v9 reruns (memory pressure) dominate the RL p95 mean (sensitivity: +3.8% without them).

#### M7. SLO / SLA metrics

1. *SLO*: end-to-end p95 ≤ 1000 ms in each ~10 s Locust window. *e2e_slo_violation* (per 5 s sample): window p95 > 1000.
   *e2e_violation_seconds*: total time in violated samples. *e2e_violation_fraction*: violated samples ÷ samples with a
   p95. *service_violation_seconds*: time any service's mean latency exceeded its own SLO (0 for the shop: no per-service
   SLO). *SLA status* in `results/`: whole-run p95 ≤ 1000 → "met".
2. How long users had a bad experience.
3. `Σ Δt` over samples with `e2e_slo_violation`; E1 default HPA: 30 s (6 samples of 5 s).
4. Locust history CSV, sampled every 5 s.
5. `Experiment._sample` (flag), `_finalize` (sums).
6. High = long bad periods.
7. Lower (verdict check C5: mean ≤ +5 s).
8. In the twin the reward charges 10 × violation fraction.
9. Shows whether savings hurt users.
10. v9 means per run: 22.9 s (default), 8.0 (tuned), 25.6 (RL), 15.7 (Auto). E1: 30 s vs 0 s (Auto); E2: 115 s vs 30.1 s
    (RL).
11. Auto better than default, worse than tuned; RL about equal to default.
12. Window-based (a 10 s Locust window), so short spikes count fully. The dashboard's "SLA" is this SLO, not a contract.

#### M8. Recovery time / longest violation

1. Comparison page row "Longest violation (recovery)": the longest run of consecutive violated samples. In the twin,
   `recovery_s` = seconds from the first load drop until total desired replicas are within 1 of the run's minimum.
2. How quickly the system returns to normal.
3. Count consecutive violated samples × 5 s; twin: first tick after the drop with replicas ≤ floor + 1.
4. Samples; twin logs.
5. Dashboard compare; `twin_control.recovery_time`; `evaluation.json` arms (`recovery_s` list).
6. High = slow recovery.
7. Lower.
8–11. Descriptive only (not part of the verdict); v9 Auto arm `recovery_s` [4.5, 4.4, 0.5] for the runs with a drop.
12. Defined differently in the dashboard and the twin; quote which one.

#### M9. CPU: cores, % of request, % of limit, average and peak

1. *cpu_cores*: CPU in use (cores) summed over a service's pods. *cpu_pct*: average per pod as % of the CPU request (HPA's
   definition). *cpu_limit_frac*: per pod ÷ limit (feature 0). *avg/peak_cpu_pct_of_request*: mean/max of cpu_pct over all
   services and samples.
2. How busy pods are; the HPA's only signal.
3. 0.0868 cores on 1 pod, request 0.1, limit 0.5 → 86.8% of request, 0.1736 of the limit.
4. cAdvisor `container_cpu_usage_seconds_total`, rate over 1 minute.
5. `collect`; `_finalize` (`utilization`).
6. High = busy (near saturation above ~400% of request, i.e. 80% of the limit).
7. Context: too high risks latency, too low means waste.
8. HPA: `ceil(r × cpu / target)`. FlexaScale: features 0, 1, 6; guard "no scale-down at ≥ 400%"; Auto risk ≥ cpu_risk_pct.
9. The main driver of both controllers.
10. E1 Auto: average 33.5%, peak 281% of request. v9 arms `cpu_pct` mean 22.7% (Auto).
11. Default HPA runs more replicas, so lower average CPU per pod (24.3% in E1) than FlexaScale/tuned (33.5%).
12. Requests (100 m) are much lower than limits (500 m), so "% of request" can exceed 100%; a 70% target is only 14% of
    the limit. A service bottlenecked on the database shows moderate CPU while being slow.

#### M10. Memory: bytes, % of limit, average

1. *memory_bytes*: working set summed over pods; *memory_pct*: per pod ÷ memory limit (request if no limit).
2. Memory pressure.
3. 96 MiB of 256 MiB → 37.5%.
4. cAdvisor `container_memory_working_set_bytes`.
5. `collect`; `_finalize` (`avg_memory_pct`).
6. High risks out-of-memory kills.
7. Lower, with headroom.
8. Guard: no scale-down at ≥ 90%.
9. Safety only; not a policy feature in v7/v9.
10. E1: 25–26% average memory for every arm.
11. No difference.
12. Working set includes caches; the cost estimate uses memory *requests*, not limits.

#### M11. Replica counts: desired, ready, HPA desired, bounds, frozen, average, peak

1. *desired* = `spec.replicas`; *ready* = `status.readyReplicas`; *hpa_desired* = the HPA's own `status.desiredReplicas`;
   *hpa_min/hpa_max*; *frozen* = HPA carries FlexaScale's freeze annotation; *avg_total_desired* = mean over samples of
   the sum over services; *peak_total_desired*; *avg/peak_ready_replicas* (cost module).
2. Capacity requested and serving.
3. E1 Auto: average 16.6, peak 17 desired; floor = 16 services × 1.
4. Kubernetes API via discovery.
5. `_sample`, `_finalize`, `summarize_resources`.
6. High = more capacity (and cost).
7. Lower at equal performance.
8. They are the controlled quantity; feature 4 (replica fraction) and 5 (ready fraction).
9. Primary behaviour evidence.
10. v9 means: avg replicas 16.05 (Auto), peak 16.1. E1 default HPA: average 22.2, peak 27.
11. Default HPA scales up more and down later.
12. Average desired includes pods not yet ready; replica-hours uses ready.

#### M12. Scaling events, oscillations, applied scale requests, scaling delay, cooldown

1. *scaling_events*: number of desired-replica changes summed over services. *oscillations*: number of direction
   reversals (Section C.10). *applied*: FlexaScale scale requests Kubernetes accepted. *Scaling delay*: time from a FlexaScale
   decision to the new desired count (API) and to ready (pod start). *Cooldown*: guard waiting time (20 s up, 30 s down).
2. Activity and stability of control.
3. 1→2→1 = 2 events, 1 oscillation.
4. Desired series in samples; decision log.
5. `scaling_stability`; `summary.decisions.applied`; `verify_controller_modes.py` (delays).
6. Many events/oscillations = churn (pod start costs, instability).
7. Fewer oscillations (check C6); events are context.
8. Reward charges 0.25 per change; cooldowns limit frequency.
9. Stability evidence.
10. v9 means: events 3.0 (default), 0.2 (tuned), 0.4 (RL), 0.2 (Auto); oscillations 0.0/0.1/0.2/0.1. Delays: desired
    after 1.1–6.1 s, ready after 6.1–16.1 s (verification). Scale-up/down frequency is not a separate metric: derive it as
    events ÷ duration.
11. Default HPA changes most.
12. A reversal far apart in time is still counted as an oscillation (the code has no time limit).

#### M13. Replica-hours (primary resource metric)

1. Ready replicas integrated over time, in hours.
2. Resource consumption independent of prices.
3. `Σ ready × Δt / 3600`. E1 Auto: average ready 16.589 × 305.98 s / 3600 = **1.410**. Floor at 300 s: 16 × 300 / 3600 =
   **1.333**.
4. Ready counts every 5 s.
5. `summarize_resources`.
6. High = more resources.
7. Lower (check C1: interval below 0).
8. The reward's replica term is its simulated counterpart.
9. The main cost evidence.
10. v9 means: 1.512 (default), 1.366 (tuned), 1.368 (RL), 1.365 (Auto).
11. RL/Auto −7.3%/−7.7% vs default (CIs below 0); +0.3%/+0.2% vs tuned (on par).
12. Sample-based (5 s): a pod that lived 3 s may be missed. Integrates over the whole sampled window (slightly longer than
    the 300 s load).

#### M14. Allocated vs used resources and allocation efficiency

1. *Allocated vCPU-h* = Σ ready × CPU request × time; *allocated GiB-h* likewise with memory requests; *used vCPU-h* = Σ
   observed cores × time; *CPU allocation efficiency* = used ÷ allocated × 100; same for memory.
2. Waste: reserved but unused.
3. E1 Auto: allocated 0.141 vCPU-h (= 1.410 replica-h × 0.1 core), used 0.0560 → **39.7%**; memory 53.0%.
4. Requests from Deployment specs; usage from cAdvisor.
5. `summarize_resources`.
6. High efficiency = little waste (but too high = no headroom).
7. Higher, within reason.
8. —
9. Shows FlexaScale/tuned HPA do the same work on fewer replicas.
10. E1–E4: average CPU 32–40% of request for FlexaScale/tuned vs 24–28% for default HPA.
11. Default HPA least efficient.
12. Note the difference between `avg_cpu_pct_of_request` (33.46% in E1, an unweighted mean over samples and services) and
    the efficiency (39.7%, time- and replica-weighted). They answer different questions.

#### M15. Estimated cost, cost proxy, cost rate

1. *Estimated cost (USD)* = allocated vCPU-h × $0.04048 + allocated GiB-h × $0.004445 (AWS Fargate on-demand list
   prices, us-east-1). *Cost proxy* (when no prices) = vCPU-h + 0.125 × GiB-h. *Cost rate* (Overview) = $/hour of what is
   allocated now.
2. A monetary view of resource use.
3. E1 Auto: 0.141001 × 0.04048 + 0.152347 × 0.004445 = 0.005708 + 0.000677 = **$0.006385**.
4. Allocated resources.
5. `summarize_resources`; policy `cost` block.
6. High = expensive.
7. Lower.
8. —
9. Same conclusions as replica-hours (all services request the same CPU).
10. v9: $0.00685 / 0.00618 / 0.00619 / 0.00618 per run; Auto vs default −7.9% [−12.5, −3.2].
11. Follows replica-hours.
12. **An estimate, not a bill**: Minikube has no bill; real clouds price nodes, not pods; absolute values are tiny
    (fractions of a cent per run); only the percentage is meaningful.

#### M16. Decision and ownership metrics

1. Per run: *decisions.total* (services × steps), *applied*, *proposed_changes* (policy action ≠ hold index), *flexascale_owned*,
   *hpa_fallbacks* (decisions not owned by FlexaScale), *policy_modes*; Auto rule counts (`auto_counts`); per decision:
   *confidence*, *probabilities*, *policy_replicas*, *proposed_replicas*, *safety_reasons*, *hpa_recommendation*.
2. What the policy wanted vs what happened, and who owned what.
3. E1 Auto: 496 decisions (31 steps × 16), 318 proposed changes, **2 applied**. Most "proposed changes" were scale-downs of
   services already at their minimum (clamped by the bounds).
4. `decisions.jsonl`.
5. `_finalize`; `verify_controller_modes.py`.
6. —
7. —
8. They *are* the control trace.
9. Evidence for "Auto selected FlexaScale and applied scaling".
10. SLA-risk run: efficiency 462, sla_risk 34 decisions; 7 applied.
11. —
12. A proposal is not an action. Never count proposals as scaling.

#### M17. Comparison statistics: Δ%, mean, n, 95% CI, d_z, verdict checks

1. *Δ%* per pair; *mean* over pairs; *n* pairs; *95% CI* = mean ± t × s/√n; *d_z* = mean ÷ s (standardised effect size of
   paired differences); *checks C1–C7*; *verdict*.
2. Whether a difference is real or noise.
3. Auto vs default replica-hours: mean −7.748%, n = 11, CI [−12.31, −3.18]. With t(10) = 2.228: half-width 4.566 → s =
   4.566 × √11 / 2.228 = 6.80 → d_z = −7.748 / 6.80 = **−1.14** (matches the file).
4. Paired runs.
5. `lab/benchmark.py`, `scripts/analyze_v7.py` → `reports/v9/evaluation.json` (`stats`, `checks`, `verdict`).
6. A CI entirely below/above 0 = a difference at 95% confidence; |d_z| ≈ 0.2 small, 0.5 medium, ≥ 0.8 large (common
   convention).
7. Depends on the metric's direction.
8. —
9. The formal evidence.
10. Auto vs default: C1 true, **C2 false** (p95 +17.6% [−6.0, +41.2], mean above +10%), C3–C7 true → "On par /
    inconclusive". Other fields: `per_scenario_replica_hours` (e.g. flash_sale −22.9, checkout_heavy −14.5);
    `steady_app_cpu_per_request_delta_pct` = +5.99 (environment parity: Auto's shop was 6% *slower* per request in steady
    browsing, so no hidden advantage); `cpu_clock_delta_pct` not recorded on the second laptop.
11. See Section F.5.
12. 11–12 pairs is small; multiple metrics are checked, so one may pass by chance; percentages of tiny baselines can be
    large.

#### M18. Host validity metrics (`reports/host_load_by_run.csv`, `reports/v9/host_load_*.csv`)

1. *host_cores*: whole-machine CPU in use (psutil); *k8s_cores*: CPU used by the cluster's containers; *outside_cores* =
   host − k8s; *limit_cores* = idle baseline + 2.0; *battery_s*: seconds on battery; *host_affected*, *reason*; *cpu_mhz*
   (first laptop); *app_cpu_ms_per_request*: shop CPU per request (environment parity); *host_source*.
2. Whether something outside the experiment disturbed it.
3. Second-laptop baseline: idle outside 1.576 cores → limit 3.576. A run with outside 1.64 cores passes.
4. psutil samples every 5 s; Prometheus; battery state.
5. `scripts/check_host_load.py`, `scripts/measure_host_baseline.py`.
6. High outside cores = disturbed.
7. Lower.
8. —
9. Validity of every pair.
10. 7 of 53 v9 runs were host-affected (all FlexaScale/Auto) and excluded; early runs on battery are flagged.
11. —
12. Only CPU and power are checked; memory pressure was found later (late reruns).

#### M19. Training metrics (Stable-Baselines3 logs; v4 example from `logs/train_v4_lr1e-4_ent0.01_s3.log`)

| Metric | Meaning | Example value | Reading |
|---|---|---|---|
| `ep_rew_mean` | Mean episode reward over recent episodes | −20.8 → −12 | Rising = learning |
| `ep_len_mean` | Mean episode length (steps) | 30 | Fixed by the simulator |
| `fps` | Environment steps per second | 1685 → 30 | Speed (falls when evaluation runs) |
| `total_timesteps`, `iterations`, `n_updates` | Progress counters | 1,001,472; 489; 4,880 | — |
| `approx_kl` | Approximate KL divergence between old and new policy per update | 0.008–0.017 | Size of the policy change; large = unstable |
| `clip_fraction` | Share of samples whose ratio was clipped | 0.026–0.109 | High = updates hitting the limit |
| `clip_range` | ε | 0.2 | Setting |
| `entropy_loss` | Negative entropy | −4.39 → −3.61 | Less negative = less random (multi-head policy, so values below −1.6) |
| `explained_variance` | 1 − Var(G − V)/Var(G): how well the critic predicts returns | 0.03 → 0.49 | 1 = perfect, 0 = useless |
| `value_loss` | Critic's mean squared error | 57 → 31 | Falling = critic learning |
| `policy_gradient_loss` | The clipped surrogate (negated) | −0.004 | Small; not a quality measure |
| `loss` | Total loss | 27 → 12 | Mostly the value term |
| `learning_rate` | Step size | 1e-4 | Setting |

For v7/v9 the SB3 console logs were not kept on this laptop (v9 trained on the second laptop); their training is
summarised by **validation reward** per checkpoint (`reports/v9/training_v7.json`, model cards). Warm-start quality is
reported as **agreement** (share of held-out decisions equal to the teacher's), **recall per action**, and **value MSE**
vs the return variance.

#### M20. Reward, episode return and reward components (simulated)

1. *Step reward* (Part One, Section 7.6); *episode reward* = sum over the episode's steps; *validation reward* =
   mean episode reward over 40 validation workloads; components: `replicas_above_min`, `p95_inflation`, `slo_fraction`,
   `failure_pct`, `scaling_events`.
2. How good a controller is under the training objective.
3. Example step: −0.1 × (3 + 0.25) = −0.325.
4. Twin.
5. `twin_env.reward_v7`, `episode_reward`, `train_v7.run_set/agg`.
6. Closer to 0 = better (it is a penalty).
7. Higher.
8. It is what PPO maximised.
9. Selection and the gate.
10. v9 runs' best validation: −2.466 (focal_bc_s2), −2.922 (no graph), −2.990 (s1), −3.299 (old reward); rule −2.99; gate
    v9 −2.47 vs v7 −2.91.
11. In T1 tuned HPA −1.196 vs v9 −1.255; in T2 v9 −2.548 vs tuned −3.060.
12. Simulated; the seed-to-seed spread (0.52) is as large as design differences; selection on the same set flatters the
    winner.

#### M21. Twin fidelity and test-set columns

* *Twin check* (`reports/v9/twin_check.md`): live vs twin replica-hours, p95 and mean latency per HPA target; mean absolute
  error v9 twin 2.0% / 8.9% / 4.4%; v7 twin on the second laptop 1.9% / 20.5% / 17.7%.
* *T1–T3 tables* (`reports/v9/ablation.md`): columns `reward`, `replica-h`, `p95 ms`, `mean ms`, `SLO violation s`,
  `events`, `osc` per controller (all simulated).
* *Graph ablation*: Δ reward / replica-h / p95 / SLO with 95% CIs, graph − no graph, paired by episode.
* *v9 vs v7* (`reports/v9/v9_vs_v7.md`): every reward interval includes 0 on both twins → the two models tie on held-out
  tests.

#### M22. Older simulation metrics (`reports/simulation_evaluation_v4/v5/v6.md`)

Columns: *reward/step*, *SLO violation rate* (fraction of service-steps above the service's SLO), *avg replicas*, *avg
CPU %*, *replica changes/step*, each ± 95% half-width over 300 paired episodes; paired differences and *episodes v5
better*. Example (v5): reward −0.274 vs HPA-like rule −0.338 (v5 better by 0.064 ± 0.031) but worse than a tuned rule
(−0.048 ± 0.013), with 0.44 more replicas. **Simulated**, Alibaba-driven; did not carry over live.

#### M23. GNN quantities

| Quantity | Value | Meaning |
|---|---|---|
| Nodes | 16 real of 20 slots | Services |
| Edges | 25 directed | Calls |
| Node features | 10 | Part One, Section 8.1 |
| Adjacency | 20 × 20 binary | Caller rows, callee columns |
| Degrees | e.g. api-gateway out-degree 9; order-service out-degree 7, in-degree 1; catalog-service in-degree 6 | Number of callees / callers |
| Embedding size | 64 per node; readout 128 | Learned summary |
| Rounds | 2 | Receptive field 2 hops |
| Parameters | 42,566 | Section 8.7 |

"Dependency information" in this project = the adjacency matrix plus message passing; no traffic-weighted edges are used
for the shop.

#### M24. Alibaba dataset columns (`data/processed/alibaba_service_state*.csv`)

`timestamp` (ms from trace start), `service_id` (hashed msname), `cpu_utilization` (%), `memory_utilization` (%),
`replica_count`, `request_rate`, `latency_ms` are **trace-derived**. `source`, `submit_time`, `start_time`,
`finish_time`, `completion_time`, `wait_time`, `makespan`, `cpu_memory_ratio`, `cpu_capacity`, `gpu_count`,
`gpu_utilization`, `gpu_memory`, `jct`, `acceptance_ratio`, `successful_requests`, `failed_requests`, `error_rate`,
`success_rate` are **filled by rule** for schema compatibility (Part One, Section 5.2). Do not present them as
measurements.

### F.3 Every results file, its columns and what it concludes

| File | Purpose | Columns / content | Conclusion |
|---|---|---|---|
| `results/RESULTS.md` | Curated results with charts and evidence | Narrative + tables | The summary you present |
| `results/data/selected_runs.csv` | One row per selected run (E1–E4 arms + verification runs) | `experiment, experiment_title, arm, run_id, block, scenario, controller, users, spawn_rate, duration_s, actual_duration_s, state, initial_replicas, hpa_bounds, hpa_config, flexascale_config, throughput_rps, total_requests, p50_ms, p90_ms, p95_ms, p99_ms, mean_ms, error_rate_pct, avg_cpu_pct_of_request, peak_cpu_pct_of_request, avg_memory_pct, avg_replicas, peak_replicas, replica_hours, estimated_cost_usd, cpu_allocation_efficiency_pct, e2e_slo_violation_s, e2e_slo_violation_fraction, sla_status, scaling_events, cleanup_safe, raw` (all defined in F.2) | Per-run evidence for E1–E4 and verification |
| `results/data/comparisons.csv/.json` | Pooled pre-registered comparisons | `study, comparison, pairs, verdict, replica_hours_mean, cost_mean, p95_ms_mean, failure_pct_mean, throughput_mean, replica_hours_ci95, p95_ms_ci95, source` (means are Δ%; failure in pp) | Savings vs default; parity vs tuned |
| `results/data/v9_auto_vs_default_pairs.csv` | Every pair behind Auto vs default | `block, scenario, candidate, reference, replica_hours, cost, p95_ms, p99_ms, failure_pct, throughput` (Δ% per pair; failure Δ in pp) | Where the saving comes from (flash sale, checkout heavy) |
| `results/charts/*.svg`, `screenshots/*.png` | Charts and dashboard captures | — | Visual evidence |
| `results/verification/README.md`, `*.json` | End-to-end verification | JSON keys: `run` (id, state, controller, model + sha256, cleanup, operator_failure, workload, replicas, resources), `totals`, `operator_events`, `lab_events`, `per_service`, `exclusivity_violations`, `faults`, `snapshots`, `request` | All three modes and fallbacks work |
| `reports/experiments/<id>/run.json` | Everything about one run | `id, request, state, timestamps, events, samples, summary, cleanup, model, initial/start_replicas, slo, auto_state, auto_counts, policy` | Raw truth |
| `…/telemetry.csv` | One row per service per 5 s sample | `t, elapsed, users, rps, fail_rps, p50_ms, p90_ms, p95_ms, p99_ms, e2e_slo_violation, service, desired, ready, hpa_desired, hpa_min, hpa_max, frozen, cpu_pct, memory_pct, cpu_cores, memory_bytes, request_rate, latency_ms, latency_p50/p90/p95/p99_ms, error_rate, stale` | Timeline data |
| `…/decisions.jsonl` | One record per service per operator step, plus events | `type, ts, step, app, mode, service, features, missing, stale, policy{mode, action, action_label, delta, confidence, probabilities, window, clipped}, current_replicas, ready_replicas, hpa, hpa_recommendation, policy_replicas, auto{owner, rule, reason, candidate, hpa_recommendation, flexascale_proposal, streak, inputs}, controller, proposed_replicas, safety_reasons, applied, apply_error, hpa_note, policy_input` | Explainability |
| `…/locust_stats.csv` | Whole-run Locust stats | `Type, Name, Request Count, Failure Count, Median/Average/Min/Max Response Time, Average Content Size, Requests/s, Failures/s, 50%…100%` | End-to-end outcome |
| `…/locust_stats_history.csv` | Periodic Locust rows | `Timestamp, User Count, Type, Name, Requests/s, Failures/s, percentiles, Total Request/Failure Count, Total Median/Average/Min/Max Response Time, Total Average Content Size` | Window percentiles for the SLO |
| `…/locust_failures.csv`, `locust_exceptions.csv` | Errors by type | `Method, Name, Error, Occurrences, First/Last Seen` | Why requests failed (e.g. 400 empty cart, 502 under contention) |
| `reports/live_benchmark_summary.csv` | One row per recorded run (289) | `run, app, controller, model, scenario, users, duration_s, state, complete, preliminary, requests, requests_seen_in_samples, throughput_rps, failure_pct, p50_ms, p95_ms, p99_ms, e2e_slo_violation_s, avg_replicas, peak_replicas, replica_hours, alloc_vcpu_h, used_vcpu_h, cpu_alloc_eff_pct, estimated_cost, cost_proxy, scaling_events, oscillations, applied_scale_requests, cleanup_safe, settled_start` | Input to the live report |
| `reports/live_benchmark_report.md` | Pooled pairs by model/mode vs default HPA | Summary table + block studies | History v3–v9 |
| `reports/v9/evaluation.md/.json` | Pre-registered v9 verdicts | `blocks, excluded, comparisons{pairs, stats, verdict, checks, per_scenario_replica_hours, …}, arms` | Final verdicts |
| `reports/v9/calibration.md/.json` | Tuned-HPA calibration | Target, valid runs, p95, mean, failures, replica-h, throughput, meets rule | 350% selected |
| `reports/v9/twin_check.md`, `ablation.md`, `v9_vs_v7.md`, `evaluation_sensitivity.md`, `gate.json`, `arms.json`, `*_plan*.json`, `host_*` | Twin fidelity, test sets, ablation, robustness, gate, design, validity | See M18–M21 | Supporting evidence |
| `reports/v7/evaluation.md`, `replication.md`, `calibration.md` | First-laptop studies | Same structure | Withdrawn batch (confound) and on-par replication |
| `reports/simulation_evaluation*.md/json` | v2–v6 simulated tests | See M22 | Simulation gains that did not transfer |
| `reports/data_quality_report.md/json` | Dataset checks | Shape, units, splits, distributions | Data provenance |
| `reports/shopping_benchmark_*`, `reports/locust_hpa_phase_*`, `reports/locust_rl_phase_*` | Early 7-service, 60 s benchmark | Telemetry and Locust files | **Withdrawn**: used an untrained network head and mis-scaled data |
| `reports/benchmark_report.md`, `benchmark_summary.json` | Early simulated benchmark (3 episodes) | Identical numbers for HPA and RL, 20 fallbacks per episode | **Superseded**: every decision fell back to the heuristic, so it measured no difference |
| `reports/experiments_invalid/README.md` | Every excluded run and why | — | Transparency |

### F.4 How the metrics work together

A scaling decision needs several signals at once:

* **RPS up, CPU up, latency up** → genuine overload: add replicas (both HPA and FlexaScale agree).
* **CPU up, RPS flat, latency flat** → a brief CPU blip (e.g. checkout-heavy E3/E4): adding replicas wastes capacity;
  default HPA did this, FlexaScale and tuned HPA did not.
* **Latency up, CPU moderate** → a non-CPU bottleneck (order-service waiting on the database): replicas may help a little
  or not at all; a CPU-only controller under-reacts, a latency-aware one would react (future work).
* **RPS falls** → release capacity soon (FlexaScale's 30 s cooldown vs HPA's 300 s window): the source of the flash-sale
  saving.
* **Ready < desired** → pods are starting: wait (readiness guard) rather than add more.

**Why optimising one metric fails.** Minimise replicas only → the policy holds 1 replica during a spike (p95 explodes).
Minimise latency only → scale everything up (the v1–v3 failure: +77% replica-hours). Minimise churn only → never act.
The reward combines them with explicit weights, and the verdict requires cost **and** latency **and** failures.

**Over-provisioning** = more replicas than the load needs (default HPA in E1: 27 replicas, kept 5 minutes). **Under-
provisioning** = fewer than needed (FlexaScale at 40 users on the Fedora laptop: p95 2–6 s). **Resource efficiency** =
work done per allocated resource (M14). **Cost estimation** = allocated resources × list prices (M15).

### F.5 HPA vs FlexaScale vs Auto — the honest comparison

| Situation | Who did better | Why | Evidence |
|---|---|---|---|
| Flash sale vs **default** HPA | FlexaScale/Auto (fewer replicas, lower p95 in E1/E2) | Default HPA reacted late and held capacity for 300 s | E1, E2 (single pairs) |
| Checkout heavy vs default HPA | FlexaScale/Auto on cost; HPA slightly on p95 (+6%) | Default HPA scaled for brief CPU rises | E3, E4 |
| Gradual ramp, traffic drop vs default HPA | Default HPA on latency (Auto p95 +30–65%) | Lean replicas meet bursts before scale-ups | v9 pairs |
| Pooled vs default HPA | FlexaScale on cost (−7.3/−7.7%), not proven on latency | Above | v9 evaluation |
| vs **tuned** HPA | Neither (on par) | A higher target + 60 s window removes the same waste | v7 replication, v9 |
| Non-CPU bottleneck at 40 users (Fedora) | Default HPA reacted, FlexaScale did not | Its 70%-of-request target is only 14% of the limit; policies read CPU vs the limit | Verification runs |
| Safety under failures | FlexaScale/Auto hand back correctly | Lease, freeze, watchdog | Verification |
| Explainability | FlexaScale/Auto | Per-decision reasons and rules | Decision logs |

### F.6 Misleading interpretations to avoid

* Counting **proposals** (green dashed line, "would propose") as scaling. Only ◆ + desired change are actions.
* Presenting **simulated** rewards as live performance.
* Quoting **E1** (one pair) as the overall result; the pooled verdict is "on par / inconclusive".
* Comparing with the **default** HPA only; the fair baseline is the tuned HPA.
* Reading **cost in dollars** as real money saved.
* Treating **"≥ 10000 ms"** as a measured value; it is a lower bound.
* Ignoring that the **v6 −3.9%** and the first **v7 "beats on performance"** were affected by a power-profile confound.
* Calling the graph "proven beneficial"; the ablation found no measurable benefit.

---

## Section G — Research papers and novelty

### G.1 What the repository contains (and does not)

**There are no research-paper PDFs in the repository.** The only literature material is the team's own Phase 2
documents in `PPT AND REPORT/`: *Literature Review A1 – Phase 2.pdf* (a preliminary survey of five papers with a
comparison table, research gap and novelty) and *Design and Solutions – A1 phase 2.pdf* (architecture, methodology and the
same five references). The details below for those five papers come **only** from those documents. The final project
report reviews seven more papers; those paragraphs were written from general knowledge of the papers, not from files in
the repository, so **verify every number and author list against the papers themselves before the viva**.

### G.2 The five papers in the team's literature review

| # | Paper (as listed by the team) | Year | Key contribution (team's words) | Methodology | Dataset / evaluation | Limitation / gap (team's words) |
|---|---|---|---|---|---|---|
| 1 | Santos et al., *Gwydion: Efficient Auto-Scaling for Complex Containerized Applications in Kubernetes through Reinforcement Learning*, J. Netw. Comput. Appl. 234, 104067 | 2025 | RL-based Kubernetes autoscaling that considers microservice dependencies; cost- and latency-aware rewards | Deep RL considering microservice dependencies | Redis Cluster and Online Boutique on Kubernetes | Mainly horizontal scaling and predefined reward strategies; limited adaptive multi-objective optimisation |
| 2 | Ahmad et al., *Towards Resource-Efficient Reactive and Proactive Auto-Scaling for Microservice Architectures*, J. Syst. Softw. 225, 112390 | 2025 | Smart HPA and ProSmart HPA: reactive and proactive scaling with ML workload prediction | Resource-efficient HPA with ML prediction | Real Kubernetes microservice benchmark | No reinforcement learning for continuously learned policies |
| 3 | Pandey, *Reinforcement Learning-Based Autoscaling for Cost and Performance Optimization in Kubernetes Clusters* | 2025 | Multidimensional RL autoscaler, horizontal + vertical, jointly optimising latency, cost and SLA | PPO and DDPG | Spark TPC-DS on an EKS cluster | Extensive training; cost–latency focus without modelling service dependencies |
| 4 | Shi et al., *AdaptScale: An Adaptive Data Scaling Controller for Improving Multiple Performance Requirements in Clouds*, FGCS 105, 814–823 | 2020 | Adaptive workload prediction + greedy heuristic for multiple SLAs with minimal resources | Greedy heuristic with workload prediction | Simulation platform | Cloud *data* scaling, not Kubernetes microservice autoscaling |
| 5 | El Haj Ahmed et al., *KubCG: A Dynamic Kubernetes Scheduler for Heterogeneous Clusters*, Softw. Pract. Exp. 51(2), 213–234 | 2021 | Dynamic scheduler using historical execution information for CPU–GPU clusters | Dynamic scheduling from execution history | Heterogeneous Kubernetes cluster | Scheduling efficiency, not runtime autoscaling |

**A detail to fix in your own documents.** In both Phase 2 PDFs the reference list titles paper 4 "*FlexaScale:* An
Adaptive Data Scaling Controller…", while the literature table calls it "*AdaptScale*". The final report uses
"AdaptScale". Check the actual paper's title before the viva; an examiner who notices will ask.

### G.3 What FlexaScale adopted, modified or did differently

| Idea | Source in the literature | What FlexaScale did |
|---|---|---|
| Dependency information in an RL autoscaler | Gwydion [1] | Adopted and **modified**: a GNN with directed caller/callee messages over the real call graph, focal per-service decisions with per-service rewards |
| A tuned rule can be strong | Smart HPA [2] (and the team's own finding) | Made it part of the **evaluation**: a calibrated tuned HPA is the primary baseline |
| PPO for autoscaling | Pandey [3] | Adopted PPO (Stable-Baselines3); addressed training cost with a fitted twin and imitation warm start |
| Several performance requirements in one objective | AdaptScale [4] | One reward with explicit weights for replicas, latency inflation, SLO, failures and churn |
| Use measurements of the actual system | KubCG [5] | The application twin is fitted to measured CPU per request and pod start-up times |

### G.4 What is genuinely different, and what is not

**Defensible claims** (each backed by code and evidence):

1. Per-service, explainable arbitration between a learned policy and the native HPA (Auto mode), with exclusive
   ownership enforced by a Lease and an HPA freeze, and verified fallback in every failure mode tested.
2. A fair, pre-registered live evaluation against both the default and a calibrated HPA, including negative results,
   withdrawn confounded batches and an ablation of the graph.
3. Training in an application twin fitted to the live system, checked for fidelity before use.

**Claims you must not make:** that FlexaScale beats a tuned HPA; that the GNN is proven to help; that the method is the
first RL autoscaler or the first dependency-aware one (Gwydion and others predate it); that the cost numbers are real
savings.

**Phase 2 design elements not implemented:** adaptive reward weighting by traffic phase; online PPO updates on the live
cluster; PyTorch Geometric in the final model; a three-node cloud cluster. The confidence-proxy fallback was implemented
(Auto rule 2 and the non-Auto confidence gate) but set to 0 in the shop's policy.

---

## Section H — Mistakes, bugs, debugging and troubleshooting

### H.1 Real problems met in this project (all documented in the repository)

| # | Problem | How it showed up | Fix | Source |
|---|---|---|---|---|
| 1 | Alibaba CPU/memory stored as fractions, consumers expected percent | v1 trained on near-zero CPU | Rescaled ×100 with provenance; builder fixed | `reports/data_quality_report.md` |
| 2 | Early live benchmark used the GNN's `node_policy_head`, which PPO never trained | "FlexaScale" numbers did not come from a trained policy | Report withdrawn; runtime only uses trained parameters | `reports/shopping_benchmark_report.md` |
| 3 | Pods scraped by two jobs counted twice | Request rates 2× too high on the first laptop (v7 twin fitted on doubled rates) | Sum per (pod, job), max over jobs | `docs/POLICY_V9.md` §8 |
| 4 | cAdvisor without `container` label (Docker on cgroup v2) | CPU missing for every service → FlexaScale would hold everything | Fall back to pod-level series | `workload_metrics.py` docstring |
| 5 | Zero traffic reported as missing | Idle services looked broken | `up == 1` with no series → rate 0, `no_traffic` | same |
| 6 | `localhost` cost 2 s per query on Windows | Slow sampling | Use 127.0.0.1 (IPv4) | `docs/POLICY_V9.md` §1.1 |
| 7 | Each downstream call created its own HTTP client; order history returned every order (43k) | order-service OOM-killed in both arms; 36 runs invalidated | Shared client; history limited to 20 | `reports/final_readiness_report.md` defects 13–14 |
| 8 | Laptop power profile `balanced` | Shop ran faster whenever FlexaScale's control kept the host busy → false "beats" | Replication under `performance` profile; batch withdrawn | `docs/V7_REPORT.md` §4.1 |
| 9 | Runs on battery, Modern Standby, lid closed, laptop suspend | Disturbed or interrupted runs | Validity rule; reruns; sleep inhibition | `reports/experiments_invalid/README.md` |
| 10 | Operator killed → HPAs stayed frozen | No autoscaling until manual restore | Lab watchdog | `lab/experiments.py` |
| 11 | Two Helm releases selected each other's operator pods | Lifecycle test read the wrong pod | Release-specific selector (chart 0.5.1) | `helm/flexascale/templates/operator-deployment.yaml` |
| 12 | `kubectl` killed with no message | Empty error in logs | Report the exit code | `k8s/kube.py` |
| 13 | PPO from scratch learned "scale everything up" | v1–v3 over-provisioning (+77.5% replica-hours) | Unit-free features, bounded penalties, imitation warm start | `docs/FINAL_PROJECT_SUMMARY.md` §6 |
| 14 | Uncapped latency inflation in the reward | Rare overloads dominated gradients | Cap at 4 | `twin_env.RewardConfig` |
| 15 | Teacher rule almost never scales up (17 of 24,647 labels) | Imitation never learned scale-ups (`models/flexascale_v7_bc_imbalanced`) | Class weights + relabelled CPU augmentation | `rl/imitation_v7.py` |
| 16 | Twin queues unbounded | Unrealistic overloads (`models/flexascale_v7_unbounded_queue`) | Closed-loop bound by waiting users | `simulator/twin.py` |
| 17 | `kubectl scale` to the minimum undone by HPA's 300 s memory | Runs did not start comparably | Freeze HPAs at minimum, wait out the window, restore, verify | `Experiment._reset_replicas` |
| 18 | Confidence fallback with threshold 0.7 in early simulation | Every decision fell back to the heuristic; identical results | Thresholds revisited; benchmark superseded | `reports/benchmark_summary.json` |

### H.2 Troubleshooting (symptom → cause → what to do)

| Symptom | Likely cause | Action |
|---|---|---|
| Dashboard chip "Prometheus" red | Port-forward died | `./fsctl start` (restarts port-forwards) |
| Alert "HPA left frozen" | An operator stopped without hand-back | `./fsctl stop` (restores every HPA) |
| "Lease held outside an experiment" | A previous operator still holds or recently held it | Wait 30 s for expiry, or `./fsctl stop --force-release-lease` |
| Start refused | Another run, Locust or operator still active, or a Lease held | Stop it; check `./fsctl status` |
| "NO MODEL (CPU heuristic)" | Model file missing or incompatible | Live mode is refused; check `model_path` and the Models page |
| Telemetry "stale" or "missing" | Prometheus targets down, pods not scraped | Check targets; FlexaScale hands those services to HPA automatically |
| FlexaScale never scales on the Fedora laptop | v9 is fitted to the other laptop | Choose policy v7 |
| p95 shows "≥ 10000" | Percentile beyond the largest bucket | A lower bound, not a measurement |
| Runs not comparable on the Comparison page | Different users/duration, unsettled start, incomplete | Rerun with Comparable start |

### H.3 Common conceptual mistakes

* Confusing CPU % of **request** (HPA's signal, can exceed 100%) with CPU % of **limit** (FlexaScale's feature 0).
* Thinking the GNN outputs replica counts (it outputs embeddings; the actor outputs probabilities; the operator turns an
  action into a count; safety may change it).
* Thinking FlexaScale learns live (it does not).
* Thinking Auto mixes the two controllers' numbers (it chooses **one owner** per service per step).
* Thinking the HPA is switched off under FlexaScale (it is frozen, still running, and restored on hand-back).

---

## Section I — Viva questions and answers

### I.1 Basic

1. **What problem does FlexaScale solve?** Kubernetes' HPA scales each service on its own CPU with one fixed target, reacts
   late and keeps spike capacity for five minutes. FlexaScale uses a learned, dependency-aware policy with a safety layer,
   and keeps the HPA as a fallback.
2. **What is a microservice?** A small program that does one job and talks to others over the network.
3. **What is a pod, a Deployment, a replica?** The running unit; the instruction to keep N identical pods; one of those N.
4. **Desired vs ready replicas?** Asked for (`spec.replicas`) vs actually serving (`status.readyReplicas`); ready lags by
   ~10–15 s after a scale-up.
5. **How does the HPA decide?** `ceil(r × CPU / target)`, ±10% tolerance, scale-down uses the highest recommendation of the
   last 300 s.
6. **What is reinforcement learning?** Learning decisions by trial and error to maximise a reward.
7. **What are state, action and reward here?** 10 features per service plus the call graph; replica change −1…+3; a
   penalty for replicas, latency inflation, SLO violation, failures and churn.
8. **What is a GNN?** A network that passes information along a graph's edges.
9. **What is PPO?** An RL algorithm that improves the policy in small, clipped steps using an actor and a critic.
10. **What is Prometheus?** A time-series database that scrapes metrics; FlexaScale queries it with PromQL.
11. **What is Locust?** A load generator that simulates users.
12. **What is p95?** The time within which 95% of requests finished.
13. **What is your SLO?** End-to-end p95 ≤ 1000 ms per ~10 s window.
14. **What are replica-hours?** Ready replicas × time in hours; our main resource measure.
15. **What dataset did you use?** Alibaba cluster-trace-microservices-v2021 (30-minute shard) for v1–v6; the live shop's
    own measurements for the twin used by v7/v9.
16. **How many services and edges?** 16 services, 25 edges.
17. **What is the observe mode?** FlexaScale logs decisions without changing the cluster; the default.
18. **What are the three modes?** Native HPA (FlexaScale may shadow), FlexaScale (owns every service), Auto (per-service
    owner).
19. **How often does FlexaScale decide?** Every 10 seconds.
20. **Where is the model?** `models/flexascale_v9/best_model/best_model.zip` (SHA-256 `2f95764b…`), 42,566 parameters.
21. **What language and frameworks?** Python, PyTorch, Stable-Baselines3, Gymnasium, FastAPI; React/TypeScript dashboard;
    Kubernetes, Helm, Prometheus, Grafana, Locust.
22. **How do you start it?** `./fsctl start`, dashboard at `http://127.0.0.1:8090/`; `./fsctl stop`.
23. **How many tests?** 373, all passing.

### I.2 Intermediate

24. **Why CPU relative to the limit, not the request?** Pods saturate (are throttled) at the limit; with a 0.1-core
    request and a 0.5-core limit, "% of request" can be 400% and still be safe.
25. **Why latency relative to each service's own minimum?** Services have different normal latencies (login with bcrypt
    is slow by design); one absolute SLO for all would be wrong.
26. **Why unit-free features?** The policy is trained in a simulator and used live; ratios mean the same in both and across
    services.
27. **What exactly enters the GNN?** 20 × 10 features, a 20 × 20 adjacency matrix, a 20-mask, and a 20-number one-hot of
    the focal service: 660 numbers.
28. **What exactly comes out?** 128 numbers: the focal service's embedding after two rounds and the mean embedding of all
    services.
29. **How are callers and callees treated differently?** Separate weight matrices `W_callee` and `W_caller`; means over
    `A·H` and `Aᵀ·H`.
30. **Why two rounds?** A two-hop receptive field reaches the checkout fan-out (gateway → order → payment) while staying
    small and trainable.
31. **Why mean aggregation?** So high-degree nodes (api-gateway, 9 callees) are not dominated by the number of neighbours.
32. **What does "focal" mean?** Each service's decision is a separate row with a one-hot marking it, so each decision gets
    its own reward (credit assignment).
33. **How is the action turned into replicas?** Index → delta via the model card's `(−1, 0, +1, +2, +3)`; clipped to
    [−1, +3] and bounds 1–10; then the guards.
34. **What is confidence?** The probability of the chosen action. Thresholds are 0 in the shop's policy.
35. **What guards exist?** Bounds, step limits, budget 48, readiness, 20/30 s cooldowns, no scale-down at ≥ 400% CPU, ≥ 90%
    memory or above SLO, stale telemetry → HPA.
36. **How do you prevent FlexaScale and HPA from fighting?** Freeze the HPA (min = max = FlexaScale's count) before
    scaling; restore from annotations on hand-back; one Lease per application.
37. **What does the Lease protect against?** Two FlexaScale instances controlling the same application.
38. **What happens if the operator crashes?** The lab watchdog restores all HPAs (verified: about 1.4 s after SIGKILL); in
    the Helm install the hand-back hook covers upgrades and uninstalls.
39. **What if Prometheus goes down?** All services' telemetry becomes stale → Auto rule 1 / guard 0 → HPA in the same step
    (verified).
40. **What are the four Auto rules?** Controller health → HPA now; confidence → HPA; SLA risk with HPA wanting more → HPA
    now; otherwise efficiency → FlexaScale after 2 steps.
41. **Why is switching to FlexaScale slower than to HPA?** Handing to HPA is the safe direction; delays there could harm
    users. Hysteresis avoids flapping.
42. **What is the application twin?** A simulator fitted to the shop's measurements: CPU per request, limits, queueing,
    call graph, pod start, delayed metrics.
43. **How accurate is it?** v9 twin vs live: 2.0% replica-hours, 8.9% p95, 4.4% mean latency error.
44. **Why imitation before PPO?** PPO from scratch learned "scale everything up" or could not match a simple rule; starting
    from the rule gives a good policy that PPO can refine.
45. **What hyperparameters?** n_steps 64 × 80 agents, batch 512, 10 epochs, lr 1e-4, clip 0.1, target KL 0.02, γ 0.97, λ
    0.95, entropy 0.01, value coef 0.5, grad norm 0.5; 2M agent-steps per run.
46. **How was the model selected?** Best validation reward over 40 workloads (focal_bc_s2, −2.466), then a gate against v7.
47. **What is a tuned HPA?** HPA with the CPU target and window chosen by a rule fixed in advance: highest target whose
    p95, mean latency and failures stay within 10% of the 70% target; 350%/60 s on the second laptop.
48. **Why compare against a tuned HPA?** The default HPA over-provisions this lightly loaded shop and is easy to beat;
    the tuned one is the fair baseline.
49. **What does "pre-registered" mean?** The rules were written down before the first run, with a time-stamped record.
50. **What is a 95% CI here?** mean Δ ± t × s/√n over paired blocks; if it includes 0, no proven difference.

### I.3 Advanced

51. **Write the PPO clipped objective and explain the min.** `E[min(ρÂ, clip(ρ, 1−ε, 1+ε)Â)]`; the min takes the
    pessimistic value, so the gradient stops once the ratio leaves [1−ε, 1+ε] in the improving direction.
52. **What is GAE and why λ = 0.95?** An exponentially weighted sum of TD errors; λ balances bias (low λ) and variance
    (high λ); 0.95 is a standard, stable choice.
53. **Why γ = 0.97?** Effective horizon ~33 steps (~5.5 min): long enough to see pod start-up and cooldown effects, short
    enough for stable value estimates in 30–60-step episodes.
54. **How is the critic used?** Only in training: it gives V(s) for advantages; it is fitted with a 0.5-weighted MSE.
55. **Why per-service rewards, and do they sum to the global reward?** Each service pays its own replicas and churn plus a
    share of the latency penalty proportional to traffic share × own excess latency; the shares sum to 1, so the rewards
    sum to the global reward.
56. **What does LayerNorm do in your GNN and why the residual?** Keeps embeddings in a stable range; the residual keeps a
    node's own information and eases gradient flow.
57. **How many parameters and where?** 25,664 in the extractor, 16,512 in the two 64-unit hidden layers, 325 action head,
    65 value head = 42,566.
58. **How do you handle variable numbers of services?** 20 padded slots with a mask; padded embeddings stay 0 and are
    excluded from the mean; more than 20 services are refused.
59. **What did the graph ablation show?** Reward differences graph − no graph had CIs including 0 on T1, T2 and T3: no
    measurable benefit on this shop.
60. **Why might the graph not help here?** Load on each service is visible in its own features soon enough at 25 users;
    most services sit at the floor; the twin's 9% p95 error is as large as the differences the graph could exploit.
61. **Explain the histogram percentile interpolation and its error.** Linear inside the bucket reaching rank q × total;
    the error can be up to the bucket width (e.g. 100–250 ms).
62. **What is the difference between e2e p95 and per-service p95?** E2E from Locust, actual times; per service from
    histograms, interpolated, 1-minute window.
63. **Why is cost an estimate?** Allocated resources × public list prices; Minikube has no bill; clouds bill nodes.
64. **Explain d_z for Auto vs default replica-hours.** Mean −7.75%, SD of paired differences ≈ 6.8 → d_z ≈ −1.14, a large
    standardised effect.
65. **Why is the verdict "on par" despite a CI below zero for cost?** Check C2 failed: p95 mean +17.6% with a CI that
    includes large increases; "beats on cost" requires latency not to be worse.
66. **What is check C7?** Replica-hours lower in at least 4 of 6 scenarios, so one scenario cannot carry the result.
67. **What was the power-profile confound?** Under `balanced`, the CPU clock followed host load; FlexaScale's live control
    added ~0.55 cores of host activity, so the shop ran faster in FlexaScale arms even when decisions were identical. A
    replication under `performance` removed it.
68. **How did you check environment parity in v9?** `steady_app_cpu_per_request_delta_pct`: Auto's shop used 6% *more*
    CPU per request in steady browsing, so no hidden speed advantage.
69. **Why did v9 hold every service at one replica on the Fedora laptop?** Its behaviour was learned on the second
    laptop's twin, starting from a teacher rule that scales up at about 60% of the CPU limit; on the Fedora laptop at 40 users CPU per pod stayed at 30–50% of the
    limit while order-service was database-bound.
70. **Why didn't Auto hand those services to HPA?** Its CPU risk level (400% of request = 80% of the limit) was not reached
    and the shop has no per-service latency SLO; with a 60% threshold (controlled variant) it did.
71. **Is the Lease safe against two operators starting at the same moment?** Yes: `kubectl replace` with the
    `resourceVersion` fails for the slower one (optimistic concurrency).
72. **What if the operator dies while holding a frozen HPA and no lab is running (in-cluster)?** The Lease expires after 30
    s, but HPAs stay frozen until an operator or `./fsctl stop` restores them. The Helm hook covers upgrades and
    uninstalls. Kubernetes restarts a crashed operator pod; by reading the code, the new operator takes the expired Lease
    and, for every service it hands to HPA, `ensure_hpa_active` restores a frozen HPA. This restart path was **not**
    tested live, and a standalone in-cluster watchdog is not implemented; say so as a limitation.
73. **What is the difference between `policy_replicas` and `proposed_replicas`?** The policy's clipped proposal before
    safety vs the approved count after safety (and ownership).
74. **How is the decision for all 16 services computed efficiently?** One batched forward pass of 16 rows.
75. **Could FlexaScale manage an app without a configured topology?** Yes: edges are inferred from the gateway's forward
    counters (bookstore); without any traffic metrics only a weak name-order heuristic remains.

### I.4 Difficult examiner questions

76. **"So your RL system is no better than a tuned HPA. What is the contribution?"** A safe, explainable framework that lets
    a learned policy share control with the HPA, a fair evaluation method, and the finding that, at this scale, a
    calibrated rule matches the learned policy. Negative results are results; the framework is ready for settings where
    learned policies may help (larger, more dependent workloads).
77. **"Your best result is one flash-sale pair. Isn't that cherry-picking?"** The pooled pre-registered verdict is reported
    first; E1–E4 were selected by a stated rule to illustrate the mechanism, and the limitation (single pairs) is written
    next to them.
78. **"Why not compare with other RL autoscalers?"** Their code and setups were not available for our shop and laptop;
    the HPA (default and tuned) is the standard baseline; this is a limitation.
79. **"25 users is tiny."** Yes; the single-node cluster limited load. At 25 users most services stay at one replica,
    which bounds any saving; heavier, multi-node experiments are future work.
80. **"Simulation results are meaningless."** They are used for training and selection only; every claim about
    performance comes from live runs; the twin was checked against live runs.
81. **"Why did you change the model from v7 to v9?"** A different laptop; the twin and calibration do not transfer; v9 was
    trained for the second laptop under a new pre-registration.
82. **"Isn't the confidence fallback useless with thresholds of 0?"** It is implemented and tested, but the policy's
    probabilities were not calibrated as a correctness measure (decisions near 0.49 were correct), so health and SLA-risk
    rules gave clearer hand-back conditions.
83. **"Your SLO is end-to-end, but your guards use per-service latency. Isn't that inconsistent?"** The per-service SLO
    guard and Auto latency rule exist but are unused for the shop (no per-service SLO). Making Auto use end-to-end latency
    is the main future improvement.
84. **"How do you know the dashboard shows real values?"** It reads the same run files; missing values are "—"; the Comparison
    page uses the same code as the reports (`lab/benchmark.py`).
85. **"What would make FlexaScale beat a tuned HPA?"** Signals the HPA cannot use (latency, dependencies under real
    contention), heavier and more variable load where a fixed target is wrong for some services, and multi-node costs.
86. **"Why Stable-Baselines3 and not your own PPO?"** A tested, standard implementation reduces bugs and makes results
    reproducible; the custom part is the policy architecture and environment.
87. **"Your demo credentials are in Git."** Yes, for a local lab only; production would use Kubernetes Secrets from a
    vault.

### I.5 "Why did you choose …?"

* **GNN:** dependencies are a graph; message passing lets each decision see callers and callees; mask/padding supports
  different applications. (Honest: no measurable benefit here.)
* **PPO:** stable, few hyperparameters, works with discrete actions and shared actor-critic networks, standard in SB3;
  clipping suits a safety-critical setting.
* **Kubernetes:** the industry standard for microservices and the platform whose HPA we improve on.
* **Alibaba trace:** the largest public microservice trace with per-service CPU, memory, rate and latency; used to start
  (v1–v6); replaced by the twin when it did not transfer.
* **Minikube:** zero cost, full control, reproducible on student laptops.
* **This architecture (operator + freeze + Lease + Auto):** add-on without code changes, never two controllers, HPA always
  available.

---

## Section J — Explaining the project in 2, 5, 10 and 15 minutes

### J.1 Two minutes

"Microservice applications on Kubernetes are scaled by the Horizontal Pod Autoscaler, which looks at one service's CPU
with one fixed target. FlexaScale replaces that with a learned policy: every ten seconds it reads Prometheus telemetry,
builds ten unit-free features per service, passes them over the application's call graph with a graph neural network and
lets a PPO-trained policy propose a replica change per service. A safety layer bounds every change, a Kubernetes Lease and
an HPA freeze make sure only one controller acts on a service, and an Auto mode chooses per service whether FlexaScale or
the HPA should be in charge. We verified it live, including outages and crashes. In a pre-registered evaluation it used
about 7.5% fewer replica-hours than the default HPA, and it matched, but did not beat, a carefully tuned HPA."

### J.2 Five minutes

Add to the two-minute version: the shop (16 services, 25 edges, one PostgreSQL); the three HPA weaknesses with our numbers
(27 replicas kept for 5 minutes in a flash sale; brief CPU rises scaled in checkout-heavy load; the database-bound order
service); the twin (fitted to the shop, 2% replica-hour error), imitation then PPO, the gate; the safety guards; the Auto
rules; the verification table (Auto chose FlexaScale and Kubernetes confirmed 1→2 in 6 s / ready in 16 s; mixed ownership;
Prometheus cut; SIGKILL); the results table (default HPA vs tuned vs RL vs Auto); one limitation (per-laptop calibration
and CPU-only signal).

### J.3 Ten minutes (slide-by-slide outline)

1. Problem and motivation (1 min). 2. Objectives (0.5). 3. Literature and gap (1). 4. Architecture (1.5). 5. Features,
GNN and PPO with the real order-service decision (2). 6. Safety and Auto mode (1.5). 7. Evaluation design (1). 8.
Results: verification, pooled table, E1 chart (1.5). 9. Limitations and future work (0.5).

### J.4 Fifteen minutes (with live demo)

The ten-minute talk plus: a live Auto run in the Live lab (choose v7 on the Fedora laptop, flash sale, 25–40 users; point
at the proposal line, the ◆ marker, the desired step and the ready area); the Auto page's rule cards and ownership table;
the Comparison page with the tuned-HPA verdict; the Models page with the SHA-256; and the decision record of one step
(`decisions.jsonl`) to show explainability. Keep two minutes for the honest findings: on par with a tuned HPA, no
measurable graph benefit, and the database-bound service.
