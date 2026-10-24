# FlexaScale: Final Project Summary

**RL-based, dependency-aware autoscaling for Kubernetes microservices, with a safety layer that never lets two controllers own the same Deployment.**

Status of every claim below is tracked in `reports/final_readiness_report.md`.

## 1. Problem

Kubernetes' Horizontal Pod Autoscaler (HPA) scales each Deployment independently on a threshold (e.g. 70% of requested CPU). In a microservice application, load on one service propagates to its callees, and threshold rules react only after utilisation has risen. They also ignore latency targets and the cost of the replicas they add. FlexaScale asks whether a learned policy that sees all services and their dependencies together can make better scaling decisions, and how such a policy can run *safely* next to the native autoscaler.

## 2. Contribution

1. **A PPO policy with a GNN dependency encoder** (PyTorch Geometric GCN inside a Stable-Baselines3 feature extractor), trained on a simulator driven by the Alibaba microservices v2021 trace.
2. **A model-agnostic way to apply a fixed-size trained policy to any number of services**: each service is evaluated in a K-node window (itself plus its nearest dependency-graph neighbours) with the same trained weights.
3. **A safety and ownership layer**: confidence gating with hysteresis, HPA fallback, a Kubernetes `Lease` per application (one controller instance), and per-Deployment HPA freezing that records and later restores the HPA's original bounds.
4. **An installable, application-agnostic operator** (Helm chart, application policy file, observation-only default, least-privilege namespaced RBAC).
5. **A live evaluation lab**: a dashboard plus orchestrated, comparable HPA-vs-FlexaScale experiments on a real cluster, with resource and cost accounting that keeps allocation, usage, replica-hours and estimated cost apart.

## 3. Architecture

```
          Prometheus (cAdvisor, kube-state-metrics, app histograms)        Kubernetes API (Deployments, HPAs, Lease)
                         │                                                              │
                         ▼                                                              ▼
   WorkloadMetricsClient (CPU % of request, mem %, rps, latency;      WorkloadDiscovery (namespace, selector, allow/deny,
   missing/stale flagged, never estimated)                             datastore exclusion, HPA via scaleTargetRef)
                         └───────────────────────┬──────────────────────────────────────┘
                                                 ▼
                     AppOperator.step()  ── observation [cpu%, mem%, replicas, rps, latency] per service
                                                 │      dependency edges (policy topology or observed traffic)
                                                 ▼
                     PolicyRuntime (trained PPO+GNN; ppo_direct if N = K, else ppo_neighborhood)
                                                 │      action ∈ {−1, 0, +1} and its probability (confidence)
                                                 ▼
                     Safety: telemetry check · replica bounds · scale-down blocks (CPU/memory/SLO/cooldown/readiness)
                             · scale-up waits for readiness · confidence ≥ 0.70 to take ownership, < 0.60 to hand back
                                                 │
                       observe mode ─────────────┼───────────── live mode (holds Lease flexascale-<app>)
                       (log only)                ▼
                                   freeze HPA (min = max = target, originals in annotations) → scale Deployment
                                                 │
                                   decisions.jsonl (proposed vs applied) → Live Lab timeline (requested vs actual)
```

Code map: `flexascale/config/app_policy.py`, `discovery/workloads.py`, `metrics/workload_metrics.py`, `rl/policy_runtime.py`, `operator/app_operator.py`, `safety/{hpa_manager,lease,lock}.py`, `lab/` (experiments, server, processes), `evaluation/cost.py`, `dashboard/` (React/TypeScript/Vite/Tailwind source of the lab UI).

## 4. Application-agnostic deployment

* Nothing in the core names an application. The shopping app's namespace, exclusions and topology live in `config/apps/shopping.yaml`. A second, different application (`examples/bookstore`: 5 services, different names, CPU sizes and HPA naming, two services without an HPA) runs with the same operator and model through `config/apps/bookstore.yaml`.
* No application code changes. CPU and memory come from cAdvisor and kube-state-metrics. Request rate and latency are used when the app exports the common `http_requests_total` / `http_request_duration_seconds` metrics; otherwise they are marked missing (degraded CPU/memory-only mode).
* Installation: `helm/flexascale` (policy rendered to a ConfigMap; `mode: observe` by default, with read-only RBAC; write verbs only in `live`). See RUNNING.md §U.

## 5. GNN and PPO

* **Observation** (per service, units identical in training and live): CPU % of allocation/request (0–100), memory % (0–100), replicas, total request rate (req/s), mean latency (ms). The trained models take K = 4 services → 20 floats. Values are clipped to the training bounds (replicas 1–10, rate/latency ≤ 10,000).
* **Action** per service: 0 = scale down by 1, 1 = hold, 2 = scale up by 1 (`MultiDiscrete([3]*4)`).
* **Network**: per-node linear projection (5→64), 2 × GCNConv (64) with LayerNorm, readout = global mean pool ⊕ per-node embeddings → MLP → 64-d features, then PPO actor/critic heads (64-64).
* **Graph during training**: a fixed 4-node chain. The Alibaba call-graph files (MSCallGraph) were not used, so the GNN has *not* learned real dependency structure from data. Live, edges come from the application policy (shopping) or from observed service-to-service traffic.
* **Variable service counts**: the PPO action head is fixed at 4. For N ≠ 4, each service is evaluated in its own 4-node neighbourhood window and only that slot's action is used. The encoder's `node_policy_head` is never trained by PPO and is not used (a test sets it to NaN and checks decisions are unchanged).

## 6. Reward

Per service, averaged over services (`simulator/flexascale_env.py`):

```
r = 1.0 · SLO + 0.3 · efficiency + 0.1 · stability + w_cost · cost
SLO        = +1 if latency ≤ 100 ms, else −(latency/100 − 1), floored at −10
efficiency = −|CPU% − 70| / 100
stability  = −|Δreplicas|
cost       = −replicas / max_replicas          (added in this release; w_cost = 0 reproduces the original reward)
```

The original reward had no explicit resource-cost term. Held-out evaluation showed the policy trained on it (v2) nearly always scales up (§10). v3 was trained with `w_cost = 0.5`, the cost term the stated objective implies. The weight was chosen once, not tuned on test data, and v3 shows the same over-provisioning: the SLO penalty (up to −10 per service) still dominates. The deployed **v4** policy addresses the causes rather than the weight: a dependency-aware simulator with attainable per-service SLOs, unit-free inputs, a bounded SLO penalty (−3), cost weight 1.0, and a focal objective that matches live per-service inference (`simulator/dependency_env.py`, `docs/POLICY_V4.md`).

## 7. Alibaba data

* Source: `cluster-trace-microservices-v2021`, first 30-minute shard (MSResource_0, MSRTQps_0), aggregated to 1,213 services × 30 one-minute timestamps (36,355 rows). Temporal split 70/15/15 with zero timestamp overlap (`reports/data_quality_report.md`).
* **Defect fixed**: the processed files stored CPU/memory as fractions while every consumer expected percent. The files were rescaled (with provenance) and the builder was fixed. The original (v1) model had been trained on the fractional data.
* The simulator's `normalized` demand model rescales each service's CPU demand into the 1–10 replica range used live, with an M/M/1-style congestion factor for latency. Random service sampling and random initial replicas give training diversity, because each split is only a few minutes long (validation 4 and test 5 timestamps, so 3–4-step held-out episodes).
* No additional trace data was downloaded (≈2.3 GB per extra shard). Nothing showed more data was the bottleneck.

## 8. Simulation vs live operation

| | Simulation (training/evaluation) | Live (operator) |
| :--- | :--- | :--- |
| Load | Alibaba trace demand, rescaled | Real Locust traffic on Minikube |
| CPU | demand / replicas, percent | cAdvisor cores / requested cores × 100 |
| Latency | trace latency × congestion factor | mean from app histograms (missing if not exported) |
| Replicas | instant | pods take seconds to become ready; scale-up waits for readiness |
| Topology | fixed 4-node chain, random services | policy topology or observed traffic; neighbourhood windows |

Sim-to-real transfer was not validated beyond the live experiments in §10.

## 9. Safety, ownership and fallback

* **Observation-only by default** in the policy files and the Helm chart. Live mode is refused without a loadable trained model or without the application Lease.
* **One controller instance per application**: a `coordination.k8s.io/v1 Lease` acquired and renewed with optimistic concurrency (`kubectl replace` with resourceVersion). Losing it returns every service to HPA and switches to observe.
* **Never two controllers on one Deployment**: before FlexaScale scales a Deployment that has an HPA, it sets the HPA to `min = max = target` and records the original bounds in annotations. Handing back (low confidence, missing telemetry, lease loss, step error, shutdown, SIGTERM, uninstall) restores those original bounds. HPAs are found through `scaleTargetRef`, not by naming convention.
* **Guards**: replica bounds per service; an app-wide replica budget (`max_total_replicas`, added after a live run exhausted the node, §12); no scale-down above 85% CPU, above 90% memory, above the latency SLO, within 60 s of the previous scale-down, or while pods are not ready; no scale-up while pods are still starting; missing/stale CPU telemetry → no action.
* **Hysteresis**: take ownership at confidence ≥ 0.70 (after a 15 s cooldown); hand back below 0.60.
* **Lab cleanup**: every exit path stops Locust and the operator, restores HPAs and verifies "no frozen HPA, no live lease".

## 10. Results

### Simulation, v4 (deployed), 300 paired test-service episodes (`reports/simulation_evaluation_v4.md`)

Dependency-aware simulator, test services disjoint from training and validation:

| Policy | Reward / step | SLO violations | Avg replicas |
| :--- | ---: | ---: | ---: |
| PPO v4 (validation-selected from 8 candidates) | −0.425 ± 0.097 | 37.6% | 4.54 |
| HPA-like rule | −0.288 ± 0.091 | 40.7% | 2.82 |
| PPO v3 (previous) | −0.861 ± 0.086 | 33.5% | 9.54 |

v4 uses 52% fewer replicas than v3, but it is below the HPA rule on reward: 3.0 ± 1.5 points fewer SLO violations for 1.72 ± 0.20 more replicas (paired).

### Simulation, v2/v3, original simulator (200 paired episodes; `reports/simulation_evaluation.md`)

| Policy | Reward (orig.) | Latency-SLO violations | Avg replicas | Scale actions / step |
| :--- | ---: | ---: | ---: | ---: |
| PPO v3 (validation-selected) | −1.41 ± 0.75 | 25.2% | 7.47 | 4.97 |
| PPO v2 (original reward) | −1.35 ± 0.69 | 25.7% | 7.30 | 4.22 |
| HPA-like rule (70% ± 10%) | −1.94 ± 0.73 | 31.2% | 5.25 | 2.85 |
| Legacy v1 model (fraction-unit data) | −5.27 ± 1.06 | 36.5% | 5.99 | 1.25 |

The PPO policies beat the HPA-like rule on reward (paired difference +0.53 ± 0.23 for v3) and violate the latency SLO about 6 percentage points less often, **by provisioning about 40% more replicas and scaling almost every step**. That is a performance-for-cost trade-off, not a free win.

### Live experiments (`reports/live_benchmark_report.md`)

Shop on Minikube, 25 users, 300 s, one run per scenario and controller, comparable starts.

**v4 (deployed), 2026-10-24, six scenarios:**

| Scenario | p95 ms HPA → FlexaScale | Failures % | Replica-hours | Resource-cost proxy |
| :--- | ---: | ---: | ---: | ---: |
| Steady browsing | 1000 → 1500 | 3.30 → 3.32 | 1.19 → 1.24 | +4% |
| Checkout-heavy | 6000 → 6000 | 30.19 → 18.90 | 1.41 → 1.38 | −2% |
| Payment degradation | 4100 → 2100 | 21.85 → 32.15 | 1.10 → 1.21 | +10% |
| Flash-sale spike | 2600 → 1700 | 3.05 → 2.46 | 1.15 → 1.40 | +22% |
| Gradual ramp | 2200 → 3100 | 7.02 → 7.03 | 1.11 → 0.98 | −11% |
| Traffic drop | 5000 → 3900 | 7.41 → 5.80 | 1.48 → 1.69 | +14% |

Averaged over the six pairs: replica-hours +6%, p95 −2.4%, throughput +4.5%, failure rate −0.5 pp. Individual differences are large in both directions, and with one run per arm none of them is established. v4 is roughly on par with HPA in cost and shows no demonstrated latency or reliability benefit. It no longer over-provisions the way v3 did.

**v3 (previous model), 2026-10-23:**

| Scenario | p95 ms HPA → FlexaScale | Throughput req/s | Replica-hours | Resource-cost proxy |
| :--- | ---: | ---: | ---: | ---: |
| Flash-sale spike | 1400 → 2100 | 10.44 → 8.77 | 1.25 → 2.20 | +77% |
| Gradual ramp | 3000 → 3400 | 7.05 → 6.84 | 1.11 → 2.20 | +98% |
| Traffic drop | 1900 → 2100 | 5.50 → 5.44 | 1.19 → 1.88 | +58% |

With v3, FlexaScale **did not outperform native HPA**. It provisioned 58–98% more resources and had equal or worse latency, throughput and failure rates. The safety and ownership machinery worked in every run; the learned policy is the weak component. A single shared PostgreSQL instance and pod start-up cost on a small node are plausible reasons extra replicas did not help (not isolated experimentally).

## 11. Cost methodology

Per run, from 5-second samples: replica-hours; *allocated* vCPU-hours and GiB-hours (ready replicas × requests); *observed* vCPU-hours (cAdvisor); CPU allocation efficiency (observed / allocated); and either an **estimated cost** (only when `cost.cpu_per_vcpu_hour` and `cost.memory_per_gib_hour` are configured) or a unitless **resource-cost proxy** (vCPU-h + 0.125 × GiB-h). Percentages are shown only between comparable, complete runs with a positive baseline. No real cloud bill exists on Minikube and none is claimed.

## 12. Limitations

* The learned policy does not beat native HPA. v4 fixed v3's collapse to scaling up, but it still uses more replicas than the HPA rule in simulation, and its live results are mixed.
* The trained graph is a synthetic chain, not the real Alibaba call graph. The dependency awareness is architectural, not learned from real dependencies.
* The model's input is fixed at 4 services; other sizes use neighbourhood windows, which were not part of training.
* Short trace (30 min). v2/v3 had very short held-out episodes; v4 splits by service with full 30-minute episodes. Few seeds per configuration.
* Live comparisons use one run per scenario and controller on a single-node Minikube, so they are indicative only.
* Confidence is the policy's action probability, not a calibrated uncertainty estimate.
* Handing a service back to HPA can cause churn: the restored HPA immediately applies its own recommendation.
* **Node capacity incident (2026-10-22 23:48)**: at 40 users a FlexaScale run scaled the shop to 45 replicas. The Minikube node is a Docker container limited to 6 GiB, but it advertises the host's ~16 GB as allocatable, so the scheduler admitted pods that did not fit. The node thrashed (42.6% request failures) and the API server stopped for ~3 minutes. Because the HPA-restore calls could not reach the API, seven HPAs stayed frozen. The lab reported this as *not safe*, and `procctl safe-state` restored the original bounds from the HPA annotations once the API recovered. Fixes: the app-wide replica budget, teardown restore retries, settled-start enforcement, and running live comparisons at 25 users.
* The in-cluster Helm installation was verified with a locally built image only (see the readiness report).
