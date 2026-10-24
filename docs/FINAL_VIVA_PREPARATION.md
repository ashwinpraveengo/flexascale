# FlexaScale Viva Preparation

Short, defensible answers grounded in the code (paths given) and in measured results. Where a result is weak or negative, the answer says so. Examiners respect that more than overclaiming.

---

**What problem does FlexaScale solve?**
Native HPA scales each Deployment on its own CPU threshold, reacts after utilisation rises, ignores how load propagates through a call graph, and ignores latency targets and replica cost. FlexaScale makes joint, dependency-aware scaling decisions for a whole microservice application with a learned policy, and runs it safely beside HPA: it can always hand control back, and two controllers never own the same Deployment.

**Why reinforcement learning?**
Scaling is sequential decision-making under delayed effects: a replica added now helps only after it is ready, and over-provisioning costs money for as long as it stays. RL optimises a long-term objective (latency SLO, CPU efficiency, stability, cost) instead of a fixed rule. The honest caveat is that the learned policy is only as good as the reward. Ours learned to over-provision because the SLO term dominates (see Limitations).

**Why PPO?**
Stable on-policy actor-critic with a clipped objective that tolerates noisy rewards, works with multi-discrete actions (one categorical head per service), and its action probabilities give a natural confidence signal for the safety gate. Implemented with Stable-Baselines3 (`rl/ppo_agent.py`, `rl/train.py`).

**Why a GNN?**
Services are nodes and calls are edges. Message passing lets the representation of a service include its neighbours' load, and the same weights apply to every node. We use 2 GCN layers (PyTorch Geometric) inside an SB3 feature extractor (`rl/gnn_encoder.py`). Caveat: training used a fixed 4-node chain of trace services, not the real Alibaba call graph, so the dependency awareness is architectural rather than learned from real call data.

**How is the dependency graph built?**
Live: from the application policy's `topology` (the shopping app lists its 10 caller→callee edges), otherwise inferred from observed service-to-service traffic metrics (`gateway_forward_total`, Istio, or client/server labels) with an exponential moving average and decay (`state/graph_inference.py`). With neither, services are ordered by name and the windows carry no dependency information. That is documented as degraded mode.

**What is the state vector?**
Per service: `[CPU % of request, memory % of limit, replicas, request rate (req/s), mean latency (ms)]`, the same units in training and live (`metrics/workload_metrics.py`). The model takes 4 services = 20 floats, clipped to training bounds. Missing metrics are flagged and set to 0, never estimated. Missing or stale CPU means no action.

**What are the actions?**
Per service: scale down by 1, hold, scale up by 1. The safety layer turns that into a target replica count within per-service bounds (`operator/app_operator.py::_decide`).

**How is the reward calculated?**
Per service, averaged: `1.0·SLO + 0.3·efficiency + 0.1·stability + w·cost`, where SLO = +1 if latency ≤ 100 ms else −(latency/100 − 1) (floor −10), efficiency = −|CPU − 70|/100, stability = −|Δreplicas|, cost = −replicas/max. The original reward had w = 0. We added the cost term (w = 0.5 for the deployed v3 model) because the stated goal includes cost, then reported that it did not change the over-provisioning.

**How was the Alibaba trace used?**
MSResource_0 and MSRTQps_0 (cluster-trace-microservices-v2021, first 30 minutes) were aggregated per service per minute: CPU and memory from instance usage, replicas = distinct instances, request rate = providerRPC_MCR, latency = providerRPC_RT. The result is 1,213 services × 30 timestamps with a temporal 70/15/15 split and no overlap. We found and fixed a unit defect (fractions vs percent). The simulator replays this demand, rescaled to the 1–10 replica range, with random service subsets per episode (`data/build_dataset.py`, `simulator/flexascale_env.py`, `reports/data_quality_report.md`).

**Difference between simulation and live telemetry?**
Simulation: trace demand, instant replicas, modelled latency (M/M/1-style congestion), chain graph. Live: Prometheus cAdvisor CPU against the pod's request, real request histograms, pods that take seconds to become ready, real topology. The observation units were aligned on purpose. Sim-to-real transfer is evidenced only by the live runs.

**How is controller ownership enforced?**
Two mechanisms (`safety/lease.py`, `safety/hpa_manager.py`):
1. A Kubernetes `Lease` per application. Only one FlexaScale instance can be live, using optimistic concurrency through resourceVersion. Losing the lease sends every service back to HPA and switches to observe mode.
2. Per Deployment: before FlexaScale scales a service, it freezes that service's HPA at `min = max = target`, with the original bounds stored as annotations on the HPA. The HPA cannot fight a value it is pinned to. Handing back restores the original bounds. This was verified live, and in tests the freeze always happens before the scale.

**How is fallback handled?**
Confidence below 0.60 (hysteresis; 0.70 is needed to take over), missing or stale telemetry, step exceptions, lease loss, SIGTERM or uninstall all restore HPA ownership. The lab's teardown and `stop_review.sh` restore and *verify* it (no frozen HPA, no live lease).

**How is application independence demonstrated?**
No application names in the core. Everything app-specific is in `config/apps/*.yaml`. The same operator and model ran on a second, different application, the synthetic 5-service bookstore with different names, sizes and HPA names and two services without an HPA. Unit tests cover 1–9 services. The shopping app is just an example workload.

**How is cloud cost estimated?**
Ready replicas × *requested* CPU/memory are integrated over the run into allocated vCPU-hours and GiB-hours. With configured prices that gives an estimated cost; without them, a unitless proxy (vCPU-h + 0.125 × GiB-h). Observed usage (cAdvisor) is reported separately as allocation efficiency. Savings are shown only between comparable complete runs, and never presented as a bill (`evaluation/cost.py`).

**What does the HPA comparison actually prove?**
It shows the full system works end to end on a real cluster, safely, under identical scenarios and comparable starts. On the outcome itself: the first trained policy (v3) was clearly worse. It used 58–98% more replica-hours than HPA and was no better on latency, because it had collapsed to "always scale up" already in simulation. The diagnosed causes were fixed in v4 (`docs/POLICY_V4.md`). Over six live scenarios, v4 was roughly on par with HPA in cost (+6% replica-hours on average, range −11% to +22%), with mixed latency and failure results. For example, under payment degradation p95 was −49% but failures were +10 pp. One run per arm on single-node Minikube, so none of these differences is statistically established. In simulation v4 still uses 61% more replicas than an HPA-like rule, for 3 points fewer SLO violations.

**What are the limitations?**
The policy does not beat native HPA. v4 fixed v3's over-provisioning collapse, but it still uses more replicas than the HPA rule in simulation. The GNN was trained on a synthetic chain, not the real call graph. The input is fixed at 4 services (neighbourhood windows for other sizes were not trained for). The trace is short (30 min). Few seeds per configuration. Confidence is uncalibrated. Handing back to HPA can cause churn. Live evidence is a single run per arm on Minikube. The earlier Phase-7 benchmark was produced by an untrained head and is withdrawn.

---

### Likely follow-ups

* *"Why did the earlier report show FlexaScale better?"* That run used an untrained network head (GNN `node_policy_head`) and a model trained on wrongly scaled data. We found this in the final audit, removed that path and withdrew the result.
* *"Is the 0.93 confidence meaningful?"* It is the policy's probability for its chosen action. It is useful as a gate but not calibrated.
* *"What would you do next?"* Rebalance the reward (bounded SLO penalty against cost) with a validation protocol. Train on the real MSCallGraph topology with variable graph sizes and a per-node action head trained by PPO. Run repeated live trials with confidence intervals.
