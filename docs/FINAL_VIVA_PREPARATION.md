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
Live: from the application policy's `topology` (the shopping app lists its 25 caller→callee edges), otherwise inferred from observed service-to-service traffic metrics (`gateway_forward_total`, Istio, or client/server labels) with an exponential moving average and decay (`state/graph_inference.py`). With neither, services are ordered by name and the windows carry no dependency information. That is documented as degraded mode.

**What is the state vector?**
Per service: `[CPU % of request, memory % of limit, replicas, request rate (req/s), mean latency (ms)]`, the same units in training and live (`metrics/workload_metrics.py`). The model takes 4 services = 20 floats, clipped to training bounds. Missing metrics are flagged and set to 0, never estimated. Missing or stale CPU means no action.

**What are the actions?**
Per service: scale down by 1, hold, scale up by 1. The safety layer turns that into a target replica count within per-service bounds (`operator/app_operator.py::_decide`).

**How is the reward calculated?**
Per service, averaged: `1.0·SLO + 0.3·efficiency + 0.1·stability + w·cost`, where SLO = +1 if latency ≤ 100 ms else −(latency/100 − 1) (floor −10), efficiency = −|CPU − 70|/100, stability = −|Δreplicas|, cost = −replicas/max. The original reward had w = 0. We added the cost term (w = 0.5 for v3) because the stated goal includes cost, then reported that it did not change the over-provisioning. v4 and the deployed v5 use the revised reward of the dependency-aware simulator (bounded SLO penalty −3, cost weight 1.0; `docs/POLICY_V4.md` §3).

**How was the Alibaba trace used?**
MSResource_0 and MSRTQps_0 (cluster-trace-microservices-v2021, first 30 minutes) were aggregated per service per minute: CPU and memory from instance usage, replicas = distinct instances, request rate = providerRPC_MCR, latency = providerRPC_RT. The result is 1,213 services × 30 timestamps with a temporal 70/15/15 split and no overlap. We found and fixed a unit defect (fractions vs percent). The simulator replays this demand, rescaled to the 1–10 replica range, with random service subsets per episode (`src/flexascale/data/build_dataset.py`, `simulator/flexascale_env.py`, `reports/data_quality_report.md`).

**Difference between simulation and live telemetry?**
Simulation: trace demand, instant replicas, modelled latency (M/M/1-style congestion), chain graph. Live: Prometheus cAdvisor CPU against the pod's request, real request histograms, pods that take seconds to become ready, real topology. The observation units were aligned on purpose. Sim-to-real transfer is evidenced only by the live runs.

**How is controller ownership enforced?**
Two mechanisms (`safety/lease.py`, `safety/hpa_manager.py`):
1. A Kubernetes `Lease` per application. Only one FlexaScale instance can be live, using optimistic concurrency through resourceVersion. Losing the lease sends every service back to HPA and switches to observe mode.
2. Per Deployment: before FlexaScale scales a service, it freezes that service's HPA at `min = max = target`, with the original bounds stored as annotations on the HPA. The HPA cannot fight a value it is pinned to. Handing back restores the original bounds. This was verified live, and in tests the freeze always happens before the scale.

**How is fallback handled?**
Confidence below 0.60 (hysteresis; 0.70 is needed to take over), missing or stale telemetry, step exceptions, lease loss, SIGTERM or uninstall all restore HPA ownership. For Helm upgrade, rollback and uninstall the chart runs a hook that scales the operator to 0 first: the in-cluster test showed that otherwise Helm removes the operator's write permission at the same moment as it stops the pod, and the HPAs stayed frozen (found and fixed on 2026-10-26, chart 0.4.1). The lab's teardown and `stop_review.sh` restore and *verify* it (no frozen HPA, no live lease).

**How is application independence demonstrated?**
No application names in the core. Everything app-specific is in `config/apps/*.yaml`. The same operator and model ran on a second, different application, the synthetic 5-service bookstore with different names, sizes and HPA names and two services without an HPA. Unit tests cover 1–9 services. The shopping app is just an example workload.

**How is cloud cost estimated?**
Ready replicas × *requested* CPU/memory are integrated over the run into allocated vCPU-hours and GiB-hours. With configured prices that gives an estimated cost; without them, a unitless proxy (vCPU-h + 0.125 × GiB-h). Observed usage (cAdvisor) is reported separately as allocation efficiency. Savings are shown only between comparable complete runs, and never presented as a bill (`evaluation/cost.py`).

**What does the HPA comparison actually prove?**
It shows the full system works end to end on a real cluster, safely, under identical scenarios and comparable starts. On the outcome itself: the first trained policy (v3) was clearly worse. It used 58–98% more replica-hours than HPA and was no better on latency, because it had collapsed to "always scale up" already in simulation. The diagnosed causes were fixed in v4 (`docs/POLICY_V4.md`). Over six live scenarios, v4 was roughly on par with HPA in cost (+6% replica-hours on average, range −11% to +22%), with mixed latency and failure results. For example, under payment degradation p95 was −49% but failures were +10 pp. One run per arm on single-node Minikube, so none of these differences is statistically established. In simulation v4 still uses 61% more replicas than an HPA-like rule, for 3 points fewer SLO violations. The deployed v5 (`docs/POLICY_V5.md`) starts by imitating the HPA-like rule and then fine-tunes with PPO. In simulation it beats that rule (+0.064 ± 0.031 reward per step, 3.4 points fewer SLO violations, paired test episodes), but not a better-tuned threshold rule. Live, over six scenarios × two repeats, it used +8% replica-hours with p95 +6.5% and failures +0.5 pp. It was better on traffic drop and worse on a gradual ramp in both repeats, and most other differences flipped sign between repeats. So v5 beats the HPA-like rule in simulation and is close to native HPA live, but **does not beat native HPA on the cluster**.

**What are the limitations?**
The policy does not beat native HPA live. v5 beats the HPA-like rule in simulation, but not a tuned threshold rule, and the gain did not carry over to the cluster. The dependency-graph input has only a borderline effect (ablation +0.016 ± 0.015 reward). The GNN was trained on a synthetic chain, not the real call graph. The input is fixed at 4 services (neighbourhood windows for other sizes were not trained for). The trace is short (30 min). Few seeds per configuration. Confidence is uncalibrated. Handing back to HPA can cause churn. Live evidence is two runs per arm for v5 (one for v3/v4) on single-node Minikube. The earlier Phase-7 benchmark was produced by an untrained head and is withdrawn.

**What is Auto mode, and why add it after the policy lost?**
Three learned policies (v4, v5, v6) did not beat native HPA. Auto mode keeps what *did* work (exclusive ownership, safe hand-back, full logging) and decides per service and per step who scales it, with four ordered rules (`operator/auto_mode.py`): (1) controller health: no model, stale CPU or no Lease → HPA; (2) policy confidence below 0.70 to take over, 0.60 to keep → HPA; (3) SLA risk: latency above the SLO or CPU ≥ 85% of request, and HPA would run more replicas → HPA ("capacity first"); (4) otherwise FlexaScale. Hand-backs are immediate; take-overs need 2 consecutive steps. Every decision stores the rule, its inputs and a one-line reason, and the dashboard shows them. Live, over 18 pairs on the 16-service shop, Auto used **3.9% fewer replica-hours than default native HPA (95% CI −6.5 … −1.3)**, with p95 +2.8% (CI −8.0 … +13.6, no measurable change) and failures −0.07 pp. Under the rule fixed in advance (`docs/POLICY_V6.md` §3.1) that is "beats HPA on cost". Say clearly where it comes from: default HPA never scales down within a 300 s run (its stabilisation window is 300 s), and Auto lets FlexaScale remove replicas while the SLA-risk rule hands stressed services back to HPA. It is a modest effect, weaker in repeat 3. A native HPA with a 60 s scale-down window saves less (−1.4%, 12 pairs), and the indirect comparison does not show Auto saving more than it (−2.5 points, CI −5.4 … +0.3).

**Why 16 services?**
Medium-sized production shops run 15–20 services. Seven was too small to show cross-service effects. The shop now has search, recommendations, reviews, pricing, promotions, shipping, fraud, notification and wishlist, and checkout calls shipping and fraud (required) and notification (best effort). The operator and dashboard needed no code changes, only `config/apps/shopping.yaml`.

**What went wrong in the benchmarks, and how do you know the results are clean?**
Every invalid run is kept with its reason in `reports/experiments_invalid/README.md`: a host suspend, a host shutdown (the battery ran out at 05:09 on 25 October), a clock 5.5 h fast, other jobs on the laptop competing for CPU during three tuned-HPA pairs, and, in the first HPA-vs-Auto batch, an order-history endpoint that loaded all of a user's orders. The two load-test users had 43k orders, so order-service was OOM-killed in almost every run of both arms. That was found from Prometheus restart counts and pod memory (65 → 230+ MiB within minutes at < 1 checkout/s), fixed with a bounded query (order-service 1.3, with a regression test), and the whole batch was rerun. The exclusion rule (a pair counts only if both arms complete on a healthy cluster) was fixed before any result was seen. Host conditions are checked for every run afterwards with a rule that uses no result (`scripts/check_host_load.py`: battery, and CPU used outside Kubernetes). Where a batch's own rule did not cover host conditions, the pairs are kept and a result without them is reported next to it (Auto: −3.9% with all 18 pairs, −4.9% without the 2 battery pairs).

---

## FlexaScale v7: the attempt to beat a *fairly tuned* HPA (`docs/POLICY_V7.md`)

**Why did v4–v6 lose to HPA? Give the root causes, not the symptoms.**
Four causes, each with evidence (§1 of POLICY_V7):
* **The reward made HPA's rule optimal.** Its efficiency term rewarded running at 70% of the CPU request, HPA's own target, and the simulator's SLO was defined at that operating point. The best policy was therefore HPA's rule. v5 even started by imitating it, and in v6 PPO only drifted away from the imitation.
* **The simulator had the wrong capacity.** It treated the 100m CPU *request* as the saturation point. Real pods can burst to their 500m *limit*, and live CPU reached 337% of request, while the policy's CPU input was capped at 1.0.
* **The graph was wrong.** The GNN was trained on a 4-service chain and used on a 16-service call graph in 4-node windows.
* **The baselines were not comparable.** The "+8% worse" RL-only result came from the old 7-service shop. Auto's −3.9% saving comes from scaling down, which default HPA cannot do inside a 300 s run.

**What is a fair HPA baseline, and how did you avoid tuning it to lose?**
HPA-tuned has the 60 s scale-down window fixed earlier, plus one CPU target chosen by a rule written before any calibration run (POLICY_V7 §2.1):
* the candidates are 70, 150, 250 and 350% of request;
* each is run twice on a separate steady workload that is not an evaluation scenario;
* the chosen target is the highest one whose p95 and mean latency stay within 10%, and whose failures stay within +0.1 pp, of the 70% setting.

If the rule picks a high target, HPA-tuned becomes much cheaper and *harder* to beat. That was expected (the simulator predicted 350%) and accepted.

**What is the "twin", and why trust it?**
A simulator fitted to 61 live runs of the shop. Per service it uses CPU cost per request (least squares, R² 0.75–0.95), the real 500m capacity, a serial queue for bcrypt login, closed-loop Locust users, the measured pod start-up delay and both controllers' metric lag. Before any policy was trained it was checked against live native HPA: replica-hours within 3.8% per scenario on average (3.3% for the 60 s window), and p95 within the live spread in 5 of 6 scenarios. The final verdict still comes only from live runs.

**How is the v7 reward different, and why?**
It is stated in replica-equivalents, so each trade-off says how many replicas avoiding it is worth:
* −1 per replica above minimum;
* −6 per 100% of end-to-end p95 above what the same requests would take with ample capacity, capped at 4 per step;
* −10 while the p95 is above the 1 s SLO;
* −5 per 1% failures;
* −0.25 per replica change.

It penalises over-provisioning and under-provisioning symmetrically in their real effect: no CPU target appears anywhere. The cap was added after the first training run collapsed to "scale everything up". Rare overload episodes (inflation up to 620) had dominated the gradient.

**Why is every service an agent?**
With one global reward for 16 simultaneous decisions, a good decision for one service is buried in the noise of the other 15: the policy stayed at "hold" for 200k steps. Each service now gets its own share of the reward: its own replicas and changes, plus the part of the latency penalty its own queueing causes. The shares add up exactly to the global reward. The network parameters are shared, and each decision still sees the whole application through message passing over the real call graph. This is also how the policy is used live: one decision per service.

**How do you separate the learned policy's contribution from the rest of the system?**
* Five live arms: HPA-default, HPA-tuned, FlexaScale-RL (v7 alone), Auto (v7 + rules) and a hand-written rule under the same operator and guards. If the rule matches v7, the learning added nothing.
* In simulation, ablations without the graph and with the old reward structure.
* Auto's replica changes are attributed by owner and rule.

**Did you change any rule after seeing results?**
* The evaluation design and verdict rule (§2–3) and the training protocol (§4.3) were written before the respective runs.
* Both training amendments (penalty cap, per-service credit) are dated, explained and based only on training/validation behaviour. No test or live result existed at the time.
* Invalid runs are defined by host conditions only (battery, CPU outside Kubernetes), never by outcomes.

### Likely follow-ups

* *"Why did the earlier report show FlexaScale better?"* That run used an untrained network head (GNN `node_policy_head`) and a model trained on wrongly scaled data. We found this in the final audit, removed that path and withdrew the result.
* *"Is the 0.93 confidence meaningful?"* It is the policy's probability for its chosen action. It is useful as a gate but not calibrated.
* *"Why imitate HPA first?"* v4 scored below a rule the network can represent exactly, so the problem was optimisation, not capacity. Starting from the rule and taking small PPO steps guarantees a sensible starting point. Every fine-tuned run beat its own warm start on validation.
* *"If a tuned threshold beats v5 in simulation, what is the RL for?"* In this simulator, nothing yet that a tuned rule cannot do. That is reported as the result. The case for RL would need richer signals (latency, dependencies) to matter more than they do here.
* *"Couldn't you just shorten HPA's scale-down window?"* We tested exactly that, with the analysis fixed in advance (`docs/POLICY_V6.md` §5.2). The tuned-HPA reference (`hpa_fast`) sets a 60 s scale-down window on every HPA and restores it automatically. Over 12 pairs in six scenarios, each run directly after a default-HPA run, it used 1.4% fewer replica-hours (95% CI −2.6 … −0.2), with 2.3% lower throughput and slightly more failures; on flash_sale both of its runs had 7–10% lower throughput and a higher p95 (only one of them scaled down at all, so the cause is not clear). Auto saved 3.9%, but the indirect comparison (−2.5 points, CI −5.4 … +0.3) does not show that Auto saves more than the tuned HPA. So the honest answer is: a shorter window gives part of the saving; Auto is at least comparable and had fewer failures, but it is not shown to beat a well-tuned HPA. Also mention that an earlier single pair suggesting "a tuned HPA saves as much (−12.5%)" was withdrawn: during its tuned run other jobs on the laptop used up to 12 extra CPU cores, which the host-load check (`scripts/check_host_load.py`) found without looking at results.
* *"How do you know both arms of a pair ran under the same conditions?"* Three things. Every run starts from the same state: application data reset, every service at its minimum, and a wait until the previous run's HPA scale-down window has passed. The two arms of a pair run back to back. And afterwards `scripts/check_host_load.py` checks each run's load window for battery power (laptop charge history) and for CPU used on the host outside Kubernetes (Prometheus). That check found real problems: the battery period touched 2 of the 18 Auto pairs (the headline keeps them under its fixed rule; without them the result is −4.9% instead of −3.9%), 5 of the 12 v5 pairs (on AC only, v5 is +6.4% instead of +8.0%), and other jobs on the laptop invalidated three tuned-HPA pairs, which were rerun. The point to make: conditions were checked with a criterion that uses no result, and the exclusions are kept with their reasons in `reports/experiments_invalid/README.md`.
* *"How do you know run order did not create the saving?"* HPA always ran first, so we also paired each Auto run with the HPA run *after* it: −5.1% (all 12 pairs negative, `scripts/check_auto_run_order.py`). The HPA arm itself was stable across repeats (for example checkout_heavy 1.907 / 1.910 / 1.913 replica-hours).
* *"Is the cost saving a real bill?"* No. It is an estimate: allocated vCPU and memory × AWS Fargate on-demand list prices. The dashboard labels it as estimated.
* *"What would you do next?"* Find out why the simulator gain did not transfer (pod start-up delay and the shared PostgreSQL are not modelled; v5 is slow on ramps). Train on the real MSCallGraph topology with variable graph sizes and a per-node action head trained by PPO. Run more live repeats so confidence intervals become possible.
