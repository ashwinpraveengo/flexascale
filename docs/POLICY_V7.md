# FlexaScale Policy v7: a fair HPA baseline and a policy trained for the cluster's real cost structure

Sections 1–3 were written on 2026-10-26 between 22:30 and 23:00 IST. That was before any v7 code, training, HPA calibration run or v7 live run. They are not edited after results are seen. Any correction is added as a dated note and never replaces the original text.

## 1. Diagnosis: why v4–v6 do not beat native HPA

The evidence comes from the code, the model cards and the 61 completed runs of the 16-service shop on 2026-10-25/26 in `reports/experiments/`. The analysis scripts are listed in §5.

### 1.1 Measured behaviour of the shop (25 users, 300 s)

| Fact | Evidence |
| :--- | :--- |
| Every shop pod requests 100m CPU and may burst to a **500m limit** (5× the request). | `kubectl get deploy` (all 16 HPA'd services) |
| The application is lightly loaded. Mean CPU is 13% of the request. Only 7 of 16 services ever leave 1 replica: order, catalog, api-gateway, cart, inventory, payment, user. | per-service telemetry, all controllers |
| Native HPA (70% of request = 70m per pod) scales **order-service to 9–10 replicas** while the whole service uses at most 0.87 cores, i.e. less than 2 pods' limits. | max replicas 9 (HPA-default), 8 (60 s window) |
| Only **user-service** is clearly CPU-bound. Bcrypt password hashing at login makes its mean latency go from 1.1 s to 2.2, 7.2 and 13.0 s as its CPU per replica rises from 0–0.05 to 0.05–0.10, 0.10–0.15 and 0.15–0.25 cores. Catalog (7–11 ms), inventory, cart and payment are flat. Order-service (170–250 ms) is mostly waiting on its downstream calls. The gateway doubles above 0.10 cores per replica. | `latency_knee.py` (§5) |
| Replica-hours vary 0.4–3.7% between repeats (CV). p95 varies 5–38% and mean latency 3–23%, highest in checkout_heavy and traffic_drop. | 30 HPA-default runs |
| Of the ~17.5–19.7 replicas running on average, 16 are the fixed minimum (one per service). A saving of a few percent is a large share of the part a controller can change. | run summaries |

**Implication.** A single CPU target relative to the request gives replicas to services whose latency does not depend on CPU (order-service). It cannot also protect the one service whose latency does (user-service). Per-service decisions that take latency into account are where a learned controller could do something HPA's single target cannot. Whether one does is the question this document tests.

### 1.2 The twelve questions

| # | Question | Finding |
| :--- | :--- | :--- |
| 1 | Why does the policy over-provision? | v5's live over-provisioning (+8.0% replica-hours) was measured on the **7-service** shop (runs 2026-10-25 01:09–13:34). RL-only was **never measured on the 16-service shop**. The root cause is the training objective (row 2): it makes HPA's rule the optimum. v5 was initialised by imitating an HPA-like rule. In v6, PPO fine-tuning made every run worse than its imitation warm start (POLICY_V6 §4.1). In Auto on 16 services, when FlexaScale owns a service above its minimum, v5 holds 73% of the time, scales down 23% and scales up 4% (682 decisions). |
| 2 | Does the reward penalise unnecessary replicas enough? | The reward per service is `slo + 0.3·efficiency + 0.1·stability + 1.0·cost`, with `efficiency = −\|cpu − 70\|/100`. That term **rewards running at HPA's 70%-of-request target** and penalises running hotter as much as running colder. The simulator's SLO is "slack × latency when every service runs at the 70% target". So compliance is defined by HPA's operating point, and the best policy is HPA's ratio rule. |
| 3 | Does it trade cost against latency appropriately? | There is no stated exchange rate. Unit-free SLO ratios, CPU deviation and replica fractions are added with hand weights. Nothing says how many replica-hours one second of SLO violation is worth. |
| 4 | Are observations normalised consistently between training and live? | The **form** is identical: `v2_features` is used by both. The **meaning** is not. CPU is CPU/request, clipped to 1.0. In the simulator 1.0 is saturation, because capacity per replica equals the request and latency diverges as utilisation approaches 1. Live, a pod can use 5× its request: CPU reached 337% of request, and 2.4% of live Auto decisions had the CPU input silently capped at 1.0. The cap happens inside `v2_features`, before `PolicyRuntime`, so the decision log's `clipped` field never shows it. The same input means "saturated" in training and "14–100% of real capacity" live. |
| 5 | Are the state vector, graph, action mapping and bounds correct? | The action mapping and replica bounds are correct (tests). The graph semantics are wrong for this app. The model was trained on "slot i calls slot i+1", a chain. Live windows are breadth-first neighbourhoods of a 25-edge call graph, truncated to 4 services. api-gateway has 9 callees but its window shows 3, and siblings are presented as if they called each other. |
| 6 | Is the GNN trained on a synthetic 4-node chain but used on another topology? | Yes. Model card: `graph: {type: chain, nodes: 4}`. Live: 16 services, 25 edges. |
| 7 | Does it generalise to the real application and its dependencies? | There is no evidence that it does. v6's neighbour ablation changed reward by −0.009 ± 0.013 (no measurable effect). The policies never saw the shop's services, call graph or latency behaviour, and the simulator's latency model contradicts §1.1: it has no burst headroom and no CPU-bound service. |
| 8 | Are actions too aggressive, frequent or slow to reverse? | v5 moves ±1 replica per decision, with a 30 s scale-up and 60 s scale-down cooldown, so going from 1 to 5 replicas takes at least 2 minutes. Native HPA jumps to `ceil(n·cpu/target)` in one sync. (v6 had −2…+3 but lost in simulation.) |
| 9 | Do the safety constraints, cooldowns and bounds cause unexpected behaviour? | The guards (no scale-down at ≥85% CPU of request or above SLO, 60 s scale-down cooldown, readiness) decide when FlexaScale may scale down. The 48-replica budget applies only to FlexaScale; HPA's peak total (~34) never reaches it, so it did not bind. |
| 10 | Are live metrics stale, mis-aggregated or missing? | There were no stale samples in the 8,928 live Auto decisions. Latency was missing in 9% of them (idle services, no requests in the 1-minute window). Both controllers see CPU about a minute late: FlexaScale uses `rate[1m]` with a 30 s cAdvisor scrape, HPA uses metrics-server with `--metric-resolution=60s`. The single 250 ms mean-latency SLO for every service is wrong for user-service, whose mean latency is 1.1 s even at low CPU (bcrypt). Its latency/SLO input is saturated whatever its replica count. |
| 11 | Is the result caused by the learned policy, the Auto rules or the safety layer? | Auto's −3.9% vs HPA-default comes from FlexaScale scale-downs (56, against 0 for HPA-default). HPA-default cannot scale down inside a 300 s run. The policy's proposal is one input; the guards and rules decide the timing (sla_risk hand-overs 244, low-confidence hand-overs 319). A native HPA with a 60 s window gets −1.4%, and Auto − tuned is −2.5 points [−5.4 … +0.3]. **The evidence does not attribute the saving to PPO.** |
| 12 | Are benchmark differences caused by warm-up, initial replicas, host noise or unequal HPA settings? | Initial replicas and data are equal (comparable start). Host noise has a written exclusion criterion (POLICY_V6 §5.2). HPA-default and the 60 s variant differ only in the window. The remaining confounds are: (a) light load, so replica-hours are dominated by the 16 minimum replicas; (b) 300 s runs against HPA's 300 s default window; (c) RL-only measured on an earlier version of the app; (d) noisy p95 (CV up to 38%). |

## 2. Fair baselines

* **HPA-default**: the deployed configuration. CPU target 70% of request, 1–10 replicas, default behaviour (300 s scale-down stabilisation). Lab controller `hpa`.
* **HPA-tuned**: native HPA with the same 1–10 bounds, a 60 s scale-down stabilisation window (the rule fixed in POLICY_V6 §5.2 before any tuned run), and a single CPU target chosen by the calibration below. Lab controller `hpa_tuned`.

### 2.1 HPA-tuned calibration (fixed before any calibration run)

* **Workload** `calibration_steady`: Browsing 5 : Shopper 5, 25 users, spawn 5/s, constant for 300 s. It is used only for calibration and is not one of the six evaluation scenarios. It is steady because steady scenarios repeat well (p95 CV ≈ 5%, mean latency CV ≈ 3%), so a 10% margin is above run-to-run noise.
* **Grid**: CPU target {70, 150, 250, 350}% of request, i.e. 14, 30, 50 and 70% of the 500m limit. Window 60 s for every value. Everything else stays at the Kubernetes default.
* **Runs**: 2 per value (8 runs), in an order shuffled with `random.Random(7)` and recorded. Comparable start and the same validity rules as the evaluation (§3.4).
* **Rule**: HPA-tuned's target is the highest grid value T for which T *and every lower value* meet all of these, on the mean of their two runs:
  * p95 ≤ 1.10 × p95 at 70%;
  * mean latency ≤ 1.10 × mean latency at 70%;
  * failure rate ≤ failure rate at 70% + 0.10 pp.

  If no value above 70% qualifies, HPA-tuned uses 70% with the 60 s window. All eight results are reported, whichever value is chosen.
* **Why one target**: one target for every service is how the chart and most clusters configure HPA. Separate hand-calibrated targets per service would be a different baseline (expert manual tuning). It is listed as a limitation: such a baseline might close any gap FlexaScale shows.

## 3. Pre-registered live evaluation

### 3.1 Setup

The 16-service shop and the six Locust scenarios (steady_browsing, checkout_heavy, payment_degradation, flash_sale, gradual_ramp, traffic_drop). 25 users, spawn 5/s, 300 s. Comparable start: data reset, every service at its minimum, start ≥ 330 s after the previous load. HPA arms run FlexaScale in shadow (observe-only) mode, as before, so the host runs the same processes in every arm.

### 3.2 Arms

| Arm | Lab controller | What scales |
| :--- | :--- | :--- |
| HPA-default | `hpa` | native HPA, deployed settings |
| HPA-tuned | `hpa_tuned` | native HPA, 60 s window, calibrated target (§2.1) |
| FlexaScale-RL | `flexascale` | the v7 policy alone, under the operator's safety layer (no Auto rules) |
| FlexaScale-Auto | `auto` | Auto rules choosing per service between v7 and HPA-tuned |
| FlexaScale-heuristic (attribution) | `flexascale` with the rule in place of the model | the same operator, signals and safety layer, with a hand-written rule instead of the learned policy (defined in §4 before the batch) |

The model in both FlexaScale arms is the checkpoint the simulation protocol in §4 selects, whether or not it beats HPA-tuned in simulation. The heuristic arm exists to separate the learned policy's contribution from that of the operator and its rules. It may be dropped *before* the batch starts if time does not allow, but never after any of its runs.

### 3.3 Design and statistics

* 12 blocks: 6 scenarios × 2 repeats. Each block runs every arm back to back, in an order shuffled with `random.Random(2610 + block)` and recorded. Repeat 1 covers the scenarios in the order above, then repeat 2.
* Pairing is **within block**: Δ = candidate − reference. The primary reference is **HPA-tuned**; HPA-default is the secondary reference.
* Per run: replica-hours (primary), estimated cost, p50/p95/p99, mean latency, failure rate, throughput, end-to-end SLO-violation seconds (Locust p95 > 1000 ms in a 10 s window), per-service SLO-violation seconds, average and peak replicas, CPU utilisation, scaling events and oscillations. Recovery time after a load decrease is descriptive: the time from the phase change that lowers users (flash_sale, traffic_drop) until total desired replicas are within 1 of the run's minimum total.
* For each metric: mean paired Δ with a 95% t-interval (df = 11), Cohen's d_z, and per-scenario sign agreement across repeats.

### 3.4 Invalid runs (never decided on outcomes)

A run is invalid if it:
* was host-affected (on battery at any point in its load window, or more than 2.0 cores of CPU outside Kubernetes on average; POLICY_V6 §5.2);
* did not complete at least 95% of its duration;
* did not start settled; or
* failed because the cluster or API was unhealthy.

Invalid runs are moved to `reports/experiments_invalid/` with the reason. The arm is rerun once at the end of the batch, inside its block's pairing. A block with a run still invalid after its rerun is reported as missing for that arm's comparisons.

### 3.5 Verdict, for each candidate against each reference

| Verdict | All of |
| :--- | :--- |
| **Beats on cost** | (C1) replica-hours interval < 0; (C2) p95 interval not entirely > 0 and mean Δ ≤ +10%; (C3) failure-rate interval not entirely > 0 and mean Δ ≤ +0.10 pp; (C4) throughput mean Δ ≥ −2%; (C5) end-to-end SLO-violation mean Δ ≤ +5 s per run; (C6) mean oscillations Δ ≤ +5 per run; (C7) replica-hours mean Δ < 0 in at least 4 of the 6 scenarios |
| **Beats on performance** | p95 interval < 0 or failure-rate interval < 0; replica-hours interval not entirely > 0 and mean Δ ≤ +2%; C3–C6 |
| **Worse** | the replica-hours, p95 or failure-rate interval lies entirely > 0, without one of the two gains above |
| **On par / inconclusive** | otherwise |

The project states that **FlexaScale beats a fair native HPA only if FlexaScale-RL or FlexaScale-Auto beats HPA-tuned by this table.** Auto's replica changes and saved replica-hours are attributed by owner (FlexaScale or HPA) and by the rule that chose the owner. No other metric, subset of scenarios or exclusion is used for a verdict.

## 4. v7 policy: design, training and simulation results

*Written as the work proceeds; see §5 for the running record.*

## 5. Running record

| Time (IST) | Step |
| :--- | :--- |
| 2026-10-26 22:30 | Diagnosis (§1) from code, model cards and the 61 runs of the 16-service shop. Scripts: `scripts/analysis/svc_stats.py`, `scripts/analysis/latency_knee.py`. |
| 2026-10-26 23:00 | §2–§3 fixed before any calibration or v7 run. |
