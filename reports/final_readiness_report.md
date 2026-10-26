# FlexaScale Final Readiness Report

Date: 2026-10-23, updated 2026-10-24 (v4 policy, six-scenario live benchmark, replica restore for HPA-less Deployments, chart/image 0.3.0) 2026-10-25 (v5 policy, live benchmark with two repeats, chart/image 0.4.0) and 2026-10-26 (16-service shop, v6 policy attempt, Auto mode, redesigned control center; evening: six-scenario tuned-HPA batch, host-load check of every run, in-cluster Helm rollback/uninstall test with a fix in chart 0.4.1). Environment: Fedora 43, Docker, Minikube profile `flexascale` (Kubernetes v1.31, single node, a Docker container with 9 GiB RAM, raised from 6 GiB), Python 3.14 venv.

Status keys: **VERIFIED** (executed and checked here), **PARTIALLY VERIFIED**, **NOT VERIFIED**, **BLOCKED**.

## 1. Overall readiness

**Ready for the presentation as a working, safe, application-agnostic autoscaling *system*. The learned *policy* alone does not beat native HPA. Auto mode beats default native HPA on cost by a modest, statistically supported margin (§8.0).**

The one-command startup, live dashboard, comparable HPA-vs-FlexaScale experiments, ownership safety and cleanup are all verified on the live cluster. The deployed policy is now v5 (`docs/POLICY_V5.md`): an HPA-imitation warm start fine-tuned with PPO. It is the first FlexaScale policy that beats the HPA-like rule in simulation (+0.064 ± 0.031 reward per step, 3.4 points fewer SLO violations, paired test episodes). It does not beat a better-tuned threshold rule there. On the live shop it does **not** beat native HPA: over 12 pairs (six scenarios × two repeats) it used +8% replica-hours, with p95 +6.5% and failures +0.5 pp. Most per-scenario differences flip sign between repeats (§8.1). v4 and v3 results are kept in §8.2–8.3.

Since then: the shop grew from 7 to **16 services** (Helm chart 1.1.0), a v6 policy trained in a simulator matching the live control loop also lost to native HPA in simulation (`docs/POLICY_V6.md` §4), and **Auto mode** was added: explainable, logged per-service rules decide whether FlexaScale or native HPA owns each service (`docs/POLICY_V6.md` §5). In the live HPA-vs-Auto benchmark (3 repeats × 6 scenarios, §8.0) **Auto used 3.9% fewer replica-hours than default native HPA (95% CI −6.5 … −1.3) with no measurable latency or failure penalty**. It is the only FlexaScale configuration that beats native HPA, and its saving comes from scaling down sooner, not from a better learned policy. A native HPA tuned to a 60 s scale-down window also beats default HPA on cost, by less (−1.4%, 12 pairs), and the indirect comparison does not show Auto saving more than it (−2.5 points, 95% CI −5.4 … +0.3). The dashboard was rebuilt as a control center (Overview, Live lab, Comparison, Auto mode, Models). It shows only measured values and labels a benchmark verdict as preliminary below 6 pairs. Validity work on 2026-10-26: every run's host conditions (battery, CPU used outside Kubernetes) are now checked with a rule that uses no result (`scripts/check_host_load.py`). This withdrew one tuned-HPA comparison and added battery caveats to the v5 and Auto results (§8). The Helm chart's live, rollback and uninstall paths were tested in-cluster for the first time, and a defect that left HPAs frozen was fixed (defect 19, chart 0.4.1).

## 2. What already existed (audited)

Shopping app (7 FastAPI services, React frontend, PostgreSQL, Helm chart, HPAs), Prometheus/Grafana, Locust journeys, Alibaba v2021 preprocessing, Gymnasium simulator, PyG GNN encoder, SB3 PPO training, safety coordinator / lock / HPA manager, operator, legacy FastAPI dashboard, benchmark scripts, 154 passing tests.

## 3. Defects found in the audit (all fixed unless noted)

| # | Defect | Impact | Fix |
| :--- | :--- | :--- | :--- |
| 1 | Processed dataset stored CPU/memory as **fractions**; schema, simulator and live code use percent | Original model trained on near-zero CPU | `scripts/fix_dataset_units.py` (idempotent, provenance), builder fixed, model retrained |
| 2 | For ≠ 4 services the operator used the GNN `node_policy_head`, **never trained by PPO** | Earlier "FlexaScale (PPO+GNN)" live benchmark ran on random weights | `rl/policy_runtime.py`: trained weights on neighbourhood windows; old report withdrawn |
| 3 | Missing latency synthesised from CPU and reported as OK; request rate faked from network bytes | Fabricated telemetry | Removed; reported as missing |
| 4 | Live CPU measured as % of one core, HPA uses % of request | Policy and HPA saw different signals | CPU % of request everywhere |
| 5 | HPA fallback reset bounds to hardcoded 1–10; HPAs found by `-hpa` name | Wrong restore, broken on other apps | Original bounds stored in HPA annotations; lookup by `scaleTargetRef` |
| 6 | Shopping service names hardcoded in safety config, discovery mocks and graph inference | Not application-agnostic | Moved to `config/apps/shopping.yaml` |
| 7 | Ownership lock was in-memory per process | Two controller processes could both scale | Kubernetes `Lease` with optimistic concurrency |
| 8 | Helm chart: `--live` by default, ClusterRole with cluster-wide write, operator image never built | Unsafe, uninstallable | Chart 0.2.0: observe default, namespaced Role, writes only in live, Dockerfile |
| 9 | Original reward had no resource-cost term | Policy learned to scale up | Cost term (v3) did **not** fix it. v4 redesign (simulator, unit-free inputs, focal objective) reduced it; v5 (imitation warm start) removed it. See §6, `docs/POLICY_V4.md`, `docs/POLICY_V5.md` |
| 10 | No app-wide replica cap | A live run exhausted the 6 GiB node (§7) | `max_total_replicas` budget guard |
| 11 | Legacy API: wildcard CORS on mutation endpoints | Any web page could trigger actions | Lab server is same-origin, 127.0.0.1, validated inputs; legacy API disabled in chart |
| 12 | Frontend nginx resolves upstream at boot | CrashLoopBackOff after cluster restart, self-heals | Fixed in frontend 1.1: runtime `resolver` from the pod's resolv.conf, upstream in a variable |
| 13 | Each downstream call in order/cart/gateway created its own HTTP client | order-service OOM-killed under load (16-service shop) | One shared client per process (images 1.2) |
| 14 | `GET /api/orders/user/{id}` returned **every** order of the user; the two load-test users had 43k orders | order-service OOM-killed in almost every run of the first HPA-vs-Auto batch, in both arms. All 36 runs invalidated (`reports/experiments_invalid/README.md`) | order-service 1.3: newest 20 orders (`limit` ≤ 100); test `test_user_order_history_is_bounded` |
| 15 | Host clock 5.5 h fast (NTP off, RTC in local time) | Prometheus rejected samples, service-account tokens failed, ingress routed to a deleted pod; 35 of 36 runs of the first Auto batch refused | NTP enabled, RTC in UTC, system workloads and Minikube restarted; documented |
| 16 | The live API reported a service as FlexaScale-owned whenever its HPA was frozen | During the lab's pre-run reset (HPAs held at their minimum, lease free) a native-HPA run showed "FlexaScale ×16" | FlexaScale ownership requires the Lease. Otherwise the owner is `reset` (dashboard: "Reset hold"), in both `lab/experiments.py` and the dashboard |
| 17 | Grafana CPU and memory panels listed the 7 original containers by name | The 9 new services were missing | Panels select every container in the namespace (except PostgreSQL) |
| 18 | `docker-compose.yml` had only the 7 original services | Checkout (which requires shipping and fraud) failed under Compose | All 16 services added; `docker compose config` validates |
| 19 | Helm chart 0.4.0: `helm rollback` (live → observe) and `helm uninstall` left every HPA frozen and the Lease held. Helm downgraded or deleted the operator's Role while replacing its pod, so the SIGTERM hand-back had no permissions left (found in the in-cluster test, `logs/helm_verify_before_fix.out`) | After a rollback or uninstall neither HPA nor FlexaScale would scale the application | Chart 0.4.1: a pre-upgrade / pre-rollback / pre-delete hook Job scales the operator to 0 and waits while the old Role still exists; verified in-cluster (§9) and by render tests (`tests/test_helm_chart.py`) |

## 4. What was changed / added

* **Product core** (under `src/flexascale/`): `config/app_policy.py`, `discovery/workloads.py`, `metrics/workload_metrics.py`, `rl/policy_runtime.py`, `operator/app_operator.py`, `safety/lease.py`, HPA manager rewrite, `k8s/kube.py`.
* **Lab**: `lab/experiments.py`, `lab/server.py`, `lab/processes.py`, `lab/procctl.py`, `evaluation/cost.py`; React/TypeScript/Vite/Tailwind UI in `dashboard/`, built into `src/flexascale/lab/static/`.
* **Workloads**: `load-testing/scenarios.py` (6 scenarios); second application `examples/bookstore/`.
* **Scripts**: `start_review.sh`, `start_demo.sh`, `stop_review.sh`, `review_status.sh`, `run_lab.py`, `run_lab_experiments.py`, `build_live_report.py`, `evaluate_policies.py`, `data_quality_report.py`, `fix_dataset_units.py`; Makefile targets; teardown `--delete` now asks for confirmation.
* **Models**: `models/flexascale_v2` (original reward), `models/flexascale_v3` (cost-aware reward), `models/flexascale_v4` (dependency-aware simulator; selected from 8 candidates on validation services), `models/flexascale_v5` (HPA-imitation warm start + PPO, **deployed**; selected from 12 candidates on validation services), all with model cards. Training attempts A, B and the interrupted first run of C are kept under `models/flexascale_v4_*`. Legacy `models/best_model` kept untouched.
* **Docs**: RUNNING.md quick start + §U–W (inaccurate checklist items corrected), `docs/FINAL_*.md`, this report.

## 5. Tests actually executed

| Check | Result | Status |
| :--- | :--- | :--- |
| `pytest tests` (framework + shopping app) | **296 passed**, 0 failed (was 154; rerun 2026-10-26 20:55 after the host-load check, the Welch comparison, Helm chart tests and the hand-back hook) | VERIFIED |
| New tests: policy validation, discovery rules, HPA freeze/restore of original bounds, Lease exclusion/takeover/conflict, telemetry attribution, cost maths, policy runtime for 1–9 services (incl. untrained head set to NaN), operator observe/live/guards/lease loss/budget, process safety, lab API, comparability, scenarios, script syntax, teardown confirmation | 77 tests | VERIFIED |
| `helm lint` both charts; render observe/live/invalid mode | pass; invalid mode fails with message | VERIFIED |
| `bash -n` on all review scripts | pass | VERIFIED |
| Dashboard `tsc` strict + `vite build` | pass | VERIFIED |

One test failed once under extreme host load (process stop timeout) and exposed a real liveness race in `processes.py`, which was fixed. Three consecutive runs then passed.

## 6. Model and inference verification

| Item | Evidence | Status |
| :--- | :--- | :--- |
| Saved models load; observation/action spaces | v5: Box(20) unit-free (observation version 2, same as v4), MultiDiscrete([3]*4), GNNExtractor, 501,760 timesteps after the warm start; also loads inside the 0.4.0 image | VERIFIED |
| Model actually trained | Model card + eval logs (5 checkpoints); held-out test differs strongly from random/hold | VERIFIED |
| Live inference uses the configured trained model | Operator status/decision logs record model path, sha256, `ppo_direct` / `ppo_neighborhood` | VERIFIED |
| Feature units/order match training | Same 5 fields in percent; clipped to training bounds; `clipped` recorded per decision | VERIFIED |
| Node order ↔ Deployment mapping | Sorted names, order-independence test, per-decision window logged | VERIFIED |
| Train/val/test separation | v4/v5: split by service (train/val/test services disjoint); candidate chosen on val, test run once. v5's test reuses v4's test services with fresh seeds (disclosed) | VERIFIED |
| Reward in code matches docs | v2/v3: `simulator/flexascale_env.py::_compute_reward` = docs/FINAL_PROJECT_SUMMARY.md §6; v4: `simulator/dependency_env.py::_compute_reward` = docs/POLICY_V4.md §3 | VERIFIED |
| Policy quality (simulation, 200 paired test episodes) | v5 (300 test-service episodes, `reports/simulation_evaluation_v5.md`): reward −0.274 vs HPA rule −0.338 vs tuned rule 77/45 −0.227; SLO violations 37.9% vs 41.4% vs 37.4%; replicas 3.26 vs 2.81 vs 3.12. v4: replicas 4.81 | VERIFIED (beats HPA rule; below tuned threshold rule) |
| Missing metrics / model failure handled safely | Tests + live: no action on missing CPU; live refused without model | VERIFIED |

## 7. Live verification on the cluster

| Item | Evidence | Status |
| :--- | :--- | :--- |
| All shop services, frontend, PostgreSQL, Prometheus, Grafana healthy | `start_review.sh` readiness, `review_status.sh` | VERIFIED |
| Prometheus targets; telemetry maps to the right Deployment | 14 targets up; per-Deployment CPU/mem/rps/latency/p95 in dashboard | VERIFIED |
| Observe mode changes nothing | Decision log `applied: false`; HPAs unchanged | VERIFIED |
| Live scaling by the trained policy | e.g. `cart-service: FlexaScale requested 3 -> 4 (confidence 0.65, ppo_neighborhood)` → replica change → 4/4 ready | VERIFIED |
| Lease + HPA freeze; never two controllers | Lease held only during FlexaScale runs; HPAs pinned min=max before each scale; restore to 1–10 | VERIFIED |
| Cleanup restores safe state | `cleanup.safe = true` on every run with a reachable API; `stop_review.sh` verifies | VERIFIED |
| Recovery when the API was down | 7 HPAs left frozen, reported NOT SAFE, restored from annotations by `procctl safe-state` | VERIFIED |
| Dashboard shows real data | Screenshot check; values match Prometheus queries | VERIFIED |
| Locust scenarios | All 6 smoke-tested against the shop | VERIFIED |
| Startup twice → no duplicates | Second run: "already running (reused)"; one process each | VERIFIED |
| Second application (5-service bookstore) | Observe and live operation with the same code and model (see §8) | VERIFIED (functional; no benchmark) |
| In-cluster Helm install of the operator | Upgraded release running in observe mode with read-only RBAC | VERIFIED (§9) |

**Capacity incident.** At 40 users a FlexaScale run reached 45 replicas, exhausting the 6 GiB node: 42.6% failures, API server down for about 3 min. That run and its pair are excluded from comparisons (unsettled start, resource exhaustion). The fixes are in §3 (#10) and the lab.

## 8. Benchmark and cost validation

### 8.0 Auto mode vs native HPA, 2026-10-26 (16-service shop): VERIFIED

Clean batch 04:35–12:18 (`logs/live_auto_batch_v2.out`): 3 repeats × 6 scenarios × {HPA, Auto}, 25 users, 300 s, comparable start, order-service 1.3. All 36 runs completed with cleanup verified safe, with no app container restarts and no exclusions. Auto − HPA over 18 pairs (mean, 95% interval):

| Replica-hours | Estimated cost | p95 latency | Failure rate | Throughput |
| ---: | ---: | ---: | ---: | ---: |
| −3.9% (−6.5 … −1.3) | −4.0% (−6.6 … −1.3) | +2.8% (−8.0 … +13.6) | −0.07 pp (−0.12 … −0.02) | +0.7% (−0.3 … +1.7) |

**Verdict under the rule fixed in advance (`docs/POLICY_V6.md` §3.1): Auto beats default native HPA on cost.** Replica-hours were lower in 16 of 18 pairs.

The saving comes from scaling down. Default HPA made 0 scale-downs in all 18 runs, because its 300 s stabilisation window outlasts a run, while FlexaScale made 56 scale-downs inside Auto. The result holds when each Auto run is paired with the *following* HPA run instead (−5.1%, all 12 pairs negative).

Repeat 3 was weaker (gradual_ramp +8.8%: FlexaScale over-scaled once, in a run mostly on battery), so this is a modest, real effect, not a large one. The laptop ran on battery (CPU about 1 GHz) from 11:52:05: 218 s of the 314 s load window of that gradual_ramp Auto run (its HPA arm ran on AC) and the whole last pair. Both pairs are kept, as the pre-registered rule requires; without them the result is −4.9% (CI −7.2 … −2.6, 16 pairs). Apart from the battery period, no run of the batch had more than 1.64 cores of host CPU in use outside Kubernetes (`reports/host_load_by_run.csv`, `scripts/check_host_load.py`). Details: `docs/POLICY_V6.md` §5.1, `reports/live_benchmark_report.md`.

**Tuned-HPA reference (`docs/POLICY_V6.md` §5.2): VERIFIED (12 pairs, 6 scenarios).** The `hpa_fast` controller works: unit and lab tests pass, and live the 60 s window was set on all 16 HPAs and restored after every run (checked on the cluster after the batch: no window left, no FlexaScale annotation, lease free). Excluded under the host-load criterion: the runs made on battery, three pairs that overlapped other jobs on the laptop using up to 12 extra cores (among them the single earlier AC pair, −12.5%, which is withdrawn), and the steady_browsing rerun, which ran on battery (19:25–19:34) and is missing. Result: tuned HPA − default HPA replica-hours **−1.4% (95% CI −2.6 … −0.2)**, p95 +5.8% (−5.5 … +17.1), failures +0.05 pp (−0.02 … +0.12), throughput −2.3% (−4.6 … −0.0): "beats HPA on cost" under §3.1, with 19 scale-downs against 0. Auto − tuned HPA (indirect, Welch): replica-hours −2.5 points (−5.4 … +0.3), **no difference shown**; failures −0.13 pp (−0.21 … −0.04) in Auto's favour.

### 8.1 v5 (deployed), 2026-10-25

Six scenarios × two controllers × **two repeats**, 25 peak users, 300 s each, alternating HPA and FlexaScale per scenario, comparable starts. All 24 counted runs completed, all cleanups were verified safe, and all 12 pairs passed the comparability checks. Repeat 2 was hit by two host incidents: OOM kills plus a dead Prometheus port-forward at 04:57, then a shutdown at about 05:09 when the laptop's battery ran out (it had been on battery since 02:04, so 5 of the 12 counted pairs ran on battery in both arms; see "What this shows" below). The affected pairs were rerun whole after a healthy restart, under a rule fixed before any rerun result was seen. The invalid runs and reasons are in `reports/experiments_invalid/README.md`.

Changes are v5 relative to HPA in the same scenario and repeat (rep 1 / rep 2):

| Scenario | Δ p95 % | Δ failures pp | Δ throughput % | Δ replica-h % |
| :--- | ---: | ---: | ---: | ---: |
| checkout_heavy | +22.4 / −26.2 | +0.4 / +4.5 | −32.3 / +9.3 | −4.8 / +1.2 |
| flash_sale | −4.2 / +0.0 | +1.1 / −4.2 | +5.3 / +10.7 | +11.2 / +24.3 |
| gradual_ramp | +43.5 / +83.3 | +0.7 / −0.7 | −7.9 / −7.5 | +5.9 / +26.6 |
| payment_degradation | −15.2 / +32.3 | +2.5 / −0.0 | +1.7 / +2.8 | +7.3 / +6.2 |
| steady_browsing | +0.0 / +6.2 | −0.8 / +0.5 | +0.2 / −2.7 | +2.0 / +20.4 |
| traffic_drop | −35.1 / −29.4 | +1.8 / +0.1 | +11.4 / +8.8 | +6.2 / −10.9 |

**What this shows.** Averaged over the 12 pairs, v5 used +8.0% replica-hours, with p95 +6.5%, throughput −0.0% and failure rate +0.5 pp relative to HPA. **v5 does not beat native HPA live.** Five of the 12 pairs (repeat 1 payment_degradation, flash_sale, gradual_ramp, traffic_drop and repeat 2 steady_browsing, 2026-10-25 02:00–04:30) ran on battery in both arms, found afterwards in the laptop's charge history (`reports/host_load_by_run.csv`); on the 7 AC-power pairs v5 used +6.4% replica-hours (95% CI −6.7 … +19.5), so the direction is the same but the interval includes 0 ("on par" under the §3.1 rule instead of "worse"). Only a few effects keep their direction in both repeats. v5 is better on traffic_drop (p95 −35% / −29%) and worse on gradual_ramp (p95 +44% / +83%, because it scales up later on a slow ramp). It uses more replicas on flash_sale and payment_degradation. Everything else flips sign between repeats, and HPA alone varies by as much (checkout_heavy failures 31.4% then 27.5%). The simulator gain over the HPA rule did not carry over to the cluster.

### 8.2 v4 (previous model), 2026-10-24

Six scenarios × two controllers, 25 peak users, 300 s each, alternating HPA and FlexaScale per scenario, comparable starts, sleep inhibited on the host. All 12 runs completed, all cleanups were verified safe, and all 6 pairs passed the comparability checks. One HPA run was invalidated by a host suspend and rerun; it is kept in `reports/experiments_invalid/` with the reason.

| Scenario | Throughput HPA → FS | p95 ms HPA → FS | Failures % HPA → FS | Replica-hours HPA → FS | Cost proxy Δ |
| :--- | ---: | ---: | ---: | ---: | ---: |
| steady_browsing | 11.36 → 11.02 | 1000 → 1500 | 3.30 → 3.32 | 1.194 → 1.238 | +4% |
| checkout_heavy | 8.50 → 8.62 | 6000 → 6000 | 30.19 → 18.90 | 1.414 → 1.380 | −2% |
| payment_degradation | 9.03 → 10.20 | 4100 → 2100 | 21.85 → 32.15 | 1.101 → 1.212 | +10% |
| flash_sale | 8.39 → 9.48 | 2600 → 1700 | 3.05 → 2.46 | 1.148 → 1.397 | +22% |
| gradual_ramp | 7.07 → 7.02 | 2200 → 3100 | 7.02 → 7.03 | 1.106 → 0.984 | −11% |
| traffic_drop | 4.72 → 4.86 | 5000 → 3900 | 7.41 → 5.80 | 1.477 → 1.687 | +14% |

**What this shows.** Averaged over the six pairs, v4 used +6% replica-hours, with p95 −2.4%, throughput +4.5% and failure rate −0.5 pp relative to HPA. Three of the six pairs touched a battery period (2026-10-24 18:28–18:51 and from 19:07, laptop charge history): gradual_ramp with only its HPA arm on battery, traffic_drop with both arms, flash_sale with 4 s of its FlexaScale arm. On the 3 AC-power pairs v4 used +3.8% replica-hours (95% CI −11.7 … +19.3). The per-scenario differences go both ways and are large: p95 ranged from −49% to +50%, and failures from −11 pp to +10 pp. With one run per arm these cannot be separated from run-to-run noise, so **v4 is roughly on par with HPA in cost, with no established latency or reliability benefit**. The clear change is relative to v3, which used 58–98% more replica-hours than HPA in the same setup (§8.3).

### 8.3 v3, 2026-10-23

Three scenarios × two controllers, 25 peak users, 300 s each, comparable starts (all services at 1 replica at controller handoff), run through the dashboard's own API (`scripts/run_lab_experiments.py`). All 6 runs completed, all cleanups were verified safe, and all 3 pairs passed the comparability checks. Full tables: `reports/live_benchmark_report.md`; per-run CSV: `reports/live_benchmark_summary.csv`; raw data: `reports/experiments/<run>/`.

| Scenario | Throughput HPA → FS | p95 ms HPA → FS | Failures % HPA → FS | Replica-hours HPA → FS | Cost proxy Δ |
| :--- | ---: | ---: | ---: | ---: | ---: |
| flash_sale | 10.44 → 8.77 req/s | 1400 → 2100 | 2.07 → 2.50 | 1.246 → 2.205 | **+77%** |
| gradual_ramp | 7.05 → 6.84 | 3000 → 3400 | 6.45 → 6.96 | 1.110 → 2.197 | **+98%** |
| traffic_drop | 5.50 → 5.44 | 1900 → 2100 | 6.75 → 7.35 | 1.193 → 1.879 | **+58%** |

**What the cost comparison shows.** FlexaScale allocated 58–98% more resources (replica-hours, requested vCPU-hours, proxy cost) than native HPA, while latency, throughput and failure rate were equal or worse. Its CPU allocation efficiency was 38–41% against HPA's 56–70%. This is an over-provisioning *cost increase*, not a saving. At the time (v3) no prices were configured for the shop, so these v3 figures are a unitless proxy and not money. Since 2026-10-26 the shop policy carries AWS Fargate on-demand list prices, so §8.0 reports an estimated cost (still not a bill).

| Item | Status |
| :--- | :--- |
| Reported metrics reproducible from raw data | VERIFIED (`build_live_report.py` recomputes from `run.json`; Locust final vs sampled totals in CSV) |
| Comparable runs (same scenario/users/duration, settled start) | VERIFIED (Auto: 18 pairs; v5: 12; v4: 6; v3: 3) |
| Steady browsing, checkout-heavy, payment-degradation live comparison | VERIFIED with v5 (§8.1) and v4 (§8.2); not run with v3 |
| Statistical significance | PARTIALLY VERIFIED: 95% t-intervals of the mean paired difference, pooled over scenarios (Auto 18 pairs: replica-hours interval below 0; v5 12 pairs: above 0). Single-node Minikube and 2–3 pairs per scenario, so per-scenario effects are not established; v3/v4 had one run per arm |
| Withdrawn: `reports/shopping_benchmark_report.md` (untrained head) | marked withdrawn in place |
| Second application, live FlexaScale run (5-service bookstore, 120 s, preliminary) | VERIFIED: lease, freeze of `*-autoscaler` HPAs via scaleTargetRef, direct scaling of no-HPA services, budget respected (peak 15), cleanup safe. The earlier gap (no-HPA services kept their raised count) is fixed. The original count is recorded in `flexascale.io/original-replicas` before the first scale and restored on shutdown. Verified 2026-10-24 on the bookstore's `cart` (scaled 1 → 3 with the real `HPAManager`, restored to 1, annotation cleared) and in a 120 s v4 run, where shutdown cleared the markers on `cart`/`pricing`. v4 itself made no scale changes in that run. |

## 9. Installation and portability

| Item | Evidence | Status |
| :--- | :--- | :--- |
| Operator image | `docker build -f deploy/flexascale/Dockerfile -t flexascale:0.4.0 .` (CPU-only torch 2.14.1, NumPy 2.2.6, SB3 2.9.0); v5 model loads inside the image (Box(20), MultiDiscrete([3]*4), 501,760 steps) and includes the replica-restore code; policy validates | VERIFIED |
| Helm install/upgrade on Minikube | Existing broken release `flexascale` (chart 0.1.0, ImagePullBackOff, `--live` default, cluster-wide write ClusterRole) upgraded in place to 0.2.0, then to 0.3.0 on 2026-10-24 (v4 model, `scale_up_cooldown_seconds: 30`, `patch deployments` in live mode only), then to 0.4.0 on 2026-10-25 (v5 model, no other change), then to 0.4.1 on 2026-10-26 (hand-back hook, defect 19; revision 7). The selector was kept compatible because Deployment selectors are immutable (found during the first upgrade). Old ClusterRole removed | VERIFIED |
| Observation-only default | Decision log in the 0.4.0 pod: `observe`, v5 model path, `ppo_neighborhood`, `applied: false`, note "observation only: no cluster change"; HPAs unchanged (1–10); no lease held | VERIFIED |
| Least-privilege RBAC (observe) | `kubectl auth can-i` as the operator SA: list deployments/hpa in the target namespace **yes**; patch hpa, patch deployments, update deployments/scale, create leases **no**; list deployments cluster-wide **no** (checked on 0.3.0; 0.4.0 changes only the image and model path) | VERIFIED |
| Live mode in-cluster | Throwaway release `fsverify` on the bookstore, 2026-10-26 (`logs/helm_verify.out`): install in observe (no write permission), upgrade to live; the operator took the Lease within 3–6 s, froze all 3 HPAs (min = max, original bounds stored as annotations) and marked the 2 HPA-less Deployments with their original replica count. Live RBAC (`kubectl auth can-i`): patch HPAs, update/patch `deployments --subresource=scale`, create leases in the application namespace **yes**; delete deployments, read secrets, scale in another namespace **no** | VERIFIED |
| Rollback / uninstall | With chart 0.4.0 both left the HPAs frozen and the Lease held (defect 19). With chart 0.4.1 (hand-back hook): `helm rollback` live → observe restored all 3 HPAs to 1–5, cleared every marker and released the Lease within 3 s; `helm upgrade` back to live re-acquired it; `helm uninstall` restored everything again, released the Lease within 3 s and left no RBAC in the application namespace. The main release `flexascale` was then upgraded in place to 0.4.1 (revision 7; the hook ran, observe mode kept) | VERIFIED |
| Portability (2nd app) | Bookstore: same operator and model, observe and live, no code change | VERIFIED |

The in-cluster operator (chart 0.4.1, image 0.4.0) was left running in **observe** mode targeting `flexascale-apps` (~384 Mi request). It does not hold the lease, so it does not interfere with the lab. To remove it: `helm uninstall flexascale -n flexascale-system` or `kubectl -n flexascale-system scale deploy/flexascale-operator --replicas=0`.

## 10. Remaining limitations

* The learned policy (v5) beats the HPA-like rule in simulation but not a better-tuned threshold rule, and it does not beat native HPA live (+8% replica-hours, p95 +6.5%, over 12 pairs; +6.4% on the 7 pairs run on AC power). It is slow on gradual ramps. The dependency-graph input has only a borderline effect in the simulator (ablation +0.016 ± 0.015 reward).
* The GNN was trained on a synthetic 4-node chain, not real call graphs. N ≠ 4 uses untrained-for neighbourhood windows.
* Two runs per scenario and controller for v5 (one for v3/v4); single-node Minikube; run-to-run noise is as large as most effects; indicative only.
* Deployments without an HPA are restored to their original count only on operator shutdown. A mid-run handback (low confidence, lease loss) keeps the current count, because nothing would catch a drop under load.
* The host laptop auto-suspends; long benchmark batches must run under `systemd-inhibit` (one run was lost to a suspend; in the v5 batch the host also went down once, because its battery ran out (charge history: 0% at 05:07 on 25 October), and the affected pairs were rerun).
* Confidence is uncalibrated; handing back to HPA causes churn.
* The policy files hold the 16-service shop to 48 replicas because the Minikube node is a 9 GiB container that advertises the host's 16 GB as allocatable. Start Minikube with matching `--memory` or keep the budget.
* All live batches before 2026-10-26 04:35, including the v5 HPA-vs-FlexaScale batch, ran with the unbounded order-history endpoint (defect 14). Both arms were exposed, but later runs more than earlier ones. Prometheus history from that time is gone, so the exposure cannot be measured. The v5 live result carries this caveat.
* Costs are estimates from AWS Fargate on-demand list prices applied to allocated CPU and memory, not cloud bills.
* Auto's saving was measured against *default* native HPA (300 s scale-down window). A native HPA tuned to a 60 s window saves 1.4% (12 pairs, §8.0), and Auto is not shown to save more than it (indirect comparison, −2.5 points, CI −5.4 … +0.3). Other HPA settings (scale-down policies, CPU targets) were not tested, so Auto is not shown to beat a well-tuned HPA.
* Live benchmarks need AC power and an otherwise idle laptop: on battery it runs at about 1 GHz and every service is about 4× slower, and other jobs compete for the same CPUs. Checked afterwards (`scripts/check_host_load.py`, `reports/host_load_by_run.csv`): battery periods touched 2 of the 18 Auto pairs, 5 of the 12 v5 pairs and 3 of the 6 v4 pairs (kept under their batches' rules, with AC-only results reported), and other jobs on the laptop affected three tuned-HPA pairs (excluded and rerun). Host CPU from before the 2026-10-25 Minikube restart is no longer in Prometheus, so earlier runs can only be checked for battery.

## 11. Exact demonstration commands

```bash
./scripts/start_demo.sh          # readiness report; dashboard http://127.0.0.1:8090/ , shop http://192.168.49.2/
./scripts/review_status.sh       # anytime
./scripts/stop_review.sh         # safe shutdown (restores HPAs, verifies no lease)
```

## 12. Submission checklist

Before committing (about 5 minutes; none of these changes the cluster):

```bash
.venv/bin/python -m pytest -q                       # all tests pass
helm lint helm/flexascale charts/shopping-app      # 2 charts linted, 0 failed
./scripts/start_review.sh --check                   # preflight only
.venv/bin/python scripts/build_live_report.py      # rebuilds the report from the raw runs; numbers must not change
```

Commit with `git add -A` and then `git commit`, **not** `git commit -a`: many required files are new and untracked, and `commit -a` would leave them out, so a fresh clone would not run. They include:

* source: `src/flexascale/lab/benchmark.py`, `src/flexascale/operator/auto_mode.py`, `src/flexascale/rl/imitation.py`, `src/flexascale/simulator/control_env.py`, the Helm hook `helm/flexascale/templates/handback-hook.yaml`, and the rebuilt dashboard bundle in `src/flexascale/lab/static/assets/`;
* the nine services added to the shop, `apps/services/{fraud,notification,pricing,promotion,recommendation,review,search,shipping,wishlist}-service/`;
* dashboard sources `dashboard/src/pages/`, `dashboard/src/Topology.tsx`, `dashboard/src/ui.tsx`;
* models `models/flexascale_v5/` (deployed) and `models/flexascale_v6/`;
* `docs/POLICY_V5.md`, `docs/POLICY_V6.md`, the new scripts (`run_live_batch.sh`, `check_host_load.py`, `check_auto_run_order.py`, `evaluate_v5.py`, `evaluate_v6.py`, `train_v5.sh`, `train_v6.sh`, `build_shop_images.sh`) and tests;
* evidence: `reports/experiments/`, `reports/experiments_invalid/`, `reports/experiments_demo/`, `reports/host_load_by_run.csv`, `reports/simulation_evaluation_v5.*`, `reports/simulation_evaluation_v6.*` and `logs/`.

That is about 320 MB of new files. No single file is larger than 1 MB, so Git LFS is not needed. The deletions in `git status` are intended: `locust/locustfile.py` (moved to `load-testing/`), `scratch/test_multidiscrete.py` and the previous dashboard bundle. `.runtime/`, `.venv/` and `node_modules/` are ignored and must not be committed.
