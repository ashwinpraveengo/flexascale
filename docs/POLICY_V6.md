# FlexaScale Policy v6: training under the live control loop

## 1. Why

v5 (`docs/POLICY_V5.md`) beat the HPA-like rule in its simulator but not native HPA on the cluster (+8% replica-hours, p95 +6.5%, 12 live pairs). The live decision logs of v5's two gradual-ramp runs show why the simulator gain did not transfer:

* About a third of v5's scale-up proposals were blocked by the operator's own guards: the confidence gate (31), waiting for starting pods (29) and the 30 s scale-up cooldown (23). The simulator had none of these guards.
* v5 handed services back to HPA about 25 times per run because its confidence dropped below the deactivation threshold, which causes churn.
* v5 moves ±1 replica per decision. Native HPA jumps to `ceil(n × cpu / target)` in one step.
* v5 was trained on one-minute steps in which a new replica serves at once. Live, the operator decides every 10–15 s, a new pod is ready after 10 s (median of 510 live scale-ups, p90 15 s), and the CPU it sees is a 1-minute Prometheus rate.
* v5 was compared with a stateless threshold rule. Native HPA also keeps replicas for 5 minutes after load falls (scale-down stabilisation).

## 2. What changed

**Simulator: `FlexaScaleEnvV3`** (`src/flexascale/simulator/control_env.py`). It keeps v4/v5's trace demand, dependency chain, shared bottleneck, SLOs, traffic events, observation (version 2) and reward. It adds:

* 15 s decisions (4 per trace minute, demand interpolated); 120 decisions per 30-minute episode.
* New replicas are ready after 1 step (30% of the time 2), matching the live measurement. Capacity uses ready replicas; cost uses requested replicas.
* Observed CPU is the mean over the last 4 steps (a 1-minute rate). The rate trend compares with 4 steps ago.
* The agent's service is subject to the operator's guards, the same as live (`app_operator._decide`): scale-up cooldown 1 step, no scale-up while replicas are starting, scale-down cooldown 2 steps, at most 2 replicas down per decision, no scale-down at ≥ 85% CPU or above the SLO.
* Neighbour services follow the **native HPA algorithm**: 70% target, 10% tolerance, scale-up limit max(2×, +4) per 15 s, 5-minute scale-down stabilisation. A random action is taken 20% of the time.

**Actions:** replica change −2, −1, 0, +1, +2, +3 per decision (v5: −1, 0, +1). The live operator reads the deltas from the model card and clips them to the policy's `max_step` / `max_scale_down_step`.

**Warm start:** imitate native HPA's ratio rule (`ceil(n × cpu / 0.7)` outside ±10%, mapped to the nearest delta), with the actor and critic trained together as in v5. Then PPO fine-tuning with small steps.

**Baseline:** the simulator's `slot0_controller='hpa'` runs the native HPA algorithm on the agent's service, without FlexaScale's guards. That is the controller FlexaScale replaces on the cluster.

Headroom check before training (validation services, 80 episodes, not used for selection): native HPA scored +0.102 reward per step. Stateless ratio rules under the guards scored +0.065 to +0.100, depending on the guard settings. Hand-written latency- and trend-aware rules scored +0.046 to +0.097. So **in this simulator native HPA is a strong baseline**, and beating it requires using information HPA does not use.

## 3. Protocol (fixed before any v6 result was seen, 2026-10-25)

* **Grid** (`scripts/train_v6.sh`): learning rate {1e-4, 3e-5} × seeds {1, 2}; clip 0.1, entropy 0.001, target KL 0.02, γ 0.97, 8 environments, 1.5M steps. Warm start: 3000 teacher episodes. Settings chosen once.
* **Selection** (`scripts/evaluate_v6.py`): every candidate (warm start, best and final checkpoint of each run) runs 200 validation-service episodes (seeds 10000–10199). The highest mean reward per step is selected.
* **Test:** one run on the test services, fresh seeds 40000–40299, paired. Baselines: native HPA, the HPA ratio rule under the guards (the teacher), v5, v6 without neighbours (ablation), hold.
* **Live operator settings for v6** (`config/apps/shopping.yaml`): poll 15 s, scale-up cooldown 15 s, scale-down cooldown 30 s, `max_step` 3, `max_scale_down_step` 2, matching the simulator. The confidence gate is set from v6's confidence distribution on the validation episodes, before any live run: the activation threshold is the 5th percentile of the chosen-action probability.
* **Live benchmark:** the 16-service shop, six scenarios × {native HPA, v6} × 3 repeats, 25 users, 300 s, alternating per scenario. Before every run, inventory is restocked and the test carts are emptied (`config/lab.yaml` `reset_requests`). A pair counts only if both runs complete on a healthy cluster. Every number is reported as measured, with the per-scenario sign agreement across repeats and the mean of paired differences with a 95% confidence interval.

### 3.1 What counts as "beats native HPA" (fixed 2026-10-25, before any v6 result)

Simulation (test, paired): the 95% confidence interval of Δ reward (v6 − native HPA) lies above 0.

Live (18 pairs, Δ = v6 − HPA in the same scenario and repeat; 95% interval of the mean over pairs):

| Verdict | Condition |
| :--- | :--- |
| **Beats HPA on cost** | Δ replica-hours < 0 with the interval below 0, **and** the interval of Δ failure rate (pp) and of Δ p95 (%) both include or lie below 0 (no measurable harm) |
| **Beats HPA on performance** | Δ p95 < 0 or Δ failure rate < 0 with the interval below 0, **and** the interval of Δ replica-hours includes or lies below 0 |
| **On par** | Every interval includes 0 |
| **Worse** | Any of the three intervals lies above 0 without one of the gains above |

Per-scenario results are reported with the number of repeats that agree in sign (3/3, 2/3), but the verdict uses only the pooled intervals above. No other metric, subset of scenarios or exclusion is used for the verdict. A pair is excluded only under the existing rule (a run did not complete on a healthy cluster), and every exclusion is listed.

## 4. Results

### 4.1 Training and selection (validation services, 200 episodes, `logs/evaluate_v6.out`)

| Run | Warm start (imitation) | Best checkpoint | Final (1.5M steps) |
| :--- | ---: | ---: | ---: |
| lr 1e-4, seed 1 | −0.028 | −0.082 | −0.310 |
| lr 1e-4, seed 2 | **+0.015** | −0.032 | −0.181 |
| lr 3e-5, seed 1 | −0.003 | −0.044 | −0.096 |
| lr 3e-5, seed 2 | −0.002 | −0.114 | −0.146 |
| *Native HPA, same episodes* | | | *+0.077* |

**PPO fine-tuning made every run worse than its own warm start.** By the protocol, the warm start of `lr1e-4_s2` was selected. It imitates HPA's ratio rule with 83% agreement, so the "v6 policy" is in effect an imitation of HPA, not an improvement on it. The imitation was more accurate than v5's (warm-start agreement 83–85%), but the critic's value loss stayed large (~70) throughout. In a 120-step episode with start-up delay, guards and a 1-minute CPU lag, the advantage estimates are noisy, so the small, clipped PPO updates moved the policy away from the teacher, not past it.

### 4.2 Test (test services, 300 paired episodes, seeds 40000–40299; `reports/simulation_evaluation_v6.md`)

| v6 vs | Δ reward / step | Δ SLO violation rate | Δ avg replicas | Episodes v6 better |
| :--- | ---: | ---: | ---: | ---: |
| Native HPA | **−0.048 ± 0.018** | +0.006 ± 0.003 | +0.29 ± 0.16 | 34% |
| HPA ratio rule (teacher, under guards) | −0.036 ± 0.010 | +0.003 ± 0.004 | +0.16 ± 0.04 | 23% |
| v5 | +0.052 ± 0.015 | −0.011 ± 0.006 | −0.20 ± 0.08 | 63% |
| v6 with neighbours neutralised | −0.009 ± 0.013 | −0.015 ± 0.006 | +0.31 ± 0.04 | 35% |

Absolute reward per step: native HPA +0.108, teacher +0.096, v6 +0.060, v5 +0.008, hold −0.520.

**Verdict under §3.1: v6 does not beat native HPA in simulation.** The interval of Δ reward lies below 0. It is worse in every traffic group: drop −0.01, none −0.11, ramp −0.06, spike −0.02. It improves on v5 (+0.052 ± 0.015), and the neighbour input still has no measurable benefit. The guards cost FlexaScale something native HPA does not pay: the teacher under the guards is already 0.012 below native HPA.

### 4.3 Decision

The protocol makes a live v6 batch pointless: it already loses in the simulator built to match the live loop. With the user's agreement (2026-10-26), it was not run. v5 stays the deployed policy, since it is the only model with live results. The remaining time went to Auto mode (`operator/auto_mode.py`, §5) and the redesigned dashboard.

### 4.4 What the three policy attempts show

| Attempt | Idea | Result vs HPA |
| :--- | :--- | :--- |
| v4 | Realistic dependency simulator, unit-free inputs | Below the HPA-like rule (sim); on par live (6 pairs, wide intervals) |
| v5 | Imitate HPA, then PPO | Above the HPA-like rule (sim), below a tuned rule; **worse live**: replica-hours +8.0% (95% CI +0.8 … +15.1, 12 pairs; 5 pairs on battery in both arms, +6.4% on the 7 AC pairs, CI −6.7 … +19.5) |
| v6 | v5 in a simulator matching the live control loop, multi-replica actions | Below native HPA (sim): −0.048 ± 0.018 |

For CPU-driven scaling of these services, native HPA's ratio rule with scale-down stabilisation is a strong controller. Neither the extra signals (latency/SLO, rate trend) nor the dependency neighbours gave the learned policy a measurable edge in any of the three setups. That is the project's result on the policy question, reported as measured.

## 5. Auto mode

`--auto` (dashboard: Auto) keeps FlexaScale's ownership machinery (Lease, HPA freeze/restore) and replaces the plain confidence gate with ordered, logged rules per service and step: controller health → policy confidence → SLA risk (capacity first: if the service is over its SLO or CPU risk level and HPA would run more replicas, HPA owns it) → efficiency (FlexaScale). Hand-backs to HPA on health or risk are immediate; moves to FlexaScale need `dwell_steps` consecutive steps. Every decision records the rule, its inputs and a one-line reason (`decisions.jsonl` → `auto`, dashboard Auto page). Configuration: the `auto:` block of the application policy, validated at start. Tests: `tests/test_auto_mode.py`. Live results: §5.1 (beats default native HPA on cost: −3.9% replica-hours over 18 pairs).

### 5.1 Live results: Auto mode vs native HPA (16-service shop, 2026-10-26)

Clean batch `logs/live_auto_batch_v2.out`, 04:35–12:18: 3 repeats × 6 scenarios, HPA then Auto in each scenario, 25 users, 300 s, comparable start, order-service 1.3. All 36 runs completed with cleanup verified, and no pair was excluded. No app container restarted (Prometheus `kube_pod_container_status_restarts_total`), and every order-service pod stayed at or below 84 MiB of 256 MiB (15 s samples). The first batch of the night was invalid; see `reports/experiments_invalid/README.md`. Full tables are in `reports/live_benchmark_report.md`.

| Auto − HPA, mean over 18 pairs | Mean | 95% interval |
| :--- | ---: | :--- |
| Replica-hours | −3.9% | −6.5 … −1.3 |
| Estimated cost (Fargate list prices) | −4.0% | −6.6 … −1.3 |
| p95 latency | +2.8% | −8.0 … +13.6 |
| Failure rate | −0.07 pp | −0.12 … −0.02 |
| Throughput | +0.7% | −0.3 … +1.7 |

**Verdict (§3.1 rule): beats native HPA on cost.** The replica-hours interval lies below 0, and the p95 and failure intervals include or lie below 0.

| Scenario | Δ replica-h % (rep 1 / 2 / 3) | Δ p95 % (rep 1 / 2 / 3) |
| :--- | :--- | :--- |
| checkout_heavy | −6.5 / −6.4 / −11.3 | +26.1 / −8.0 / −17.2 |
| flash_sale | −9.0 / −7.7 / +1.6 | +25.0 / −4.9 / +0.0 |
| gradual_ramp | −0.6 / −0.6 / +8.8 | +7.7 / −14.3 / +75.0 |
| payment_degradation | −1.4 / −1.8 / −2.4 | +0.0 / −10.0 / +0.0 |
| steady_browsing | −3.9 / −2.5 / −3.1 | +7.8 / −2.9 / +1.5 |
| traffic_drop | −12.0 / −11.4 / −0.4 | −13.3 / −12.5 / −9.7 |

Replica-hours were lower in 16 of 18 pairs. Repeat 3 was weaker than repeats 1–2 (which gave −5.3% over 12 pairs):

* In the gradual_ramp Auto run, FlexaScale scaled up 7 times and peaked at 23 replicas, against 18 for HPA. p95 was 280 ms against 160 ms, both far below the 1,000 ms SLO. Most of this run's load ran on battery (next point), and its HPA arm did not.
* On flash_sale and traffic_drop the HPA run itself used more replicas than in repeats 1–2 (1.87 and 1.66 replica-hours, against about 1.99 and 1.59), so the difference to Auto was small.
* The laptop lost AC power at 11:52:05 (`/var/lib/upower` charge history), and the CPUs then ran at about 1 GHz. That was 96 s into the load window of the gradual_ramp Auto run (11:50:28–11:55:42, so 218 of its 314 s on battery, while its HPA arm ran on AC), so that run's extra scale-ups are at least partly a battery effect: slower services use more CPU per request. The last pair (traffic_drop, 11:55 and 12:07) ran entirely on battery; latency was about twice that of repeats 1–2 in both arms. All runs completed normally, so under the pre-registered rule both pairs are kept. Without the two battery-affected pairs (host-load criterion, §5.2), over 16 pairs: replica-hours **−4.9%** (95% CI −7.2 … −2.6), estimated cost −5.0% (−7.3 … −2.7), p95 −0.9% (−7.7 … +5.9), failures −0.08 pp (−0.14 … −0.03), lower in 15 of 16 pairs, with the same verdict. (Without only the last pair, as first reported: −4.1%, CI −6.9 … −1.4.)
* Outside the battery period, no run of this batch had more than 1.64 cores of host CPU in use outside Kubernetes (`reports/host_load_by_run.csv`), so there is no sign of other host load during the batch.

The p95 differences change sign between repeats in most scenarios; traffic_drop is lower in all three.

**Mechanism.** Replica changes recorded during the runs:
* HPA runs: 86 scale-ups and **0 scale-downs**. Native HPA's default 300 s scale-down stabilisation window outlasts every 300 s run.
* Auto runs: FlexaScale made 52 scale-ups and **56 scale-downs** in the services it owned, and HPA made 44 scale-ups after hand-backs.

Of all per-service decisions, 94% were made by the efficiency rule, 4% by policy confidence and 3% by SLA risk. The SLA-risk rule hands services under latency or CPU pressure back to HPA, and the failure rate did not rise.

**Robustness.** HPA always ran first within a pair. Pairing each Auto run with the default-HPA run that *followed* it instead gives replica-hours −5.1% (95% CI −8.1 … −2.1, 12 pairs, all negative; `scripts/check_auto_run_order.py`).

**What this does and does not show.** Auto mode used about 4% fewer replica-hours (estimated cost) than *default* native HPA in 300 s runs on a single-node cluster, with no measurable latency penalty and a marginally lower failure rate. It does not show that the learned policy makes better decisions than a tuned threshold rule. The saving comes from scaling down sooner, and the policy also over-scaled once (gradual_ramp, repeat 3, in a run mostly on battery). §5.2 tests a native HPA with a 60 s scale-down window: it saves less (−1.4% over 12 pairs), and the indirect comparison does not show a difference from Auto (−2.5 points, 95% CI −5.4 … +0.3).

### 5.2 Tuned-HPA reference (exploratory; design fixed 2026-10-26 10:35, before any such run)

Question: is Auto's saving more than what native HPA would get by scaling down sooner? Native HPA's default scale-down stabilisation window is 300 s, so in a 300 s run it never scales down.

* Controller `hpa_fast`: native HPA with only `behavior.scaleDown.stabilizationWindowSeconds` = 60 s on every HPA. The original `spec.behavior` is stored on the HPA and restored after the run, and at the start of every run.
* One run per scenario, after the Auto batch, in this order: traffic_drop, flash_sale, checkout_heavy, steady_browsing, payment_degradation, gradual_ramp. The order is by the size of Auto's saving, largest first. Runs are started until 13:15. Whatever has completed is reported, with its n.
* Each run is compared with the latest earlier default-HPA run of the same scenario (repeat 3 of the batch). These pairs are not adjacent in time, so this is exploratory: it does not change the §3.1 verdict, and the dashboard and report label it as a reference.
* Reading: if the tuned HPA's replica-hours saving is similar to Auto's (−5 to −6%) with no extra latency or failures, Auto's live saving is explained by the scale-down window, and the honest claim is "safe, explainable ownership arbitration", not "better scaling decisions". If the tuned HPA saves less, or saves as much but with more failures or higher p95, Auto adds something beyond the window.

**First attempt (2026-10-26 12:20–13:00): invalid.** Three tuned runs completed (traffic_drop, flash_sale, checkout_heavy), but the laptop had been running on battery since 11:52, at about 1 GHz instead of up to 4.6 GHz. Every service was about 4× slower than in the AC-powered default-HPA runs they would be compared with (`reports/experiments_invalid/README.md`), so the comparison is invalid and the runs are excluded. One observation does not depend on speed: in the flash_sale run the tuned HPA made no scale-down at all, because load stays high until the end, so a shorter window cannot help there. A fair test needs HPA and `hpa_fast` runs adjacent in time, on AC power.

**AC-power rerun (decided 2026-10-26 13:08, before its result).** After the charger was reconnected, one adjacent pair was run: default HPA, then `hpa_fast`, on traffic_drop (first in the pre-registered order and the scenario with Auto's largest saving), 25 users, 300 s, comparable start (`logs/live_hpa_fast_ac.out`). One pair cannot give an interval, so it is reported as a single observation next to the three Auto pairs of the same scenario, not as a verdict.

**AC-power result (withdrawn at 16:45: its `hpa_fast` arm ran under outside host load; see the host-load criterion below).** Default HPA `20261026-130803-shopping-hpa-traffic_drop`, then `hpa_fast` `20261026-131404-shopping-hpa_fast-traffic_drop`. Comparable under the lab's rules; service latency was normal (recommendation 24 ms, search 23 ms, as in the morning batch).

| traffic_drop | Default HPA | HPA, 60 s scale-down | Δ |
| :--- | ---: | ---: | ---: |
| Replica-hours | 1.649 | 1.443 | **−12.5%** |
| Estimated cost ($) | 0.00749 | 0.00654 | −12.7% |
| p95 latency (ms) | 170 | 180 | +5.9% |
| Failure rate (%) | 0.08 | 0.34 | +0.27 pp |
| Peak replicas | 21 | 18 | −3 |
| Scale-downs | 0 | 2 (first at 165 s) | |

Auto on the same scenario saved −12.0%, −11.4% and −0.4% in its three pairs. **Reading at the time (withdrawn with the pair):** a native HPA with a shorter scale-down window reached the same saving as Auto's best traffic_drop pairs, with similar p95. Auto's live saving is therefore explained, at least on this scenario, by scaling down sooner than the default 300 s window, not by better decisions from the learned policy. The honest claim for Auto is safe, explainable ownership arbitration: a learned controller acts only where logged rules allow it, and gives every service back to native HPA under risk. This is one pair in one scenario, with no interval. Part of the difference is scale-up variation (peak 18 vs 21 replicas), and the failure rate was slightly higher (+0.27 pp, one run). Running all six scenarios is left as future work: `FLEXASCALE_CONTROLLERS=hpa,hpa_fast ./scripts/run_live_batch.sh 3 logs/live_hpa_fast.out`, on AC power.

**Six-scenario tuned batch (design fixed 2026-10-26 14:05, before any of its runs).**

* Runs: 2 repeats × 6 scenarios × (default HPA, then `hpa_fast`), adjacent in time per scenario, in the batch script's order (steady_browsing, checkout_heavy, payment_degradation, flash_sale, gradual_ramp, traffic_drop). 25 users, spawn 5, 300 s, comparable start, AC power, under `systemd-inhibit` (`FLEXASCALE_CONTROLLERS=hpa,hpa_fast ./scripts/run_live_batch.sh 2 logs/live_hpa_fast_batch.out`).
* Pooled with the 13:08/13:14 AC pair above (same design), so up to 13 pairs. The exclusion rules are the existing ones: a pair counts only if both arms complete on a healthy cluster and on AC power; an invalid pair is rerun once at the end if it can start before 20:30, otherwise it is reported as missing.
* Tuned HPA vs default HPA: the §3.1 rule, applied to the pooled `hpa_fast` pairs.
* Auto vs tuned HPA: both are measured as paired differences against default HPA, so they are compared through those differences. For replica-hours, the 95% Welch interval of (mean Auto Δ over its 18 pairs − mean tuned Δ). Below 0: Auto saves more than a tuned HPA. Above 0: the tuned HPA saves more. Includes 0: no difference shown. p95 and failure differences are reported the same way, descriptively. This is indirect (different baseline runs and times of day) and does not change the §5.1 verdict.

**Host-load criterion (added 2026-10-26 16:45, from host measurements only).** At 14:35 a default-HPA run was much slower than the morning's (checkout_heavy p95 650 ms against 230–290 ms). The cause was outside the cluster. In bursts from 13:18 to 14:47, processes on the same laptop that are not part of FlexaScale (among them another project's model-training job, from 14:18) used up to 12 extra CPU cores, and the host was swapping. The host has been back to normal since 14:50. A run is now called *host-affected* if, during its load window, (a) the laptop was on battery for any part of it (`/var/lib/upower` charge history), or (b) the host used on average more than 2.0 CPU cores outside the Kubernetes containers (Prometheus: `node_cpu_seconds_total` busy minus `container_cpu_usage_seconds_total` of all pods). Normal values today are 0.6–0.9 cores for HPA runs and 1.1–1.6 for Auto runs, whose operator runs on the host. The criterion uses no outcome metric, and it is applied to every run of the day by `scripts/check_host_load.py` (`reports/host_load_by_run.csv`).

* Tuned batch: a pair with a host-affected arm is invalid under the "healthy cluster, AC power" rule above. This affects the steady_browsing and checkout_heavy pairs of repeat 1 (3.9–5.5 cores outside Kubernetes in all four runs). It also affects the 13:08/13:14 traffic_drop pair: its `hpa_fast` arm ran with 5.6 cores of outside load, its default-HPA arm with 1.0. The −12.5% reported above for that pair is therefore withdrawn. The three pairs are moved to `reports/experiments_invalid/` and rerun once after repeat 2 (they can all start before 20:30).
* Auto batch (§5.1): its rule, fixed before the batch, did not cover host conditions, so the primary result keeps all 18 pairs. The battery period started at 11:52:05. That was during the load window of the repeat-3 gradual_ramp *Auto* run (11:50:28–11:55:42, 218 of 314 s on battery), so it affected two pairs, not only the last one. A sensitivity result without both pairs is reported in §5.1. No Auto-batch run exceeded the 2.0-core outside-load limit (maximum 1.64 cores outside the battery period).


**Result of the six-scenario tuned batch (2026-10-26 14:05–20:35; 12 pairs, all six scenarios).** Counted: 4 pairs of repeat 1 (its steady_browsing and checkout_heavy pairs were host-affected), all 6 of repeat 2 (`logs/live_hpa_fast_batch.out`), and the reruns of checkout_heavy and traffic_drop (`logs/live_hpa_fast_rerun.out`; the traffic_drop rerun replaces the withdrawn 13:08/13:14 pair). The steady_browsing rerun is missing: the laptop was unplugged from 19:25:29 to 19:33:52, during its default-HPA arm, and each pair is rerun only once. All 24 counted runs were on AC power with 0.66–1.87 cores in use outside Kubernetes (`reports/host_load_by_run.csv`), and every cleanup was verified.

| HPA with 60 s scale-down − default HPA (12 pairs) | Replica-hours | Estimated cost | p95 latency | Failure rate | Throughput |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Mean (95% CI) | −1.4% (−2.6 … −0.2) | −1.4% (−2.7 … −0.2) | +5.8% (−5.5 … +17.1) | +0.05 pp (−0.02 … +0.12) | −2.3% (−4.6 … −0.0) |

* Tuned HPA vs default HPA, §3.1 rule: **beats default HPA on cost** (replica-hours interval below 0; the p95 and failure intervals include 0). Throughput, which the rule does not include, was 2.3% lower; on flash_sale both tuned runs had 7–10% lower throughput, with p95 +15% and +52% (one of them made no scale-down at all, so the scale-down window is not clearly the cause). The mechanism is the one expected: 19 scale-downs in 12 runs against 0 for default HPA (58 and 56 scale-ups).
* Auto vs tuned HPA (rule fixed 14:05, 95% Welch interval of the paired differences): replica-hours **−2.5 points (−5.4 … +0.3): no difference shown**. Descriptively: estimated cost −2.6 points (−5.4 … +0.3), p95 −3.0 points (−17.9 … +12.0), failures −0.13 pp (−0.21 … −0.04), so Auto had fewer failed requests than the tuned HPA.
* **Reading.** Shortening HPA's scale-down window to 60 s gives part of the saving (−1.4%), with slightly lower throughput and slightly more failures. Auto's point estimate is larger (−3.9%) and its failure rate lower, but the indirect comparison does not establish that Auto saves more than a tuned HPA. The 10:35 reading rule ("if the tuned HPA saves less, Auto adds something beyond the window") points the same way as the point estimates; the formal 14:05 test is not significant, and it compares different baseline runs at different times of day. The earlier single pair that suggested "a tuned HPA saves as much" was an artefact of outside host load and is withdrawn. Auto's defensible claim is therefore: a learned controller acting only where logged rules allow it, with exclusive ownership and automatic hand-back, saved 3.9% against default HPA, at least as much as a 60 s scale-down window in point estimate, and it is not shown to beat a well-tuned HPA.


