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

### 3.6 Confirmatory flash-sale study (added 2026-10-27 05:15, before any live v7 outcome was analysed; withdrawn at 19:19 before any of its runs, §5)

**Why.** The twin test set T1 (run once, §5 05:05) puts v7's whole advantage over HPA-tuned in one scenario: flash_sale p95 −385 ms at −1.2% replica-hours, and no difference in four scenarios. The 12 blocks of §3 pool all six scenarios, so they are not powered for an effect in one of them. This study tests that one hypothesis on fresh live runs. It is reported whatever it finds, and it does not replace §3: **the §3.5 verdict of the 12-block batch stays the project's primary result.** A positive result here supports only the narrower claim "FlexaScale beats a calibrated native HPA under flash-sale spikes".

* **Hypothesis:** under the flash_sale scenario, FlexaScale-RL (v7) has a lower end-to-end p95 than HPA-tuned at no more replica-hours.
* **Arms:** HPA-tuned (250%, 60 s; `reports/v7/arms.json`), FlexaScale-RL (v7) and FlexaScale-heuristic (the rule, for attribution). Same models, rule, settings, comparable start, validity rules and one rerun per invalid run as §3.1–§3.4.
* **Design:** flash_sale only, 25 users, spawn 5/s, 300 s; 10 blocks, each running the three arms back to back in an order shuffled with `random.Random(2710 + block)`. Block labels `v7s-bNN-<arm>`. It runs after the §3 batch and its reruns.
* **Power:** live flash_sale p95 varied with SD ≈ 80 ms between HPA runs (paired SD ≈ 113 ms). With 10 blocks the 95% t-interval (df = 9) has a half-width of about 80 ms, so an effect of −100 ms or more is likely to give an interval below 0.
* **Verdict (RL against HPA-tuned; the heuristic arm is descriptive):**
  * **beats on performance under flash sales:** p95 interval < 0; replica-hours interval not entirely > 0 and mean Δ ≤ +2%; C3–C6 of §3.5;
  * **beats on cost under flash sales:** replica-hours interval < 0; p95 interval not entirely > 0 and mean Δ ≤ +10%; C3–C6;
  * **worse:** the replica-hours, p95 or failure-rate interval lies entirely > 0, without one of the two gains above;
  * otherwise **on par / inconclusive**.
* **No other metric, scenario or subset is used for this verdict.**

### 3.7 Clock-controlled replication (added 2026-10-27 20:15, before any of its runs)

**Why.** In the 12-block batch the CPU clock differed by arm (§5, 19:19): 1649–1761 MHz in the HPA arms, 1880–2353 MHz in the FlexaScale arms. The §3.5 verdict of that batch therefore cannot be attributed to scaling decisions. This replication repeats the comparison with the clock controlled. **For the project's claim, its verdict replaces the batch's.** The batch's verdict is still reported, together with the confound.

* **Clock control:** power profile `performance` for the whole replication (EPP and governor `performance`; set and checked by `scripts/v7_replicate.sh`). For every run's load window, `reports/host_load_by_run.csv` records the shop's CPU-seconds per Locust request (`app_cpu_ms_per_request`, which shows how fast the application ran) and the node's mean CPU clock (`cpu_mhz`, descriptive: it mostly counts busy cores).
* **Arms:** HPA-tuned (250%, 60 s), FlexaScale-RL (v7), FlexaScale-Auto (v7) and FlexaScale-heuristic (the rule). The models, rule and settings are those of §3.2 (`reports/v7/arms.json`), unchanged. HPA-default, the secondary reference, is dropped for time.
* **Design:** §3.3 with a new order seed: 12 blocks (6 scenarios × 2 repeats), the arms of each block in an order shuffled with `random.Random(2810 + block)`, labels `v7r-bNN-<arm>`. Validity rules and one rerun per invalid run as in §3.4.
* **Verdict:** the §3.5 table, each candidate against HPA-tuned, with one condition added now. **Environment parity:** in the two steady_browsing blocks, where every arm keeps every service at one replica, the candidate's shop CPU-seconds per request must not be more than 10% below HPA-tuned's, or the comparison gets no verdict. A slower candidate environment only makes the test harder. The project states that FlexaScale beats a fair native HPA only if FlexaScale-RL or FlexaScale-Auto beats HPA-tuned here. The heuristic arm attributes the result to the learned policy or to the operator.
* **Setup pilot (19:31–20:12, not counted; runs in `reports/experiments_demo/`):** steady_browsing × {HPA-tuned, RL} × 2 blocks under `performance`. p50 was 8.0 ms in all four runs; shop CPU per request was 14.82–14.91 ms (HPA-tuned) and 15.55–15.71 ms (RL, +5%, slower). Under `balanced` the batch's steady_browsing runs had p50 17–18 vs 15–16 ms and CPU per request 25.7–29.2 vs 23.1–27.3 ms. The node's mean clock still differed by arm (2057–2134 vs 2489–2824 MHz) while the shop ran at the same speed, so it counts busy cores, not the shop's speed. A ±5% clock criterion drafted before the pilot was therefore replaced by the parity rule above, before any replication run.

## 4. v7 policy: design, training and simulation results

### 4.1 Application twin (`src/flexascale/simulator/twin*.py`, fitted by `scripts/fit_twin.py`)

The twin is fitted from the 61 completed runs of the 16-service shop. All controllers are pooled, because the fitted quantities belong to the application, not the controller.
* **CPU demand** per service is `cpu_per_req × rate + idle × replicas`. The least-squares fit has R² 0.75–0.95. For example, order-service costs 16.0 CPU-ms per request, catalog 2.4 and user-service 211.8 (bcrypt).
* **Capacity** per replica is the 500m CPU *limit*; work beyond it queues. user-service is *serial* (one login at a time per replica).
* **Latency** per service is its low-load latency plus processor-sharing delay, plus queue wait, plus the excess latency of its callees.
* **End-to-end latency** uses the Locust request classes (browse, cart, checkout, orders, login). Each class gets its measured share, mean and spread per scenario, and the p95 comes from the mixture.
* **Users** are closed-loop: the load drops when responses slow down.
* **Timing and metric lag** match the cluster: pods are ready after 10 s (15 s with probability 0.3); Prometheus uses `rate[1m]` scraped every 30 s; metrics-server has 60 s resolution.

**Validation against live runs** (`scripts/analysis/validate_twin.py`, 5 seeds per scenario): replica-hours are within 3.8% of live on average for native HPA (default) and 3.3% for the 60 s window. p95 matches within the live run-to-run spread in 5 of 6 scenarios. flash_sale is too high in the twin: 699 ms against 448–670 ms live.

**Headroom at the live evaluation load** (25 users, six scenarios; `scripts/analysis/twin_headroom.py`, before any v7 training):

| Controller (twin) | Replica-h vs HPA-default | p95 (mean of scenarios) | flash_sale p95 |
| :--- | ---: | ---: | ---: |
| HPA-default (70%, 300 s) | 0 | 271 ms | 684 ms |
| HPA 70%, 60 s | −0.4% | 271 ms | 684 ms |
| HPA 150%, 60 s | −13.8% | 378 ms | 1310 ms |
| HPA 350%, 60 s | −16.3% | 467 ms | 1835 ms |
| hold every service at 1 replica | −16.6% | 515 ms | 2119 ms |

At 25 users the replica floor is 16.6% below HPA-default. A native HPA with a higher target reaches −14 to −16%, and the only latency it gives up is in flash_sale. This was written before the v7 live results: **if the calibration (§2.1) selects a high target, HPA-tuned is close to the floor, and no controller can beat it on cost by more than about 1–3%. FlexaScale's remaining room is the flash-sale spike: keeping headroom only where spikes hurt.** The evaluation design in §3 is unchanged.

### 4.2 Policy, observation and reward

* **Observation (version 3, `rl/features_v3.py`)**: 10 unit-free features per service, computed the same way by the twin environment and by the live operator:
  * CPU per replica as a fraction of the *limit*, and its trend;
  * request-rate trend;
  * log₂ latency inflation over the service's own low-load latency;
  * replica fraction and ready fraction;
  * log CPU-ms per request;
  * burstiness (peak/mean rate over 5 minutes);
  * time since the last scale-up and scale-down.
* **Policy (`rl/graph_policy.py`)**: two rounds of message passing over the application's *real* call graph, with separate weights for callees and callers, then one shared head per service. Actions are −1, 0, +1, +2 or +3 replicas. The critic is the mean of the node embeddings. Padded nodes hold, with zero entropy. Every decision-making parameter is trained by PPO.
* **Guards (`twin_control.V7_GUARDS`, the same in live)**:
  * at most +3 replicas per decision and 20 s between scale-ups;
  * one replica down per 30 s;
  * no scale-down while a pod is at ≥ 80% of its limit (400% of request);
  * no single latency SLO.
* **Reward (`simulator/twin_env.py`)**, in replica-equivalents per 10 s decision. Each term states how many replicas avoiding it is worth:
  * −1 per replica above each service's minimum;
  * −6 per 100% of end-to-end p95 above the p95 the same requests would have with ample capacity;
  * −10 while the end-to-end p95 is above the 1000 ms SLO;
  * −5 per 1% of failed requests;
  * −0.25 per replica change.

  The p95 term charges under-provisioning only when it actually slows requests, the replica term charges over-provisioning, and the change term charges churn. The components are logged separately (`info["reward_components"]`).

  **Amendment (2026-10-26 23:30, before any test or live v7 result).** The first training run's validation reward collapsed at 200k steps: replica-hours rose from 1.93 to 9.78 because the policy scaled almost every service to its maximum. On the *training* distribution, holding every service at its minimum gives a per-step p95 inflation that is usually small (median of the per-episode maximum 0.2) but reaches 81 at the 90th percentile and 620 at worst. A few overload episodes, some of them impossible to serve even at 10 replicas, dominated the gradient. Two fixes:
  * the inflation is now capped at 4 per step (`p95_inflation_cap`), as v4–v6 capped their SLO penalty at 3;
  * the action head starts biased toward "hold" (logit +1.5), because uniform exploration over −1…+3 drifts upward by one replica per decision. This bias only changes where training starts, not the objective.

  The training runs were restarted from scratch with these changes. No test-set or live data was used.

  **Amendment 2 (2026-10-26 23:43, before any test or live v7 result): per-service credit.** With the capped reward, the restarted run held every service at its minimum through 200k steps. Its validation reward, −6.92, is exactly that of holding (the best simple rule scores −4.23).

  The cause is structural. One global reward judged 16 simultaneous per-service decisions, so a good scale-up of one service is buried in the noise of the other 15 actions. The fix keeps the objective and changes who gets credit:
  * **Agents:** every service is an agent (shared network parameters). It decides from the whole application, i.e. message passing over the call graph, plus a one-hot of itself.
  * **Rewards:** each agent receives its own share of the step's reward. It pays its own replicas and replica changes, plus the share of the end-to-end latency penalty that its own queueing causes: share ∝ (fraction of requests reaching it) × (its own excess latency).
  * **Consistency with the objective:** the shares sum exactly to the global reward (`tests/test_v7.py`).

  This matches how the policy is used live: one decision per service.

  Implementation:
  * `TwinAgentsVecEnv` (4 simulations × 20 agent slots) and `GraphFocalExtractor`;
  * SB3 actor-critic with 64-unit heads; PPO 64 steps per slot, batch 512, other settings as §4.3;
  * 4M agent-steps per run, validated every 250k.

  The joint-reward run was stopped; it is not a candidate because it never finished. No test-set or live data was used.

  **Amendment 3 (2026-10-27 01:10, before any test or live v7 result): bounded queues in the twin.** The focal run still equalled holding after 1.5M agent-steps, so a diagnostic was run on a two-service app with one clearly overloaded service. The policy did not learn to scale it up. The twin's queues were unbounded: one overload built a backlog of CPU-seconds that kept the latency penalty at its cap for minutes, whatever was done. Locust is closed-loop: each user has at most one outstanding request, so a service can only hold the requests of the users waiting on it.
  * **Change:** the backlog is now capped at `users × (fraction of requests reaching the service) × CPU per request`; spawn-driven login bursts still queue in full.
  * **Re-validation:** against live native HPA, replica-hours are unchanged (3.8% and 3.3% mean error). flash_sale p95 is 673 ms, closer to live (448–670 ms).
  * **Learnability:** in the same diagnostic the policy now learns within 50k decisions to scale the overloaded service (83% probability of +1…+3) and to hold the idle one (99%).

  Training restarted from scratch on the fixed twin. No test-set or live data was used.

  **Amendment 4 (2026-10-27 01:25, before any test or live v7 result): warm start, then fine-tune.** On the fixed twin, PPO from scratch was still at the level of holding after 500k agent-steps: validation −6.86, against −4.18 for the best rule. The diagnostic shows it *can* learn the basic behaviour, but not fast enough for the time available. The main runs therefore use the recipe of v5/v6:
  * **Imitation:** the focal policy first imitates the rule that the §4.3 protocol already selects on validation. It runs 400 training-distribution episodes with 20% random deviations, cross-entropy on the rule's actions, and the critic fitted to the rule's per-service returns.
  * **Fine-tuning:** PPO then fine-tunes with small steps (lr 1e-4, clip 0.1, target KL 0.02) for 2M agent-steps.
  * **Checkpoint 0:** the warm start is evaluated and saved as checkpoint 0, so the selected checkpoint can never be worse on validation than the imitation.

  The runs are `focal_bc_s1` and `focal_bc_s2` (main), plus the ablations `focal_bc_nograph_s1` and `focal_bc_v5reward_s1`.

  What this means for attribution: if v7 ends at the rule's level, the learned policy adds nothing beyond the rule. The live rule arm (§3.2) measures exactly that.
* **Training episodes**:
  * 75%: the shop with every fitted parameter perturbed by ±30%, under randomised scenario shapes: peak 8–45 users, stage timings, mixes, extra spikes and drops, 300–600 s;
  * 25%: synthetic applications with random call DAGs of 5–18 services, sometimes one serial service. This forces the policy to read features and the graph rather than memorise service identities.

  The exact live evaluation conditions are only in the test set.

### 4.3 Training and selection protocol (fixed 2026-10-26 23:25, before the first training run)

* **Runs after amendment 2:** focal design, v7 reward, seeds 1 and 2; ablations (seed 1): `focal_nograph_s1`, and `focal_v5reward_s1`, which uses the v4–v6 *per-service* reward structure (SLO term + 0.3 × |CPU% of request − 70| + 0.1 × stability + replica cost). Selection, the heuristic arm and the test sets are unchanged. **v7** is the best of the finished main runs (v7 reward, graph) on validation.
* **Runs as first fixed** (joint design; superseded by amendment 2. `scripts/train_v7.py`, PPO settings chosen once: 8 environments × 128 steps, batch 256, 10 epochs, lr 3e-4, γ 0.97, GAE 0.95, clip 0.2, entropy 0.01):
  * graph policy with the v7 reward, seeds 1 and 2;
  * ablation without the graph (`use_graph=False`), seed 1;
  * ablation with the v4–v6 reward structure transplanted to the twin (`kind="v5"`: SLO term + 0.3 × |CPU% of request − 70| + stability + replica cost), seed 1.
* **Selection**: every 100k steps the deterministic policy runs the validation set: the unperturbed shop, 40 random workloads, seeds 10000–10039. Each run keeps its best checkpoint by mean v7 episode reward. **v7** is the better of the two graph runs on validation.
* **Heuristic arm (§3.2)**: the best rule on the same validation set from a fixed family. The family is "scale to ⌈CPU / (t × limit)⌉ when above t; one replica down when the rest would stay below d", with t ∈ {0.4, 0.5, 0.6, 0.7} and d ∈ {0.2, 0.3}, under the same guards.
* **Test (once, after selection, every controller on the same episodes)**:
  * T1: the six live scenarios at 25 users, 5 seeds each;
  * T2: 60 random shop workloads;
  * T3: 40 random synthetic applications.

  The controllers are native HPA (default; 60 s window at 70, 150, 250 and 350%), the v5-era threshold rule, the rule family, v7, and both ablations. The live arms use the selected model and rule **whatever these results are**.

## 5. Running record

| Time (IST) | Step |
| :--- | :--- |
| 2026-10-26 22:30 | Diagnosis (§1) from code, model cards and the 61 runs of the 16-service shop. Scripts: `scripts/analysis/svc_stats.py`, `scripts/analysis/latency_knee.py`. |
| 2026-10-26 22:35 | §2–§3 fixed before any calibration or v7 run. The calibration plan file is time-stamped 22:36:50. |
| 2026-10-26 22:37 | Lab restarted with `hpa_tuned`; calibration plan launched. It waits: the laptop has been on battery since about 22:35. |
| 2026-10-26 22:55 | Twin fitted and validated (§4.1); headroom check (§4.1). Checkpoint commit `ca9b7b5` (23:00) on branch `flexascale-v7`. |
| 2026-10-26 23:05 | §4.2–§4.3 fixed; training starts (`logs/train_v7.out`). |
| 2026-10-26 23:14 | Training restarted twice, with no change to the protocol. First restart: the validation score had counted churn per scaling action, while the training reward counted it per replica changed; both now count per replica (`twin.replica_changes`). Second restart (23:18): the 8 environments now step in one process (`DummyVecEnv`) instead of 8 subprocesses. That saves about 4 GB of RAM on a laptop that was swapping; the environments, seeds and settings are the same. Logs of the aborted starts: `logs/train_v7.aborted_*.out`. |
| 2026-10-26 23:20 | The plan runner freezes the training process (SIGSTOP) during each run's settle and load window and resumes it afterwards. Training cannot become host load in a measured window, and calibration can proceed during training once the laptop is back on AC. |
| 2026-10-26 23:30 | Reward amendment (§4.2): latency penalty capped, hold-biased start. Training restarted from scratch (`logs/train_v7.aborted_2330.out` holds the collapsed first run). |
| 2026-10-26 23:43 | Amendment 2 (§4.2): per-service credit (focal multi-agent design). The joint run was stopped at 200k steps without learning beyond "hold". |
| 2026-10-27 00:25 | Still on battery (17%; unplugged since about 22:35). Training paused itself at 34% after 250k agent-steps of `focal_s1` (validation still equal to holding). No calibration or evaluation run has started; they need AC power. After the charger is back (or after a shutdown), `./scripts/v7_resume.sh` resumes both. |
| 2026-10-27 00:45 | AC power back. Calibration started (run 1 at 00:45:40); training resumed. The runner froze training during each settle and load window as designed. |
| 2026-10-27 01:10 | Amendment 3 (§4.2): closed-loop queue bound in the twin. Training restarted on the fixed twin (`logs/train_v7.unbounded_queue_0110.out` holds the stopped run). |
| 2026-10-27 01:25 | Amendment 4 (§4.2): warm start from the validation-selected rule, then small-step PPO fine-tuning. The from-scratch focal run was stopped at 500k agent-steps (`logs/train_v7.focal_scratch_0125.out`). |
| 2026-10-27 01:36 | Amendment 4, class balance of the warm start (before any test or live v7 result). The first warm start agreed with the rule on 99.5% of held-out decisions, but the rule's own data contain almost no scale-ups: in 40 episodes, 17 of 24,647 labels were +1. The agreement therefore measured "hold" and "scale down" only. Each sample now has three copies whose focal CPU feature is rescaled by a factor of 0.3–4 and relabelled by the rule's own formula (`imitation_v7.limit_target_label`, tested equal to the rule). The loss uses inverse-frequency class weights, and the critic is fitted on the original samples only. PPO settings, selection and the test sets are unchanged. `focal_bc_s1` restarted from scratch (`logs/train_v7.bc_imbalanced_0136.out` holds the stopped start). |
| 2026-10-27 01:38 | Unclean reboot. The journal of the previous boot stops at 01:33, so the cause is unknown. Calibration run 5 (`20261027-013641`) was still settling and wrote nothing; it is in `reports/experiments_invalid/`. The plan resumed at 01:44 with run 5 in the same position. The stored augmentation needed about 5 GB at its peak, on a 15 GB laptop that also runs Minikube. Copies are now assembled per batch, so memory is what it was before the change. |
| 2026-10-27 01:55 | Host-load check (`scripts/check_host_load.py`) of calibration runs 1–5. Run 3 (`cal-150`, `20261027-010839`) was on battery for 85 s of its load window. Run 4 (`cal-250`, `20261027-012008`) had 2.24 cores outside Kubernetes; the source is not recorded. Both are invalid (§3.4); after run 8 they are moved to `reports/experiments_invalid/` and rerun once (`scripts/rerun_plan.py`). Runs 1, 2 and 5 are valid (1.45, 1.33 and 0.79 cores, on AC power). From now on, tests and other CPU-heavy work outside the training process are paused during load windows, as training is. |
| 2026-10-27 02:56 | Calibration complete (`scripts/v7_calibrate.sh`, `reports/v7/calibration.md`). Both reruns were valid (0.89 and 0.92 cores outside Kubernetes, on AC power). Every target has 2 valid runs. 70%, 150% and 250% meet the rule; 350% fails on p95 (230 vs 225.5 ms allowed) and on mean latency (68.0 vs 66.2 ms). **HPA-tuned: CPU target 250% of request, scale-down window 60 s.** At this load HPA-tuned uses 1.356 replica-hours, the floor of 16 single replicas for the whole run. |
| 2026-10-27 02:35 | Twin, validation set only (a scratch analysis; nothing in the protocol changed). The rule family lies on native HPA's own cost–latency curve. The selected rule 0.6/0.3 against HPA at 250%: replica-hours −0.22% [−0.5, +0.06], p95 +2.7 ms [−4.0, +9.5]. Rule 0.4/0.2: +1.9% and −29 ms; HPA at 150%: +3.7% and −44.5 ms. On these workloads HPA at 250% is 2.4% above the floor. A FlexaScale that only matches the rule would therefore be on par; a verdict of "beats" needs a better cost–latency trade-off than any single CPU target. |
| 2026-10-27 02:58 | Live plumbing smoke test (not part of the evaluation; outcomes used for no decision). Three runs on `calibration_steady` at 45 users for 180 s, not an evaluation condition: RL, Auto and the rule. They used a provisional snapshot of `focal_bc_s1` and temporary lab variants, removed afterwards. Checked: a decision every 10 s for all 16 services; the graph policy, Auto ownership and the rule path; features within the training ranges; actions applied without errors; clean starts and cleanups. The runs are in `reports/experiments_demo/`. |
| 2026-10-27 03:32 | **Selection (§4.3): v7 = `focal_bc_s2`**, best validation reward −3.35 at 250k agent-steps (`focal_bc_s1`: −3.56 at 1M; the warm starts −4.07 and −4.17; the rule −4.18). Selected rule: `limit_target(0.6/0.3)`. Selection uses only the two main runs, so it ran (`train_v7.py --select-only`) as soon as they finished. The ablations then train during the live evaluation, frozen in every load window (23:20). The twin test sets run once, after the ablations, with every controller. |
| 2026-10-27 03:43 | Promotion (`scripts/promote_v7.py`): `models/flexascale_v7/best_model/best_model.zip` (sha256 `5d4fcc20…`, `focal_bc_s2`), `config/apps/shopping_v7.yaml`, `config/apps/shopping_v7_rule.yaml`, lab variants `v7`/`v7_rule` and `reports/v7/arms.json` (HPA-tuned 250%, 60 s). The evaluation plan (`scripts/v7_plan.py`, 60 runs) is committed before its first run. |
| 2026-10-27 03:44 | Live evaluation started (`scripts/v7_evaluate.sh`, `logs/v7_evaluation.out`): 60 runs, then one rerun of each invalid run, then the verdict (`scripts/analyze_v7.py`). Ablations `focal_bc_nograph_s1` and `focal_bc_v5reward_s1` train meanwhile, frozen in every load window. |
| 2026-10-27 05:05 | Twin test sets, run once after the ablations (`reports/v7/training_v7.json` → `test`); they decide nothing, since the live arms were fixed at 03:43. **T1** (the six live scenarios in the twin, 5 seeds each), v7 (`focal_bc_s2`) against HPA 250%/60 s: replica-hours 1.352 vs 1.344 (+0.6% [−0.15, +1.26]); p95 344 vs 410 ms (−66 [−144, +12]); SLO-violation 3.5 vs 5.7 s. The whole p95 gain is in flash_sale: −385 ms at −1.2% replica-hours. checkout_heavy: −11 ms at +4.5%. The other four scenarios are identical, with both controllers at the floor. **T2** (60 random shop workloads): +0.4% replica-hours, p95 −37 ms. **T3** (40 unseen synthetic apps): −2.7% replica-hours, p95 −46 ms. Ablations on T1: without the graph p95 396 ms, with the v5 reward 396 ms; the rule 423 ms. **Expectation, stated before any live outcome is analysed:** with the effect in one of six scenarios, 12 pooled blocks are unlikely to give a p95 interval below 0, even if live matches the twin. The likely verdict is "on par / inconclusive", with a large flash-sale improvement. |
| 2026-10-27 05:15 | §3.6 added (commit `5cbf59b`, 05:15:30): a confirmatory flash-sale study (10 blocks × HPA-tuned, RL, heuristic), to run after the 12-block batch. The hypothesis comes from the twin test set (05:05). When it was fixed, 7 runs of the batch had completed (block 1, steady_browsing, and the first two runs of block 2, checkout_heavy). Their summary lines were visible in the plan log, but no comparison was computed, and no flash_sale run of the batch had started. Code: `scripts/v7_plan.py spike`, `scripts/analyze_v7.py --study spike` (no six-scenario check C7), `scripts/v7_spike.sh`; `v7_resume.sh` resumes it. |
| 2026-10-27 07:40 | Disclosure: the status line of the batch monitor printed one run's summary (run 17, FlexaScale-RL, flash_sale). No comparison was computed, and §3.5 and §3.6 were already fixed. The monitor now prints only run starts and errors until the batch is analysed. |
| 2026-10-27 15:17 | The laptop was unplugged at about 15:17:37, after run 51's load window (15:12:22–15:17:35, 0 s on battery, 1.76 cores outside Kubernetes: valid). The plan runner waits for AC power before run 52, as designed; no run is affected. |
| 2026-10-27 17:27 | AC power back (battery 51%); run 52 started at 17:27:40. While waiting, a guard was ready to stop the environment safely at 15% battery (`stop_review.sh`, then `minikube stop`, and `v7_resume.sh` on AC); it was not needed. |
| 2026-10-27 19:16 | **Batch complete: 60 valid runs, no reruns. The pre-registered §3.5 verdict against HPA-tuned:** FlexaScale-Auto **beats on performance** (p95 −21.6% [−33.5, −9.8], replica-hours +0.2% [−0.3, +0.7]). FlexaScale-RL is **on par / inconclusive** (p95 −2.5% [−40.0, +35.1], p50 −16.6% [−26.2, −7.0]). FlexaScale-heuristic **beats on performance** (p95 −20.4% [−33.5, −7.3]). See `reports/v7/evaluation.md`. |
| 2026-10-27 19:19 | **A confound, found in the batch before any further run: the CPU clock differed by arm.** (1) In steady_browsing every arm keeps all 16 services at 1 replica for the whole run, yet the FlexaScale arms had a 6–10% lower p50 in every time window. (2) In the first minute of every scenario, with identical replicas, the paired p50 was lower in the FlexaScale arms in 10 of 12 blocks. (3) Every shop container used 10–20% more CPU-seconds in both HPA arms than in all three FlexaScale arms, for the same work. (4) node-exporter's mean CPU clock during the load windows: HPA-tuned 1649 MHz, HPA-default 1761, RL 1917, Auto 1880, heuristic 2353. Under the laptop's `balanced` power profile the clock follows host activity. Live FlexaScale control added about 0.55 host cores (1.34–1.39 vs 0.80–0.85 cores outside Kubernetes), which is not the operator process itself (0.12–0.16 cores in observe mode, measured). §3.1 assumed the same host processes in every arm; that assumption did not hold. **The §3.5 verdict therefore cannot be attributed to FlexaScale's scaling decisions,** and the claim that FlexaScale beats a fair HPA is not supported by this batch. A sequential-request probe with a synthetic busy-loop load showed no latency change (18.52 vs 18.65 ms). The clock data, not that probe, is the evidence. §3.6 is withdrawn: its first run was stopped at 19:19:22 while preparing, with no data (`reports/experiments_invalid/`). |
| 2026-10-27 19:31 | Power profile set to `performance` (tuned `throughput-performance`: EPP and governor `performance`), so the CPU clock no longer follows host load; it will be restored to `balanced` afterwards. `scripts/check_host_load.py` now also records each run's mean CPU clock (`cpu_mhz`). A setup pilot, not counted anywhere: steady_browsing × {HPA-tuned, RL} × 2 blocks, alternating order (labels `pilot-…`). It checks that the clock and the steady-state latency no longer differ by arm in a scenario where scaling is identical. |
| 2026-10-27 20:12 | Setup pilot under `performance` (§3.7): environment parity restored in steady_browsing (p50 8.0 ms in both arms, the shop about twice as fast as under `balanced`; RL's shop CPU per request +5%, i.e. slightly slower). §3.7 fixed with the parity rule (shop CPU per request in steady_browsing) in place of the node-clock criterion, before any replication run. |
| 2026-10-27 21:48 | Replication paused at 8/48: the laptop was unplugged at 21:48:44, two seconds after run 8's load window (21:43:32–21:48:42, 0 s on battery: valid). The runner waits for AC; the 15% battery guard is armed again. |
| 2026-10-27 22:30 | Still on battery, draining faster under `performance`. While the replication waits, the profile is `balanced` and new runs are blocked by `.runtime/pause_live_runs`. When AC returns, the guard sets `performance`, checks it, and only then removes the pause file, so no replication run can start under `balanced`. At 15% battery it stops the environment safely instead. |
| 2026-10-27 23:28 | While live runs were paused on battery: operator image `flexascale:0.5.0` built (`deploy/flexascale/Dockerfile`; `.dockerignore` now allows `models/flexascale_v7/`) and loaded into Minikube. Inside the image the v7 runtime loads as a focal graph policy (n_max 20, sha256 `5d4fcc20…`, the promoted model), and so does v5. `helm lint` with `helm/flexascale/values-v7.yaml` passes. The in-cluster operator stays at 0.4.0 (observe) until the replication ends, so the environment does not change mid-study. |
| 2026-10-28 00:09 | AC back (battery 35%). The guard set `performance` (00:09:31) before removing the pause file; replication run 9 started at 00:09:47 under `performance`. |
| 2026-10-28 08:01 | **Replication (§3.7) complete: 48 valid runs, no reruns; environment parity holds** (candidates' shops 4.4–5.6% *slower* per request than HPA-tuned's in steady_browsing). **Verdict against HPA-tuned: FlexaScale-RL, FlexaScale-Auto and FlexaScale-heuristic are all on par / inconclusive.** Auto: replica-hours +0.1% [−0.1, +0.2], p95 +0.1% [−9.3, +9.5], failures +0.0 pp, throughput +0.0% [−1.2, +1.2]. RL: p95 +7.2% [−8.1, +22.4]. Heuristic: p95 +4.5% [−6.6, +15.6]. The batch's 20% p95 advantage was the environment confound. The twin's predicted flash-sale gain did not appear live (Auto: +34.3% / −9.6% in the two flash_sale pairs). **By the rule fixed in advance, FlexaScale v7 does not beat a fairly tuned native HPA on this testbed; it matches it at equal cost.** See `reports/v7/replication.md`. |
| 2026-10-28 08:13 | In-cluster check of the v7 deployment path. `helm upgrade` of the in-cluster operator with image `flexascale:0.5.0` and `helm/flexascale/values-v7.yaml`, in observe mode. The operator loaded the v7 model (observation version 3, no model error) and made 528 decisions through the graph policy, applying none. Rolled back afterwards to the previous release (revision 7: image 0.4.0, v5 model, observe). The power profile is back to `balanced`. |
