# FlexaScale — The Complete Explanation (from zero to viva)

This document explains the whole FlexaScale project in simple English, in the order in which the system actually works.
You do not need to know Kubernetes or machine learning before reading it. Every difficult word is explained the first
time it appears, with a small example. Where a number is given, it comes from a real file in this repository; the file is
named so you can check it.

How to read it:

* Part A explains the basic ideas (microservice, Kubernetes, pod, replica, autoscaling, HPA).
* Part B walks through every component of FlexaScale, one by one, in the order data flows through them.
* Part C explains the data and the machine learning (Alibaba trace, simulator, GNN, PPO, reward, training).
* Part D follows one request and one scaling decision through the live system, step by step.
* Part E explains the three controller modes: native HPA, FlexaScale and Auto.
* Part F explains every performance measure, with formulas and worked numbers.
* Part G gives the honest results and limitations.
* Part H is a code walkthrough: which file does what, which functions matter.
* Part I is a ready-to-speak presentation script and answers to likely viva questions.

A companion document, `docs/learning/FLEXASCALE_DASHBOARD_COMPLETE_GUIDE.md`, teaches you how to operate the dashboard.

---

## Contents

* [A. Fundamentals](#a-fundamentals)
* [B. The complete architecture](#b-the-complete-architecture)
* [C. Data and machine learning](#c-data-and-machine-learning)
* [D. The complete live execution flow](#d-the-complete-live-execution-flow)
* [E. The three controller modes](#e-the-three-controller-modes)
* [F. Performance and evaluation](#f-performance-and-evaluation)
* [G. Results and limitations](#g-results-and-limitations)
* [H. Complete code walkthrough](#h-complete-code-walkthrough)
* [I. Final presentation explanation](#i-final-presentation-explanation)
* [Glossary](#glossary)

---

## A. Fundamentals

### A.1 What is a microservice?

**Simple meaning.** A microservice is a small program that does one job and talks to other small programs over the
network.

**Why it is needed.** A big online shop has many jobs: showing products, keeping carts, taking payments, checking fraud.
If all of this is one giant program (a "monolith"), one slow part slows down everything, and you must copy the whole
giant program to handle more users. With microservices, each job is its own program, so you can give more computers only
to the job that is busy.

**Inside FlexaScale.** Our test application is an e-commerce shop made of **16 microservices** written in Python
(FastAPI), plus a React website and a PostgreSQL database (`apps/services/`, Helm chart `charts/shopping-app`, version
1.1.0). Examples: `api-gateway` (the front door), `catalog-service` (products), `cart-service`, `order-service`
(checkout), `payment-service`, `inventory-service`, `fraud-service`, `shipping-service`, `pricing-service`,
`promotion-service`, `search-service`, `recommendation-service`, `review-service`, `notification-service`,
`user-service`, `wishlist-service`.

**Practical example.** When you click "Buy", the request goes `api-gateway → order-service`, and order-service then
calls `catalog-service` (prices), `inventory-service` (reserve stock), `fraud-service` (risk check),
`payment-service` (charge), `shipping-service` (quote), `cart-service` (empty the cart) and `notification-service`
(confirmation).

**Connection to the next idea.** Each microservice must run somewhere. That "somewhere" is managed by Kubernetes.

### A.2 What is Kubernetes?

**Simple meaning.** Kubernetes is software that runs your programs on a group of computers and keeps them running. You
tell it *what* you want ("3 copies of cart-service"), and it makes it so, and keeps it so.

**Why it is needed.** Without it you would start programs by hand, restart them when they crash, and move them when a
computer fails. Kubernetes automates all of that.

**Inside FlexaScale.** We use **Minikube**, which is a one-computer Kubernetes for development. The Minikube "profile"
(its name) is `flexascale`. All 16 shop services run in the Kubernetes *namespace* `flexascale-apps` (a namespace is a
named folder that groups related things). Monitoring runs in `flexascale-monitoring`.

**Example.** `kubectl get deployments -n flexascale-apps` lists the 16 services and the database.

**Connection.** Kubernetes runs programs inside **pods**.

### A.3 What is a pod?

**Simple meaning.** A pod is one running copy of a program (one or more containers that live and die together).

**Why it is needed.** Kubernetes needs a unit it can start, stop and move. That unit is the pod.

**Inside FlexaScale.** Each running copy of, say, cart-service is one pod with a name like
`cart-service-6d567c9496-sd5t4`. FlexaScale uses exactly this name pattern (`<deployment>-<hash>-<suffix>`) to know which
service a CPU measurement belongs to (`metrics/workload_metrics.py`, function `deployment_of`).

**Connection.** Pods are created and counted by a **Deployment**.

### A.4 What is a Deployment?

**Simple meaning.** A Deployment is the instruction "keep N identical pods of this program running".

**Why it is needed.** If a pod crashes, the Deployment notices that there are fewer than N and starts a new one.

**Inside FlexaScale.** Each of the 16 shop services is one Deployment. The number N is the field `spec.replicas`.
FlexaScale scales a service by changing exactly this field (through the Kubernetes *scale* sub-resource,
`safety/hpa_manager.py`, `scale_deployment`).

**Connection.** N is called the number of **replicas**.

### A.5 What is a replica?

**Simple meaning.** A replica is one copy of a service. "3 replicas" means 3 pods doing the same job, sharing the work.

**Two numbers you will always see:**

* **Desired replicas** (`spec.replicas`): how many copies Kubernetes has been *asked* to run.
* **Ready replicas** (`status.readyReplicas`): how many copies are *actually started and able to serve*.

After a scale-up from 1 to 3, desired becomes 3 immediately, but ready stays 1 for about 10 seconds while the new pods
start (measured live: median 10 s, 90th percentile 15 s, `simulator/twin.py` docstring).

**Connection.** Changing the number of replicas automatically, according to load, is **autoscaling**.

### A.6 What is autoscaling?

**Simple meaning.** Autoscaling means the system adds copies when it is busy and removes copies when it is quiet,
without a human.

**Why it is needed.** Too few replicas → slow pages and errors. Too many replicas → you pay for computers doing nothing.
Autoscaling tries to keep "just enough".

**Example.** At night the shop needs 1 replica of catalog-service. During a flash sale it may need 4. A good autoscaler
goes 1 → 4 when the sale starts and 4 → 1 after it ends.

**Connection.** Kubernetes has a built-in autoscaler called the HPA.

### A.7 What is HPA?

**Simple meaning.** HPA (Horizontal Pod Autoscaler) is Kubernetes' built-in autoscaler. "Horizontal" means it changes
the *number* of pods (not their size).

**How it decides.** It looks at one number, usually CPU use as a percentage of what each pod *requested*, and uses this
formula:

```
desired = ceil( current_replicas × current_CPU% / target_CPU% )
```

`ceil` means "round up". It ignores small differences (±10%, the "tolerance"), and it waits 5 minutes before scaling down
(the "scale-down stabilisation window") so it does not remove pods too early.

**Worked example.** cart-service has 2 replicas, CPU is at 140% of its request, the target is 70%:
`ceil(2 × 140 / 70) = ceil(4) = 4` → HPA scales to 4 replicas.

**Inside FlexaScale.** Every shop service has an HPA (`<service>-hpa`, 1–10 replicas, CPU target 70%). It is the
**baseline** we compare against, and the **safety net**: whenever FlexaScale is not in control, the HPA is.

### A.8 Why do we need FlexaScale?

HPA has three weaknesses:

1. **It looks at one service at a time.** It does not know that order-service calls payment-service, so a flash sale on
   checkout overloads payment-service a little later, and HPA reacts only when payment-service's own CPU rises.
2. **It uses one fixed rule for every service.** A service that is slow because of a database lock, not CPU, is
   invisible to a CPU rule.
3. **It is reactive.** It scales after CPU has risen, and is slow to scale down (5-minute window), which costs money.

**FlexaScale's idea:** let a learned policy look at *all* services *and how they call each other* (the call graph), and
decide per service how many replicas it needs, while a safety layer guarantees that nothing dangerous happens and that
native HPA takes over whenever FlexaScale is unsure or unhealthy.

**Honest summary of the outcome (details in Part G):** FlexaScale works end to end, safely, on a real cluster, with a
per-service Auto mode. In careful, pre-registered experiments it is **on par with a well-tuned HPA** — it is not shown
to beat one. That is a valid and useful research result.

---

## B. The complete architecture

The live system is a loop. Data flows in this order:

```
 Locust users ──HTTP──▶ Shop (16 services on Kubernetes)
                               │  each service exports /metrics
                               ▼
                         Prometheus  (cAdvisor CPU/memory every 10 s; service /metrics every 15 s)
                               │  PromQL queries
                               ▼
  ┌──────────────────── FlexaScale operator (every 10 s) ─────────────────────┐
  │ 1 Service discovery  →  2 Telemetry  →  3 State aggregation (features)    │
  │ 4 Dependency graph   →  5 GNN + PPO policy  →  6 Proposal per service     │
  │ 7 Auto arbiter (who owns each service)  →  8 Safety guards                │
  │ 9 Execution: freeze HPA, scale Deployment (only with the Lease)           │
  │10 Decision log (proposed vs applied)                                      │
  └───────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                 Kubernetes changes desired → pods start → ready
                               │
                               ▼
              new load, new metrics ──▶ Dashboard (Live lab, timeline)
```

Below, every component is explained with the same five points: meaning, why, what FlexaScale does, example,
connection.

### B.1 Metrics pipeline

1. **Meaning.** The set of pieces that measure the system and store the numbers.
2. **Why.** An autoscaler that cannot see load cannot decide anything.
3. **In FlexaScale.** Three kinds of numbers are collected:
   * **CPU and memory per pod** from *cAdvisor* (a part of Kubernetes' node agent, the kubelet).
   * **Request counts and latency** from each service's own `/metrics` endpoint. Every service counts requests in
     `http_requests_total` and records how long each request took in a *histogram* `http_request_duration_seconds`
     (`apps/services/*/src/metrics.py`).
   * **Deployment state** (desired/ready replicas, HPA settings) directly from the Kubernetes API.
4. **Example.** `http_requests_total{pod="cart-service-…", status="200"} 1532` means that pod has answered 1532
   requests with status 200 since it started.
5. **Connection.** These numbers are stored and served by Prometheus.

### B.2 Prometheus

1. **Meaning.** A time-series database: it stores numbers with timestamps and answers questions in a query language,
   PromQL.
2. **Why.** We need *rates* ("requests per second over the last minute") and *percentiles*, not raw counters.
3. **In FlexaScale.** Installed by the Helm release `monitoring` (chart kube-prometheus-stack). It scrapes cAdvisor (CPU, memory)
   every 10 s and each service's `/metrics` every 15 s (ServiceMonitor; a second, annotation-based job every 30 s). FlexaScale asks it a handful of batched queries per step, all over a **1-minute window**
   (`metrics/workload_metrics.py`, `WorkloadMetricsClient.collect`), for example:
   ```
   sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="flexascale-apps",container="",pod!=""}[1m]))
   ```
   Three real-world problems are handled explicitly (each one silently corrupted data before it was fixed):
   * **Pod-level CPU only.** On some setups cAdvisor reports CPU per pod, not per container, so the query falls back to
     pod-level series.
   * **Counted twice.** Each pod is scraped by two jobs (a ServiceMonitor *and* an annotation job). Request rates are
     summed per (pod, job) and then the *maximum* over jobs is taken, so nothing is counted twice.
   * **Zero vs missing.** A service that is scraped but has no request series has served *zero* requests (a real 0,
     shown as "no requests"); a service that is not scraped at all is *missing* (shown as "—"). Nothing is invented.
4. **Example.** Prometheus is at `http://localhost:9090` while the lab runs (a port-forward started by `./fsctl start`).
5. **Connection.** Grafana draws Prometheus data; the FlexaScale operator and the lab read it directly.

### B.3 Grafana

1. **Meaning.** A dashboard tool that draws graphs from Prometheus.
2. **Why.** Engineers use it to look at raw metrics.
3. **In FlexaScale.** Available at `http://localhost:3000` (from the monitoring Helm release); its CPU and memory panels
   select every container in the shop namespace. FlexaScale's own control center (Part B.15) is the main dashboard;
   Grafana is the "second opinion" view of the same Prometheus data.
4. **Example.** Open Grafana during a run and you will see the same CPU rise that the FlexaScale dashboard shows.
5. **Connection.** Grafana only displays; decisions start with service discovery.

### B.4 Service discovery

1. **Meaning.** Finding out automatically which services exist, instead of hard-coding names.
2. **Why.** FlexaScale must work for any application, not just this shop (it is also tested on a 5-service
   "bookstore", `examples/bookstore/`).
3. **In FlexaScale.** `discovery/workloads.py`, class `WorkloadDiscovery`, lists all Deployments in the application's
   namespace that carry the label from the policy file (`app.kubernetes.io/part-of=flexascale-ecommerce`), finds each
   one's HPA by its `scaleTargetRef` (not by name), reads CPU/memory requests and limits, desired and ready replicas,
   and excludes databases and anything listed in `exclude` (the shop excludes `shopping-frontend` and `postgres`).
   Result: a list of `WorkloadInfo` objects.
4. **Example.** Result for the shop: 16 eligible services, each with HPA `<name>-hpa` (min 1, max 10).
5. **Connection.** The discovered names decide which telemetry to collect and how the state is built.

### B.5 State aggregation

1. **Meaning.** Turning many raw measurements into a tidy summary per service that the policy can read.
2. **Why.** The policy needs the same kind of numbers, in the same order and the same units, every time.
3. **In FlexaScale.** For each service the operator builds a `WorkloadMetrics` record (`cpu_pct`, `memory_pct`,
   `request_rate`, `error_rate`, `latency_mean_ms`, `latency_p50/p90/p95/p99_ms`, `stale`, `no_traffic`, `missing`).
   CPU is expressed **as a percentage of the CPU request**, exactly like HPA, so both controllers see the same signal.
   If a value is missing, it stays `None` and is listed in `missing`; it is never replaced by a guess.
4. **Example.** `cart-service: cpu_pct 52.1, request_rate 6.4 req/s, latency_mean_ms 169.8, p95 667.5 ms`.
5. **Connection.** These records are converted into the policy's input numbers, the *state vector*.

### B.6 State vector (observation)

1. **Meaning.** A list of numbers that describes the situation of one service at one moment; the "eyes" of the policy.
2. **Why.** A neural network can only read numbers.
3. **In FlexaScale (deployed model v9, observation version 3, `rl/features_v3.py`).** Ten unit-free numbers per
   service, in this fixed order:

   | # | Name | Meaning | Range |
   |---|---|---|---|
   | 0 | cpu_limit_frac | CPU per ready replica ÷ CPU *limit* (how close to throttling) | 0–2 |
   | 1 | cpu_limit_trend | change of #0 since the previous decision | −1–1 |
   | 2 | rps_trend | request rate now ÷ about 60 s ago | 0–3 |
   | 3 | latency_inflation | log2(latency ÷ the service's own low-load latency) | −1–4 |
   | 4 | replica_frac | replicas ÷ max replicas (10) | 0–1 |
   | 5 | ready_frac | ready ÷ desired | 0–1 |
   | 6 | cpu_per_request | log10(CPU-ms per request) ÷ 3 | 0–1 |
   | 7 | burstiness | log2(peak ÷ mean request rate over 5 min) | 0–3 |
   | 8 | since_scale_up | seconds since last scale-up ÷ 60 | 0–1 |
   | 9 | since_scale_down | seconds since last scale-down ÷ 60 | 0–1 |

   "Unit-free" means the numbers are ratios, so a slow service and a fast service can be compared. The **same code**
   (`FeatureTracker.update`) computes these numbers in training (simulator) and in the live operator, so "feature 3 =
   1.0" means the same thing in both.
4. **Example.** cart-service using 0.25 cores per pod with a 0.5-core limit → feature 0 = 0.5. Its latency 160 ms vs its
   normal 40 ms → feature 3 = log2(4) = 2.
5. **Connection.** The states of all services are placed on the dependency graph.

### B.7 Dependency graph

1. **Meaning.** A picture of "who calls whom": each service is a **node**, each call relationship is an **edge**
   (an arrow from caller to callee).
2. **Why.** Load flows along the arrows. If api-gateway gets twice the traffic, order-service and payment-service will
   soon too.
3. **In FlexaScale.** The shop's policy file `config/apps/shopping.yaml` lists 25 edges under `topology`, e.g.
   `[order-service, payment-service]`. If a policy has no topology, the operator can infer edges from observed
   inter-service traffic (`state/graph_inference.py`, `LiveGraphInference`). Node order is always the **sorted**
   service names, so service *i* is always the same service.
4. **Example.** `api-gateway → order-service → payment-service`: payment's node receives messages from order's node.
5. **Connection.** The graph and the states go into the GNN.

**Topology limitation (documented):** the graph is fixed in the policy file for the shop; edges that exist in the code
but are not listed are invisible to the policy. The model has 20 node slots (`n_max = 20`), so an application with
more than 20 services is refused as incompatible (the Models page checks this).

### B.8 GNN (Graph Neural Network)

1. **Meaning.** A neural network that works on a graph: each node repeatedly mixes its own information with its
   neighbours' information ("message passing").
2. **Why.** So the decision for payment-service can use the fact that order-service, which calls it, is getting busy.
3. **In FlexaScale (`rl/graph_policy.py`, `GraphFocalExtractor`).**
   * Each service's 10 features go through a small layer → a vector of 64 numbers (its *embedding*).
   * **Two rounds** of message passing. In each round, a service's new embedding = its own embedding + the average of
     its **callees'** embeddings + the average of its **callers'** embeddings (separate learned weights for each
     direction), followed by a normalisation and ReLU (a simple "keep positives" function).
   * For the service being decided (the "focal" service), the output is its own final embedding plus the average
     embedding of the whole application: 128 numbers.
4. **Example.** After two rounds, payment-service's embedding contains information from order-service (one hop) and
   from api-gateway (two hops).
5. **Connection.** These 128 numbers go into the PPO policy head, which chooses an action.

**Important honesty point:** a "no-graph" version (same network without message passing) was trained as an ablation.
Its performance was statistically the same (Part G). The graph is part of the design, but the experiments did not show
that it helps on this shop.

### B.9 PPO (Proximal Policy Optimization)

1. **Meaning.** A reinforcement-learning algorithm that improves a *policy* (a decision rule) by trial and error,
   changing it only a little each time ("proximal" = stay close), which keeps training stable.
2. **Why.** We cannot write down the perfect scaling rule; we want the computer to learn it from experience.
3. **In FlexaScale.** Stable-Baselines3 PPO with an **actor** (chooses the action) and a **critic** (estimates how good
   the situation is). For each service, the actor outputs probabilities for 5 actions: change replicas by
   **−1, 0, +1, +2, +3**. Training settings (`scripts/train_v7.py`, `FOCAL_PPO_KW`): learning rate 3e-4, discount
   γ = 0.97, GAE λ = 0.95, clip range 0.2, entropy coefficient 0.01, 10 epochs per update.
4. **Example.** The actor says for cart-service: −1: 2%, 0: 70%, +1: 25%, +2: 2%, +3: 1%. Live, the operator takes the
   most likely action (0 = hold) and reports its probability (0.70) as the *confidence*.
5. **Connection.** The chosen change becomes a **proposal**, which goes to Auto mode (if on) and the safety layer.

### B.10 Reward function

1. **Meaning.** The "score" the simulator gives after each decision; PPO learns to make the score as high as possible.
   Our reward is a *penalty* (negative), so higher = less bad.
2. **Why.** It tells the learner what "good autoscaling" means: few replicas *and* fast, error-free responses.
3. **In FlexaScale (v7/v9 reward, `simulator/twin_env.py`, `RewardConfig`), per 10-second step, measured in
   "replica-equivalents":**
   ```
   reward = −( 1.0  × replicas above each service's minimum
             + 6.0  × min(4, p95 / p95_with_ample_capacity − 1)      (latency inflation, capped at 4)
             + 10.0 × fraction of the step with end-to-end p95 > 1000 ms (SLO violation)
             + 5.0  × percent of requests failing
             + 0.25 × number of replica changes )                      (churn)
   ```
   (all multiplied by 0.1 for scale). Each term answers a question like "how many extra replicas is avoiding an SLO
   violation worth?" — here, 10.
4. **Example.** A step with 3 extra replicas, no slowdown, no errors, 1 change: −(3 + 0 + 0 + 0 + 0.25) × 0.1 = −0.325.
   A step with 0 extra replicas but p95 doubled (inflation 1) and the SLO broken half the time:
   −(0 + 6 + 5 + 0 + 0) × 0.1 = −1.1. So the learner prefers paying for 3 replicas.
5. **Connection.** The reward only exists in the simulator, where PPO trains.

### B.11 Simulator

1. **Meaning.** A program that imitates the shop, so the policy can practise millions of decisions quickly and safely.
2. **Why.** Training on the real cluster would take months and could break the shop.
3. **In FlexaScale.** Two generations:
   * **v1–v6:** Gymnasium environments driven by the **Alibaba cluster trace** (`simulator/flexascale_env.py`,
     `dependency_env.py`, `control_env.py`).
   * **v7 and v9: the application "twin"** (`simulator/twin.py`, `twin_env.py`). It was *fitted to measurements of our
     own shop* (`scripts/fit_twin.py`, `config/twin/shopping.json` and `shopping_v9.json`): CPU per request per
     service, the 0.5-core CPU limit, queueing, call graph, pod start time (10–15 s), and controllers that see delayed
     metrics like the real ones. One step = 10 s. Training workloads are random variations of the six live scenarios,
     and 25% of episodes use a randomly generated application so the policy must read the graph rather than memorise
     names.
4. **Example.** The v9 twin reproduces live runs with 2.0% error in replica-hours and 8.9% in p95
   (`reports/v9/twin_check.md`).
5. **Connection.** The trained policy is saved as a checkpoint and loaded by the operator.

### B.12 Safety controller

1. **Meaning.** A set of rules that check every proposal before it can touch the cluster.
2. **Why.** A learned policy can be wrong. Safety rules make sure a wrong decision cannot do serious harm.
3. **In FlexaScale (`operator/app_operator.py`, `_decide`, plus the policy file).** In this order:
   * **Bounds:** never below the service's minimum or above its maximum (1–10).
   * **Step size:** at most +3 up and −1 down per step (`max_step`, `max_scale_down_step`).
   * **Replica budget:** the whole application may not exceed 48 replicas (`max_total_replicas`), so the node is never
     overloaded.
   * **Readiness:** no scale-up while earlier new pods are still starting; no scale-down while pods are not ready.
   * **Cooldowns:** 20 s after a scale-up, 30 s after a scale-down (telemetry must catch up first).
   * **Scale-down blocks:** no scale-down while CPU ≥ 400% of request, memory ≥ 90%, or latency above the SLO.
   * **Missing or stale telemetry:** no decision at all; the service goes to native HPA (`telemetry_unavailable`).
   * **Ownership lock and Lease** (B.13).
   Every decision records `safety_reasons` (e.g. `scale_up_cooldown`) or `accepted`.
4. **Example.** The policy proposes cart-service 2 → 5 (+3), but a scale-up happened 12 s ago → `scale_up_cooldown`,
   the approved count stays 2.
5. **Connection.** Approved decisions go to execution.

### B.13 Kubernetes operator and execution

1. **Meaning.** An *operator* is a program that watches Kubernetes and changes it to reach a goal. Ours is the
   FlexaScale operator (`operator/app_operator.py`, started by `scripts/run_operator.py`, or in-cluster by the Helm chart
   `helm/flexascale`).
2. **Why.** Something must actually send the scaling request, and must make sure two controllers never fight.
3. **In FlexaScale.**
   * **Modes:** `observe` (computes and logs everything, changes nothing — the default) and `live`.
   * **Lease:** in live mode the operator must first take a Kubernetes **Lease** object `flexascale-shopping` (a lock
     with an owner and an expiry, renewed every step, 30 s). Only one FlexaScale controller can hold it.
   * **Freezing the HPA:** before FlexaScale changes a service, it sets that service's HPA to `minReplicas = maxReplicas =
     the new count` and stores the original bounds in annotations on the HPA. A frozen HPA cannot move the replicas, so
     **HPA and FlexaScale never act on the same Deployment at the same time**.
   * **Scaling:** then it sets the Deployment's replicas (`HPAManager.scale_deployment`).
   * **Hand-back:** when FlexaScale gives a service back (Auto rule, low confidence, missing telemetry, stop, error,
     lost Lease, shutdown), it restores the HPA's original bounds from the annotations (`ensure_hpa_active`,
     `restore_all_frozen`).
4. **Example.** Lab log line: "cart-service: FlexaScale requested 1 → 2 (scale_up, confidence 0.71, ppo_graph)", then
   "cart-service: desired replicas 1 → 2 (owner: FlexaScale)", then "cart-service: 2/2 replicas ready".
5. **Connection.** If anything goes wrong, the HPA fallback takes over.

### B.14 HPA fallback

1. **Meaning.** "If FlexaScale cannot or should not control a service, native HPA does."
2. **Why.** The application must never be left without an autoscaler.
3. **In FlexaScale.** Fallback happens per service or for all services:
   * per service: missing/stale telemetry, low policy confidence, Auto's SLA-risk rule, `hpa_fallback: true` policy;
   * all services: operator stop (SIGTERM/SIGINT), a step that throws an error, losing the Lease, and — added in this
     final phase — the **lab watchdog**: if the operator process dies (even killed without warning) or stops updating its
     status for 4 poll intervals during an experiment, the lab restores every HPA itself and logs a `fallback` event
     (`lab/experiments.py`, `Experiment._check_operator`).
   * After every experiment, cleanup restores all HPAs and verifies that no Lease is held (`cleanup.safe`).
4. **Example.** In the verification run `auto_crash` the operator was killed with SIGKILL; the watchdog restored all
   frozen HPAs within one sample interval and native HPA scaled the rest of the run (`results/verification/`).
5. **Connection.** All of this is shown on the dashboard.

### B.15 Dashboard (FlexaScale control center)

1. **Meaning.** The web page where you watch and operate everything: `http://127.0.0.1:8090/`.
2. **Why.** For a demonstration and for checking that the system really does what we claim.
3. **In FlexaScale.** A React + TypeScript + Vite + Tailwind app (`dashboard/`), built into
   `src/flexascale/lab/static/` and served by the lab server (`lab/server.py`, FastAPI). Pages: Overview, Service
   topology, Live lab, Auto mode, Comparison, Experiments, Models. The **Live Autoscaling Timeline** shows desired and
   ready replicas, FlexaScale and HPA proposals, scaling events, traffic and latency, live or as a replay.
4. **Example.** Start a flash-sale run in the Live lab and watch the replica line step up as pods become ready.
5. **Connection.** The traffic for these runs comes from Locust. (Full manual: the dashboard guide.)

### B.16 Locust

1. **Meaning.** A load-testing tool: it simulates many users clicking through the shop.
2. **Why.** To create realistic, repeatable traffic, so two controllers can be compared under the *same* load.
3. **In FlexaScale.** `load-testing/locustfile.py` defines user journeys (browsing, shopping, flash-sale buying, slow and
   declined payments); `load-testing/scenarios.py` mixes them and shapes the number of users over time. Six scenarios:

   | Scenario | Shape |
   |---|---|
   | steady_browsing | constant users, mostly browsing |
   | gradual_ramp | users grow in 6 steps to the peak, then plateau |
   | flash_sale | 20% of peak for the first 25% of the time, then the full peak until 65%, then back to 20% |
   | checkout_heavy | mostly carts and checkouts |
   | traffic_drop | peak for 45% of the time, then 10% (tests scale-down) |
   | payment_degradation | 300 ms payment delays and declined cards |

4. **Example.** flash_sale with 40 users and 300 s: 8 users for 75 s, 40 users until 195 s, then 8 users.
5. **Connection.** Locust's own measurements (throughput, p50/p90/p95/p99, failures) are the "end-to-end" results of an
   experiment; they come from the user's side, so they include every service on the path.

---

## C. Data and machine learning

### C.1 Alibaba Cluster Trace

**What it is.** A public dataset published by Alibaba of measurements from their real microservice production cluster
(`cluster-trace-microservices-v2021`). It contains, per microservice and per minute, CPU and memory use, number of
instances, request rate and response time.

**How FlexaScale used it.** The raw files (7.4 GB, not in Git: `data/raw/alibaba/v2021/`) were turned into
`data/processed/alibaba_service_state.csv` (36,355 rows) with train/validation/test splits *by service* (so the test
services were never seen in training). It drove the simulators of the **v1–v6** policies.

**Why later versions moved away from it.** A policy trained on Alibaba's services had never seen *our* shop, and the
earlier simulators made HPA's rule optimal by construction. v7 and v9 therefore train on the **twin**, a simulator
fitted to our own shop's measurements (Part B.11). The Alibaba data is still used in the data-quality report and the
older evaluations.

### C.2 Data preprocessing

* **Meaning.** Cleaning and reshaping raw data into a usable table.
* **What was done** (`data/build_dataset.py`, `data/preprocessing.py`, `scripts/fix_dataset_units.py`):
  joining resource and request files per service and minute, counting replicas as distinct instance IDs, averaging
  request rate and latency, and converting CPU/memory from fractions (0–1) to **percent** (0–100). That last step was a
  real bug: the first model was trained on near-zero CPU because the units were wrong (defect 1 in
  `reports/final_readiness_report.md`). The conversion is recorded in `data/processed/PROVENANCE.json`.
* **Example.** A row: `service=S_123, minute=42, cpu_utilization=37.5, memory_utilization=61.0, replicas=3, rps=120,
  latency_ms=18`.

### C.3 Training data

For v7/v9 the "training data" is not a table but **experience generated by the twin**: random workloads around the six
scenarios (peak 8–45 users, durations 300–600 s, random spikes or drops) plus random synthetic applications. Validation:
40 fixed random workloads. Test: three held-out sets (T1: the six live scenarios × 5 seeds; T2: 60 random shop
workloads; T3: 40 random applications), run only once at the end (`reports/v9/ablation.md`).

### C.4 Agent, environment, policy

* **Agent:** the learner that makes decisions (PPO + GNN).
* **Environment:** the world the agent acts in (the twin in training, the real cluster live).
* **Policy:** the agent's decision rule: "given this observation, choose this action". It is the neural network.

### C.5 State and action spaces

* **State (observation) space:** what the agent can see: 10 features per service × up to 20 services, the 20 × 20
  adjacency matrix (who calls whom), a mask (which of the 20 slots hold a real service) and a one-hot "focal" vector
  (which service is being decided now). For v9 that is 640 numbers (`observation_dim: 640` in the model info).
* **Action space:** what it can do per service: one of 5 replica changes {−1, 0, +1, +2, +3}.

### C.6 Reward

See B.10. The reward is per step; the agent maximises the *sum* of future rewards, with later rewards weighted a little
less (γ = 0.97 per step).

### C.7 Episode and step

* **Step:** one decision moment (10 seconds of simulated time): observe → act → reward.
* **Episode:** one complete simulated experiment, e.g. a 300-second flash sale = 30 steps. Then the twin resets.

### C.8 Observation

The concrete numbers seen at one step (one instance of the state space). Example for cart-service:
`[0.50, 0.10, 1.8, 1.2, 0.1, 1.0, 0.43, 0.9, 1.0, 1.0]` → half of its CPU limit, CPU rising, traffic 1.8× higher than a
minute ago, latency 2.3× its normal value, 1 of 10 replicas, all ready, …

### C.9 Training versus inference

* **Training:** the policy *learns*. Millions of steps in the twin; weights change. v9: 4 runs × 2,000,000 agent-steps
  on an RTX 3050 GPU in about 63 minutes (GPU was 1.79× faster than the best CPU setup, `docs/POLICY_V9.md` §2).
* **Inference:** the policy is *used*. One forward pass per service per 10 s on the live cluster, on the CPU, in
  milliseconds; weights never change.

### C.10 GNN nodes and edges

* **Node** = a service (with its 10 features). **Edge** = "caller → callee". The adjacency matrix has a 1 at
  (caller, callee). Messages travel both ways along each edge with different weights (B.8).

### C.11 PPO actor and critic

* **Actor:** "what should I do?" → probabilities for the 5 actions per service.
* **Critic:** "how good is this situation?" → one number (expected future reward). It is used only in training, to judge
  whether an action turned out better or worse than expected (the *advantage*). The update makes better-than-expected
  actions more likely, but only within a clipped range (±20%) so the policy changes gradually.

### C.12 Warm start (imitation)

PPO from scratch learned "scale everything up" in early versions. v5 onward first **imitates a simple rule** (behaviour
cloning), then improves it with PPO. v9's teacher was the rule `limit_target(0.6/0.3)`: scale up when CPU per replica
exceeds 60% of the limit, scale down below 30% (`rl/imitation_v7.py`).

### C.13 Model checkpoints

A checkpoint is the saved network weights at some point of training (a `.zip` from Stable-Baselines3). The deployed one
is `models/flexascale_v9/best_model/best_model.zip` (sha256 `2f95764b…`), with a `model_card.json` describing
features, actions, reward, training runs and validation. Older models (v2–v7) are kept for comparison and
reproducibility; none is overwritten.

### C.14 Model evaluation

1. **Validation** (choose the best checkpoint): 40 twin workloads. v9's selected run `focal_bc_s2` scored −2.47
   (the best of 4 runs; the seed-to-seed spread was 0.52, as large as any design difference).
2. **Gate** (is it better than the previous model?): v9 −2.47 vs v7 −2.91 on the same validation set → passed. (Same set
   as selection, which favours v9; noted honestly.)
3. **Held-out twin tests** T1–T3 (once, after everything): v9 is not measurably better than v7 (`reports/v9/v9_vs_v7.md`).
4. **Live, pre-registered evaluation** on the real cluster (Part G).

---

## D. The complete live execution flow

This is what happens, in order, during one experiment (say, Auto mode, flash sale, 40 users).

1. **A user opens the shop.** The browser loads the React site from `shopping-frontend` through the Minikube ingress
   (`http://<minikube ip>/`). Clicking a product sends `GET /api/products/12` to `api-gateway`, which forwards it to
   `catalog-service`. Each service records the request in `http_requests_total` and its duration in the histogram.
2. **Locust generates traffic.** You press **Start** in the Live lab. The lab server first prepares a *comparable
   start*: it resets the shop data (restock, empty carts), scales every service to its minimum, waits until all are
   ready (and, if a run just ended, until HPA's 5-minute scale-down memory has expired). Then it starts the operator
   (here in live + Auto mode) and Locust, which follows the flash-sale shape: 8 users, then 40, then 8.
3. **Prometheus collects metrics.** It scrapes CPU and memory from cAdvisor every 10 s, and request counters and
   histograms from each service every 15 s.
4. **The state aggregator builds observations.** Every 10 s the operator (`AppOperator.step`) discovers the 16
   services, runs the batched PromQL queries over a 1-minute window, and builds each service's 10 features with
   `FeatureTracker.update`. A service with missing CPU is marked `telemetry_unavailable`.
5. **The dependency graph is created.** The 25 edges from the policy file, restricted to the services found, in sorted
   node order.
6. **The GNN processes the graph.** `PolicyRuntime.predict_graph` packs features + adjacency + mask (+ focal one-hot)
   and runs two rounds of message passing.
7. **PPO selects an action.** For each service the actor's most likely action, e.g. cart-service +1 with confidence
   0.71. This is the **proposed** replica count (`policy_replicas`).
8. **Auto mode chooses the owner, then safety checks the action.** The Auto arbiter (Part E) decides FlexaScale or HPA
   for each service; the safety guards (B.12) may reduce or block the change. The result is the **approved** replica
   count (`proposed_replicas` in the log) and the list of `safety_reasons`.
9. **Kubernetes changes replicas.** For a FlexaScale-owned service with a change: renew the Lease, freeze its HPA at
   the new count, set the Deployment's replicas. The decision is logged with `applied: true`. For an HPA-owned service:
   its HPA is (re)activated with its original bounds and HPA scales it by its own formula.
10. **Pods become ready.** Kubernetes starts the new pods; ~10 s later `readyReplicas` rises. The lab samples every 5 s
    and records `replicas` (desired changed) and `ready` events.
11. **New metrics are collected.** With more replicas, CPU per pod drops and latency recovers; the next steps see that.
    Cooldowns stop the operator from reacting again before the metrics reflect the change.
12. **The dashboard displays the result.** The timeline draws desired (solid line) and ready (filled area) replicas,
    the FlexaScale proposal (dashed green with circles), the HPA recommendation (dotted), scale-request diamonds, owner
    bands, traffic and latency. When the run ends, the lab stops Locust and the operator, restores every HPA, checks
    that the Lease is free (`cleanup.safe = true`), and writes `reports/experiments/<run id>/run.json`, `telemetry.csv`,
    `decisions.jsonl` and Locust's CSVs.

**The feedback loop.** Load → metrics → decision → replicas → new load per replica → new metrics → next decision. Every
10 s, for every service, for the whole run.

---

## E. The three controller modes

### E.1 Mode 1 — Native HPA

Kubernetes' HPA scales every service by `ceil(replicas × CPU / 70%)`. FlexaScale may run in **shadow mode**: it computes
and logs what it *would* do, but changes nothing (`mode: observe`, no Lease, no frozen HPA). Use it as the baseline and
to see FlexaScale's opinion safely.

*Simple example:* during the flash sale catalog-service reaches 160% CPU on 1 replica → HPA asks for
`ceil(1 × 160/70) = 3` replicas.

### E.2 Mode 2 — FlexaScale

The operator runs in live mode, takes the Lease, and owns every service whose telemetry is fresh (the shop's policy uses
confidence thresholds of 0, so a service is never handed back for low confidence). Every change goes through the
safety guards. A service with missing telemetry is handed to its HPA for that step.

*Simple example:* the policy sees order-service's latency inflate and its callers' traffic rise, proposes +2, safety
approves +2 (within the budget, no cooldown), the HPA is frozen at 3 and the Deployment set to 3.

### E.3 Mode 3 — Auto

Auto mode decides, **for each service separately and every 10 s**, who should own it. It computes both FlexaScale's
proposal and HPA's recommendation from the same telemetry and applies these rules **in order**; the first rule that
applies decides (`operator/auto_mode.py`, `AutoArbiter.decide`):

1. **Controller health → HPA, immediately**, if there is no trained model, the service's CPU telemetry is missing or
   stale, or FlexaScale does not hold the Lease.
2. **Policy confidence → HPA** if the policy's probability for its action is below the activation threshold (to take
   over) or the deactivation threshold (to keep a service). (Both are 0 in the shop's policy, so this rule never fires
   there.)
3. **SLA risk → HPA, immediately**, if the service is over its latency SLO or its CPU is at or above the risk level, *and*
   HPA would run **more** replicas than FlexaScale proposes. "Capacity first": when there is risk, the more generous
   controller wins.
4. **Efficiency → FlexaScale** otherwise.

**Hysteresis.** A switch *to* FlexaScale must be chosen on 2 consecutive steps (`dwell_steps: 2`); a switch to HPA for
health or SLA risk is immediate (the safe direction). This prevents flapping.

**Ownership.** The owner is enforced by the same freeze/restore mechanism as Mode 2, under one Lease: the two controllers
never act on the same Deployment at the same time. Different services can have different owners at the same moment —
e.g. order-service with HPA (SLA risk) while catalog-service is with FlexaScale (efficiency).

**What if a controller fails?**

* FlexaScale's telemetry fails for a service → rule 1 → that service goes to HPA in the same step.
* Prometheus is completely down → every service → HPA (verified live, `results/verification/`).
* The operator crashes or is killed → the lab watchdog restores every HPA (verified live).
* The Lease is lost → all services back to HPA, operator drops to observe.

**Default thresholds in the shop's policy:** CPU risk 400% of request (= 80% of the 0.5-core limit), HPA
recommendation computed at 350% (the calibrated "tuned HPA" target on the second laptop). With these, Auto gives most
services to FlexaScale at moderate load. A *controlled* verification variant (`config/apps/shopping_verify_sla.yaml`,
CPU risk 60%, HPA at 70%) makes the SLA-risk rule fire under a flash sale, to demonstrate mixed ownership. It is used
only for verification, never for benchmarks.

---

## F. Performance and evaluation

### F.1 Throughput and requests per second

**Throughput** = completed requests per second (req/s). 3,000 requests in 300 s → 10 req/s. Higher is better *when the
offered load is the same* (Locust users wait for responses, so a slow system also receives fewer requests).

### F.2 Latency

The time from sending a request to receiving the full answer, in milliseconds (ms).

### F.3 Percentiles: p50, p90, p95, p99

Sort all request times from fastest to slowest:

* **p50 (median):** half the requests were faster than this.
* **p90:** 90% were faster; 1 in 10 was slower.
* **p95:** 95% were faster; 1 in 20 was slower.
* **p99:** 99% were faster; 1 in 100 was slower.

*Worked example.* 20 requests (ms): 10, 12, 12, 13, 14, 15, 15, 16, 18, 20, 21, 22, 25, 30, 35, 40, 60, 90, 300, 1200.
p50 ≈ 20–21 ms; p90 = the 18th value = 90 ms; p95 = the 19th value = 300 ms; the mean is 99.9 ms (pulled up by the one
1200 ms request). This is why percentiles describe user experience better than the mean.

**Two sources in FlexaScale:**
* *End-to-end* (Locust): from the user's side, whole run (`summary.workload`) or a ~10 s window (live samples).
* *Per service* (Prometheus histogram, 1-minute window): `histogram_quantile` over the service's buckets. p50, p90, p95
  and p99 are all computed from the **same** histogram and window, so they are consistent (p50 ≤ p90 ≤ p95 ≤ p99). If a
  percentile falls beyond the largest bucket (10 s), the true value is unknown but at least 10 s: it is flagged
  (`latency_capped`) and the dashboard shows "≥ 10000".

### F.4 Error rate

`failed requests ÷ all requests × 100`. 12 failures out of 3,000 → 0.4%.

### F.5 CPU utilisation

CPU used ÷ CPU *requested*, in percent (HPA's definition). A shop pod requests 0.1 core and may use up to its 0.5-core
limit, so CPU can be up to 500% "of request". 0.07 cores used → 70%.

### F.6 Memory utilisation

Working-set memory ÷ the memory limit. 96 MiB of 256 MiB → 37.5%.

### F.7 SLA and SLO

* **SLO (service-level objective):** the internal target, e.g. "end-to-end p95 ≤ 1000 ms".
* **SLA (agreement):** the promise to customers built on SLOs. We use "SLA" loosely for our SLO, as the dashboard does.
* **SLA violated** in a 10 s window when Locust's p95 in that window is above 1000 ms (`e2e_slo_violation`). The
  dashboard's verdict uses exactly the number it shows: if the p95 shown is 1,240 ms, the SLA is shown as violated.
* **SLA violation time** = total seconds of violated windows; **fraction** = violated windows ÷ all windows.

### F.8 Replica-hours

The sum over time of *ready* replicas × time. 16 services at 1 replica for 300 s = 16 × 300 / 3600 = **1.33
replica-hours**. If catalog-service ran 3 replicas for 120 s of that, add 2 × 120 / 3600 = 0.067 → 1.40.

### F.9 Resource efficiency

`CPU actually used ÷ CPU allocated (requested)`. 0.12 vCPU-h used of 0.40 vCPU-h allocated → 30% allocation efficiency.
Higher means less waste, but too high means no headroom.

### F.10 Estimated cloud cost

`allocated vCPU-hours × $0.04048 + allocated GiB-hours × $0.004445` (AWS Fargate on-demand list prices, us-east-1, set in
the policy file). Example: 0.4 vCPU-h and 2 GiB-h → 0.0162 + 0.0089 = **$0.025**. It is an *estimate of what the same
allocation would cost*, not a bill.

### F.11 Scaling delay

Time from a decision to the effect: `decision → desired changes` (seconds, Kubernetes API) and `→ ready` (pod start,
~10–15 s). The verification report lists both for every applied FlexaScale action.

### F.12 Oscillation

A reversal: up then down (or down then up) within a short time. Counted per service from the desired-replica series
(`evaluation/cost.py`, `scaling_stability`). Fewer is better.

### F.13 Recovery time

How long the system takes to get back under the SLO after a violation starts — on the Comparison page, the "Longest
violation (recovery)" row: the longest run of consecutive violated windows.

### F.14 Comparing two controllers fairly

* **Paired runs:** same scenario, users, spawn rate and duration, both started from settled minimum replicas.
* **Δ (delta) %:** `(candidate − baseline) ÷ baseline × 100`. −7% replica-hours = candidate used 7% less.
* **95% confidence interval (CI):** a range that would contain the true average difference in 95% of repetitions.
  If the CI for replica-hours is entirely below 0 (e.g. −12.3 … −3.2), the saving is statistically supported. If it
  includes 0, we cannot say there is a difference ("on par / inconclusive").
* **Pre-registration:** the rules, runs and verdict table are written down *before* running, so results cannot be
  cherry-picked.

---

## G. Results and limitations

All numbers below come from the reports named. `results/RESULTS.md` collects them with charts.

### G.1 What the experiments establish

1. **The system works end to end on a real cluster, safely.** Discovery, telemetry, GNN+PPO inference, Auto arbitration,
   safety guards, Lease, HPA freeze/restore and cleanup were exercised in hundreds of live runs (289+ recorded) and in a
   dedicated verification set (`results/verification/README.md`), including killing the operator and cutting
   Prometheus mid-run.
2. **Against a fairly tuned native HPA, FlexaScale is on par — not better.**
   * First laptop, v7 policy, clock-controlled pre-registered replication (48 runs, 12 blocks): replica-hours +0.1%
     (CI −0.1 … +0.2), Auto's p95 +0.1% (CI −9.3 … +9.5) (`docs/V7_REPORT.md`).
   * Second laptop, v9 policy, pre-registered evaluation (48 runs + reruns, 46 valid): RL replica-hours +0.3%
     (−0.2 … +0.7), Auto +0.2% → **on par / inconclusive** (`reports/v9/evaluation.md`).
3. **Against default HPA, FlexaScale and Auto use fewer resources** — v9: −7.3% and −7.7% replica-hours with intervals
   below 0, but the p95 check failed, so the verdict is still "on par / inconclusive". The same saving is obtained by
   simply tuning HPA (HPA-default vs HPA-tuned: +10.6% replica-hours for default). On the first laptop, Auto beat default
   HPA on cost by −3.9% over 18 pairs (CI −6.5 … −1.3), but that batch ran under a CPU power profile later found to
   favour whichever arm kept the host busy, so it is reported with that caveat (`docs/POLICY_V6.md`, `docs/V7_REPORT.md`).
4. **In the twin**, on random shop workloads (T2) v9 scored −2.55 vs HPA-tuned −3.06 (better), while on the six live
   scenarios (T1) they were equal (−1.26 vs −1.20). The random workloads were not run live.
5. **The graph input showed no measurable benefit** (ablation: reward Δ inside ±noise on all three test sets).

### G.2 Why HPA can perform as well or better

* At the loads this laptop can generate (25–40 users), most services sit at their minimum of 1 replica under *any*
  good controller; there is little room to be smarter.
* A tuned HPA (higher CPU target, 60 s scale-down window) already removes most waste.
* Some bottlenecks are not CPU (order-service is limited by synchronous database calls inside async handlers,
  `docs/POLICY_V8.md`); adding replicas helps less than expected for *any* controller.
* The policy learned in a simulator; the simulator is good (2% replica-hour error) but not perfect (9% p95 error).

### G.3 Where FlexaScale does well

* Per-service ownership with explicit reasons (Auto) — every decision is explainable from the log.
* Safety: no run left an HPA frozen after the hand-back fix; the watchdog covers crashes.
* Cost vs *default* HPA is lower (G.1.3), mainly by scaling down sooner.

### G.4 Where it struggles

* Spikes on non-CPU bottlenecks; latency rises before CPU does.
* Large random variation between repetitions (the same scenario can differ by tens of percent in p95), so many pairs
  are needed for any verdict.
* **Seen live on 2026-10-31 (40 users, first laptop):** order-service's latency rose about 10× while its CPU per pod
  stayed at 30–50% of its limit (it waits on the database inside its event loop). Both learned policies (v7, v9) read
  mainly CPU relative to the limit, so they held 1 replica, while default HPA — whose 70%-of-request target is only 14%
  of the limit — added replicas. In Auto mode the SLA-risk rule did not take over either, because its CPU threshold
  (400% of request) was calibrated on the other laptop and the shop's policy has no per-service latency SLO. The rule
  itself works (it fired in the controlled `auto_sla` run). Lesson for the viva: *an autoscaler is only as good as the
  signal it reads and the thresholds calibrated for the machine it runs on.*

### G.5 Limitations

Single-node Minikube on a laptop; host noise (battery, power profile, other programs) controlled by explicit host-load
rules; workloads up to 40–75 users; one shop (plus a small bookstore); images built locally (not in a registry);
results on one laptop do not transfer to the other (each was calibrated separately).

---

## H. Complete code walkthrough

Paths are relative to the repository root. "→" means "is called by / passes data to".

### H.1 Entry points

| File | What it does | Key functions |
|---|---|---|
| `fsctl`, `fsctl.cmd`, `src/flexascale/lab/launcher.py` | One-command start/stop/status of the whole lab | `cmd_start(mode)`: checks tools, starts Minikube profile, checks workloads, ingress, port-forwards, Prometheus targets, model, ownership, starts the dashboard; `cmd_stop`: stops managed processes, restores HPAs, verifies no Lease |
| `scripts/run_operator.py` | Starts the FlexaScale operator for one application | `run_policy_operator(args)`: loads the policy file, builds `AppOperator`, handles signals (SIGTERM/SIGINT/SIGBREAK → graceful hand-back), runs the loop |
| `src/flexascale/lab/server.py` | The dashboard's HTTP API (FastAPI, 127.0.0.1 only) | `create_lab_app()`: `/api/lab/overview`, `/apps/{app}/live`, `/experiments` (start/stop/list/get), `/compare`, `/benchmark`, `/models` |

### H.2 The control loop

| File | Role | Important functions (input → output) |
|---|---|---|
| `config/app_policy.py` | Reads and validates a policy YAML (`config/apps/*.yaml`) | `AppPolicy.load(path)` → `AppPolicy`; `validate()` → list of errors; `bounds_for(name)` → (min, max) |
| `discovery/workloads.py` | Finds services and their HPAs | `WorkloadDiscovery.discover()` → `List[WorkloadInfo]` (name, desired, ready, requests, limits, `hpa`) → used by operator and lab |
| `metrics/workload_metrics.py` | Prometheus telemetry per Deployment | `WorkloadMetricsClient.collect(ns, names, cpu_requests, mem_caps)` → `Dict[name, WorkloadMetrics]`; `histogram_quantile(q, buckets)` → seconds |
| `rl/features_v3.py` | The 10 features, same in training and live | `FeatureTracker.update(now, service, cpu_cores, ready, desired, cpu_limit, rps, latency_ms)` → `np.ndarray(10)`; `note_scale()` |
| `rl/policy_runtime.py` | Loads a checkpoint and runs inference | `PolicyRuntime(model_path)`; `predict_graph(features, edges)` → `PolicyOutput(actions, confidences, mode="ppo_graph", deltas…)`; `info()` → model metadata incl. sha256 |
| `rl/graph_policy.py` | The GNN feature extractor and graph policy | `GraphFocalExtractor.forward(obs)` → 128-dim features; `GraphExtractor.embed()` message passing |
| `operator/auto_mode.py` | Auto rules | `AutoArbiter.decide(service, …)` → `AutoDecision(owner, rule, reason, candidate, hpa_recommendation, flexascale_proposal)`; `hpa_recommendation(current, cpu, target, tol, lo, hi)` → int |
| `operator/app_operator.py` | The operator itself | `start()` (Lease), `step()` (one full cycle, returns `StepResult`), `_decide()` (guards + Auto + execution for one service, returns the logged record), `shutdown()` (hand-back) |
| `safety/hpa_manager.py` | All HPA/Deployment writes | `freeze_hpa(name, n)`, `scale_deployment(name, n)`, `ensure_hpa_active(name)`, `restore_all_frozen()`, `restore_unmanaged_replicas()` |
| `safety/lease.py` | Kubernetes Lease (one controller per app) | `ControllerLease.acquire()`, `renew()`, `release()`, `status()` |
| `safety/lock.py` | Per-service ownership bookkeeping | `ScalingLockManager.acquire_rl_lock()`, `release_rl_lock()`, `get_control_mode()` |
| `k8s/kube.py` | Thin `kubectl` wrapper | `get_json`, `list_items`, `scale`, `patch` |

**How they connect:** `run_operator.py` → `AppOperator.step()` → `WorkloadDiscovery.discover()` →
`WorkloadMetricsClient.collect()` → `FeatureTracker.update()` → `PolicyRuntime.predict_graph()` → for each service
`_decide()` → `AutoArbiter.decide()` (Auto only) → guards → `HPAManager.freeze_hpa()` + `scale_deployment()` →
`_log()` writes `decisions.jsonl`.

### H.3 The lab (experiments) and dashboard

| File | Role | Important functions |
|---|---|---|
| `lab/experiments.py` | Runs one experiment end to end | `Lab.start(ExperimentRequest)` (refuses a second run); `Experiment._prepare()` (reset data, minimum replicas, start operator), `_start_workload()` (Locust), `_sample()` (every 5 s: replicas, metrics, Locust window, operator decisions → events), `_check_operator()` (watchdog), `_teardown()` (stop, restore, verify), `_finalize()` (summary), `_write_files()`; `Lab.live(app)` (the dashboard's live view), `Lab.compare(a, b)` |
| `lab/benchmark.py` | Pairs runs and computes verdicts | `benchmark(runs, compare, app, reference)` → per-model pooled Δ with CIs and verdict; `model_tag(run)` |
| `lab/processes.py` | Safe process management (never kills by port) | `ProcessManager.start/stop/is_running` |
| `evaluation/cost.py` | Replica-hours, cost, stability | `summarize_resources(samples, cost)` → `ResourceSummary`; `scaling_stability(series)` |
| `dashboard/src/App.tsx` | Layout, navigation, polling | — |
| `dashboard/src/pages/*.tsx` | Overview, LiveLab, AutoPage, Compare, Experiments, Models, TopologyPage | — |
| `dashboard/src/timeline/ScalingTimeline.tsx`, `data.ts`, `feeds.ts` | The live scaling visualisation; data model; incremental polling (`samples_from`) | `feedOfRun()`, `useActiveExperiment()` |

### H.4 Learning and simulation

| File | Role |
|---|---|
| `data/build_dataset.py`, `data/preprocessing.py`, `data/schema.py` | Alibaba trace → processed CSV with a fixed schema |
| `simulator/flexascale_env.py`, `dependency_env.py`, `control_env.py` | v1–v6 Gymnasium environments (Alibaba-driven) |
| `simulator/twin.py`, `twin_env.py`, `twin_control.py`, `twin_workloads.py` | v7/v9 application twin, its Gym env, the operator/HPA loops in simulation, random workloads/apps |
| `scripts/fit_twin.py` | Fits the twin to live runs |
| `scripts/train_v7.py` | Trains v7/v9 runs (warm start + PPO); `--device cuda` on the GPU laptop |
| `scripts/promote_v9.py`, `scripts/v9_gate.py` | Model card, gate check, policy files |
| `rl/imitation_v7.py` | Behaviour-cloning warm start |

### H.5 Tests

`tests/` has 370+ tests (`pytest`). Examples: `test_auto_mode.py` (every Auto rule and hysteresis),
`test_operator.py` / `test_agnostic_operator.py` (guards, Lease loss, budget), `test_safety.py` (freeze/restore),
`test_workload_metrics.py` (the three telemetry pitfalls, p90, capped percentiles), `test_lab.py` (process safety, API,
watchdog), `test_helm_chart.py` (chart renders and the hand-back hook).

---

## I. Final presentation explanation

### I.1 A 3-minute talk you can give

> "Modern applications are built from many small services. Kubernetes runs them, and its built-in Horizontal Pod
> Autoscaler adds or removes copies of each service by looking at that service's CPU alone. That ignores how services
> depend on each other and treats every service with one rule.
>
> FlexaScale is an autoscaling framework that looks at the whole application. Every ten seconds it discovers the
> services, reads CPU, memory, request rate and latency from Prometheus, turns them into ten unit-free features per
> service, and places them on the application's call graph. A graph neural network passes information along the call
> graph, and a policy trained with PPO reinforcement learning proposes a replica change for each service.
>
> Every proposal goes through a safety layer: replica bounds, a total budget, cooldowns, readiness checks and blocks on
> scale-down under pressure. Only then does FlexaScale scale, and only after freezing that service's native HPA and while
> holding a Kubernetes Lease, so two controllers can never fight over one service. If telemetry disappears, the
> operator crashes, or the lease is lost, everything returns to native HPA.
>
> We also built Auto mode, which decides per service whether FlexaScale or native HPA should be in charge, with
> explainable rules: health, confidence, SLA risk, then efficiency.
>
> We trained the policy in a simulator fitted to our own shop, and evaluated it on a 16-service e-commerce application
> with pre-registered experiments. The honest result: FlexaScale works end to end and safely, uses 7–8% fewer
> replica-hours than default HPA, and performs on par with a carefully tuned HPA — it does not beat it. The project's
> value is a safe, explainable, application-agnostic RL autoscaling system and a rigorous method for evaluating one."

### I.2 Likely viva questions, with short answers

* **Why reinforcement learning and not a formula?** Scaling is a sequence of decisions with delayed effects (pods take
  10–15 s to start, metrics lag a minute). RL optimises the long-term outcome, not just the next step.
* **Why a GNN?** Load propagates along the call graph; a GNN lets each decision use neighbours' state. (Our ablation
  did not show a measurable gain on this shop — we report that.)
* **Why PPO?** Stable on-policy algorithm, works with discrete actions, standard in Stable-Baselines3.
* **What is in the state?** Ten unit-free numbers per service (B.6) plus the graph.
* **What is the action?** −1, 0, +1, +2, +3 replicas per service.
* **What is the reward?** Minus (extra replicas + 6 × latency inflation + 10 × SLO-violation share + 5 × failure % +
  0.25 × changes) × 0.1.
* **How do you stop FlexaScale and HPA fighting?** Lease per application + freeze the HPA (min = max) before scaling,
  restore the original bounds from annotations on hand-back.
* **What happens if Prometheus dies?** Telemetry becomes unavailable → every service goes to HPA in that step; shown in
  the verification run `auto_outage`.
* **What if the operator crashes?** Graceful exits hand back themselves; a hard kill is caught by the lab watchdog,
  which restores all HPAs (`auto_crash` run). In-cluster, Kubernetes restarts the pod and the Helm hook hands back on
  upgrade/rollback/uninstall.
* **Did you beat HPA?** Not a tuned HPA. On par in two pre-registered evaluations on two laptops. Against default HPA
  we use fewer replica-hours, but a tuned HPA achieves the same without a model.
* **Why should we believe your measurements?** Pre-registered rules, paired runs from a settled start, host-load checks
  (battery, CPU outside Kubernetes), invalid runs kept separately with reasons (`reports/experiments_invalid/`).
* **What is p95?** 95% of requests were faster than this time.
* **What is a replica-hour?** One replica running for one hour; our cost measure.
* **Is the dataset real?** Yes, the Alibaba 2021 microservice trace for v1–v6; v7/v9 train on a twin fitted to our own
  live measurements.
* **Can it run on another application?** Yes: discovery is label-based and a 5-service bookstore runs with the same
  operator and Helm chart (limit: 20 services per model).

---

## Glossary

| Term | Simple meaning |
|---|---|
| Ablation | Removing one part (e.g. the graph) to see if it mattered |
| Agent | The learner/decision-maker in RL |
| Annotation | A note (key/value) stored on a Kubernetes object |
| cAdvisor | The kubelet component that measures container CPU/memory |
| Checkpoint | Saved model weights |
| CI (confidence interval) | Range for the true average difference |
| Cooldown | Waiting time after a scaling action |
| Deployment | "Keep N copies of this program running" |
| Desired / ready replicas | Asked-for copies / copies actually serving |
| Embedding | A list of numbers representing something (a service) inside a neural network |
| Freeze (HPA) | Set min = max so the HPA cannot move replicas |
| GNN | Neural network that passes messages along graph edges |
| Helm | Package manager for Kubernetes (installs charts) |
| HPA | Kubernetes' built-in CPU-based autoscaler |
| Hysteresis | Requiring a condition to hold for a while before switching, to avoid flapping |
| Inference | Using a trained model to make decisions |
| Lease | Kubernetes lock object with an owner and an expiry |
| Locust | Load generator that simulates users |
| Minikube | Single-machine Kubernetes |
| Namespace | A named group of Kubernetes objects |
| Observe / shadow mode | Compute and log decisions, change nothing |
| Operator | A program that manages Kubernetes resources automatically |
| p50/p90/p95/p99 | Latency percentiles |
| Pod | One running copy of a program |
| Policy | The decision rule (the neural network) |
| PPO | The RL algorithm used to train the policy |
| Pre-registration | Writing the rules before running the experiments |
| PromQL | Prometheus' query language |
| Replica-hours | Replicas × hours; resource usage |
| Reward | Score the simulator gives for a decision |
| SLO / SLA | Performance target / promise (p95 ≤ 1000 ms here) |
| Twin | Simulator fitted to the real application |
| Watchdog | A checker that reacts when a process dies or hangs |
