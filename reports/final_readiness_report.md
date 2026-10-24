# FlexaScale Final Readiness Report

Date: 2026-10-23, updated 2026-10-24 (v4 policy, six-scenario live benchmark, replica restore for HPA-less Deployments, chart/image 0.3.0). Environment: Fedora 43, Docker, Minikube profile `flexascale` (Kubernetes v1.31, single node, a Docker container capped at 6 GiB RAM), Python 3.14 venv.

Status keys: **VERIFIED** (executed and checked here), **PARTIALLY VERIFIED**, **NOT VERIFIED**, **BLOCKED**.

## 1. Overall readiness

**Ready for the presentation as a working, safe, application-agnostic autoscaling *system*, with an honestly reported, mixed result for the learned *policy*.**

The one-command startup, live dashboard, comparable HPA-vs-FlexaScale experiments, ownership safety and cleanup are all verified on the live cluster. The deployed policy is now v4 (`docs/POLICY_V4.md`). It removed v3's "always scale up" collapse: on the live shop it used −11% to +22% of HPA's replica-hours (v3: +58% to +98%). It still does not beat native HPA. In simulation it used 61% more replicas than the HPA rule for 3 points fewer SLO violations. Live results were mixed across six scenarios, with one run per arm (§8).

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
| 9 | Original reward had no resource-cost term | Policy learned to scale up | Cost term (v3) did **not** fix it. v4 redesign (simulator, unit-free inputs, focal objective) reduced it; see §6 and `docs/POLICY_V4.md` |
| 10 | No app-wide replica cap | A live run exhausted the 6 GiB node (§7) | `max_total_replicas` budget guard |
| 11 | Legacy API: wildcard CORS on mutation endpoints | Any web page could trigger actions | Lab server is same-origin, 127.0.0.1, validated inputs; legacy API disabled in chart |
| 12 | Frontend nginx resolves upstream at boot | CrashLoopBackOff after cluster restart, self-heals | **Not fixed** (needs image rebuild); documented workaround |

## 4. What was changed / added

* **Product core**: `config/app_policy.py`, `discovery/workloads.py`, `metrics/workload_metrics.py`, `rl/policy_runtime.py`, `operator/app_operator.py`, `safety/lease.py`, HPA manager rewrite, `k8s/kube.py`.
* **Lab**: `lab/experiments.py`, `lab/server.py`, `lab/processes.py`, `lab/procctl.py`, `evaluation/cost.py`; React/TypeScript/Vite/Tailwind UI in `dashboard/`, built into `src/flexascale/lab/static/`.
* **Workloads**: `load-testing/scenarios.py` (6 scenarios); second application `examples/bookstore/`.
* **Scripts**: `start_review.sh`, `start_demo.sh`, `stop_review.sh`, `review_status.sh`, `run_lab.py`, `run_lab_experiments.py`, `build_live_report.py`, `evaluate_policies.py`, `data_quality_report.py`, `fix_dataset_units.py`; Makefile targets; teardown `--delete` now asks for confirmation.
* **Models**: `models/flexascale_v2` (original reward), `models/flexascale_v3` (cost-aware reward), `models/flexascale_v4` (dependency-aware simulator, **deployed**; selected from 8 candidates on validation services), all with model cards. Training attempts A, B and the interrupted first run of C are kept under `models/flexascale_v4_*`. Legacy `models/best_model` kept untouched.
* **Docs**: RUNNING.md quick start + §U–W (inaccurate checklist items corrected), `docs/FINAL_*.md`, this report.

## 5. Tests actually executed

| Check | Result | Status |
| :--- | :--- | :--- |
| `pytest tests` (framework + shopping app) | **247 passed**, 0 failed (was 154) | VERIFIED |
| New tests: policy validation, discovery rules, HPA freeze/restore of original bounds, Lease exclusion/takeover/conflict, telemetry attribution, cost maths, policy runtime for 1–9 services (incl. untrained head set to NaN), operator observe/live/guards/lease loss/budget, process safety, lab API, comparability, scenarios, script syntax, teardown confirmation | 77 tests | VERIFIED |
| `helm lint` both charts; render observe/live/invalid mode | pass; invalid mode fails with message | VERIFIED |
| `bash -n` on all review scripts | pass | VERIFIED |
| Dashboard `tsc` strict + `vite build` | pass | VERIFIED |

One test failed once under extreme host load (process stop timeout) and exposed a real liveness race in `processes.py`, which was fixed. Three consecutive runs then passed.

## 6. Model and inference verification

| Item | Evidence | Status |
| :--- | :--- | :--- |
| Saved models load; observation/action spaces | v4: Box(20) unit-free (observation version 2), MultiDiscrete([3]*4), GNNExtractor, 1,000,000 timesteps; also loads inside the 0.3.0 image | VERIFIED |
| Model actually trained | Model card + eval logs (5 checkpoints); held-out test differs strongly from random/hold | VERIFIED |
| Live inference uses the configured trained model | Operator status/decision logs record model path, sha256, `ppo_direct` / `ppo_neighborhood` | VERIFIED |
| Feature units/order match training | Same 5 fields in percent; clipped to training bounds; `clipped` recorded per decision | VERIFIED |
| Node order ↔ Deployment mapping | Sorted names, order-independence test, per-decision window logged | VERIFIED |
| Train/val/test separation | v4: split by service (train/val/test services disjoint); candidate chosen on val, test run once | VERIFIED |
| Reward in code matches docs | v2/v3: `simulator/flexascale_env.py::_compute_reward` = docs/FINAL_PROJECT_SUMMARY.md §6; v4: `simulator/dependency_env.py::_compute_reward` = docs/POLICY_V4.md §3 | VERIFIED |
| Policy quality (simulation, 200 paired test episodes) | v4 (300 test-service episodes, `reports/simulation_evaluation_v4.md`): reward −0.425 vs HPA rule −0.288, SLO violations 37.6% vs 40.7%, **replicas 4.54 vs 2.82** (v3: 9.54) | VERIFIED (over-provisions less than v3; below HPA rule on reward) |
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

### 8.1 v4 (deployed), 2026-10-24

Six scenarios × two controllers, 25 peak users, 300 s each, alternating HPA and FlexaScale per scenario, comparable starts, sleep inhibited on the host. All 12 runs completed, all cleanups were verified safe, and all 6 pairs passed the comparability checks. One HPA run was invalidated by a host suspend and rerun; it is kept in `reports/experiments_invalid/` with the reason.

| Scenario | Throughput HPA → FS | p95 ms HPA → FS | Failures % HPA → FS | Replica-hours HPA → FS | Cost proxy Δ |
| :--- | ---: | ---: | ---: | ---: | ---: |
| steady_browsing | 11.36 → 11.02 | 1000 → 1500 | 3.30 → 3.32 | 1.194 → 1.238 | +4% |
| checkout_heavy | 8.50 → 8.62 | 6000 → 6000 | 30.19 → 18.90 | 1.414 → 1.380 | −2% |
| payment_degradation | 9.03 → 10.20 | 4100 → 2100 | 21.85 → 32.15 | 1.101 → 1.212 | +10% |
| flash_sale | 8.39 → 9.48 | 2600 → 1700 | 3.05 → 2.46 | 1.148 → 1.397 | +22% |
| gradual_ramp | 7.07 → 7.02 | 2200 → 3100 | 7.02 → 7.03 | 1.106 → 0.984 | −11% |
| traffic_drop | 4.72 → 4.86 | 5000 → 3900 | 7.41 → 5.80 | 1.477 → 1.687 | +14% |

**What this shows.** Averaged over the six pairs, v4 used +6% replica-hours, with p95 −2.4%, throughput +4.5% and failure rate −0.5 pp relative to HPA. The per-scenario differences go both ways and are large: p95 ranged from −49% to +50%, and failures from −11 pp to +10 pp. With one run per arm these cannot be separated from run-to-run noise, so **v4 is roughly on par with HPA in cost, with no established latency or reliability benefit**. The clear change is relative to v3, which used 58–98% more replica-hours than HPA in the same setup (§8.2).

### 8.2 v3 (previous model), 2026-10-23

Three scenarios × two controllers, 25 peak users, 300 s each, comparable starts (all services at 1 replica at controller handoff), run through the dashboard's own API (`scripts/run_lab_experiments.py`). All 6 runs completed, all cleanups were verified safe, and all 3 pairs passed the comparability checks. Full tables: `reports/live_benchmark_report.md`; per-run CSV: `reports/live_benchmark_summary.csv`; raw data: `reports/experiments/<run>/`.

| Scenario | Throughput HPA → FS | p95 ms HPA → FS | Failures % HPA → FS | Replica-hours HPA → FS | Cost proxy Δ |
| :--- | ---: | ---: | ---: | ---: | ---: |
| flash_sale | 10.44 → 8.77 req/s | 1400 → 2100 | 2.07 → 2.50 | 1.246 → 2.205 | **+77%** |
| gradual_ramp | 7.05 → 6.84 | 3000 → 3400 | 6.45 → 6.96 | 1.110 → 2.197 | **+98%** |
| traffic_drop | 5.50 → 5.44 | 1900 → 2100 | 6.75 → 7.35 | 1.193 → 1.879 | **+58%** |

**What the cost comparison shows.** FlexaScale allocated 58–98% more resources (replica-hours, requested vCPU-hours, proxy cost) than native HPA, while latency, throughput and failure rate were equal or worse. Its CPU allocation efficiency was 38–41% against HPA's 56–70%. This is an over-provisioning *cost increase*, not a saving. No prices are configured for the shop, so the figures are a unitless proxy and not money; the bookstore policy carries illustrative prices for demonstration only.

| Item | Status |
| :--- | :--- |
| Reported metrics reproducible from raw data | VERIFIED (`build_live_report.py` recomputes from `run.json`; Locust final vs sampled totals in CSV) |
| Comparable runs (same scenario/users/duration, settled start) | VERIFIED for 3 pairs |
| Steady browsing, checkout-heavy, payment-degradation live comparison | VERIFIED with v4 (§8.1); not run with v3 |
| Statistical significance | NOT VERIFIED (one run per arm, v3 and v4) |
| Withdrawn: `reports/shopping_benchmark_report.md` (untrained head) | marked withdrawn in place |
| Second application, live FlexaScale run (5-service bookstore, 120 s, preliminary) | VERIFIED: lease, freeze of `*-autoscaler` HPAs via scaleTargetRef, direct scaling of no-HPA services, budget respected (peak 15), cleanup safe. The earlier gap (no-HPA services kept their raised count) is fixed. The original count is recorded in `flexascale.io/original-replicas` before the first scale and restored on shutdown. Verified 2026-10-24 on the bookstore's `cart` (scaled 1 → 3 with the real `HPAManager`, restored to 1, annotation cleared) and in a 120 s v4 run, where shutdown cleared the markers on `cart`/`pricing`. v4 itself made no scale changes in that run. |

## 9. Installation and portability

| Item | Evidence | Status |
| :--- | :--- | :--- |
| Operator image | `docker build -f deploy/flexascale/Dockerfile -t flexascale:0.3.0 .` (1.88 GB, CPU-only torch 2.14.1, NumPy 2.2.6, SB3 2.9.0); v4 model loads (observation version 2) inside the image and includes the replica-restore code; policy validates | VERIFIED |
| Helm install/upgrade on Minikube | Existing broken release `flexascale` (chart 0.1.0, ImagePullBackOff, `--live` default, cluster-wide write ClusterRole) upgraded in place to 0.2.0, then to 0.3.0 on 2026-10-24 (v4 model, `scale_up_cooldown_seconds: 30`, `patch deployments` in live mode only). The selector was kept compatible because Deployment selectors are immutable (found during the first upgrade). Old ClusterRole removed | VERIFIED |
| Observation-only default | Decision log in the 0.3.0 pod: `observe`, v4 model path and sha256, `ppo_neighborhood`, `applied: false`; HPAs unchanged (1–10) | VERIFIED |
| Least-privilege RBAC (observe) | `kubectl auth can-i` as the operator SA: list deployments/hpa in the target namespace **yes**; patch hpa, patch deployments, update deployments/scale, create leases **no**; list deployments cluster-wide **no** (rechecked on 0.3.0) | VERIFIED |
| Live mode in-cluster | Chart renders the extra write verbs for `policy.mode=live`; the live control path itself is verified via the lab (same operator code, host kubeconfig) | PARTIALLY VERIFIED (in-cluster live not exercised; it would contend with the lab for the lease) |
| Rollback / uninstall | Standard Helm; uninstall triggers SIGTERM → HPA restore (shutdown path unit-tested and exercised by the lab) | PARTIALLY VERIFIED (not executed in-cluster) |
| Portability (2nd app) | Bookstore: same operator and model, observe and live, no code change | VERIFIED |

The upgraded in-cluster operator was left running in **observe** mode targeting `flexascale-apps` (~384 Mi request). It does not hold the lease, so it does not interfere with the lab. To remove it: `helm uninstall flexascale -n flexascale-system` or `kubectl -n flexascale-system scale deploy/flexascale-operator --replicas=0`.

## 10. Remaining limitations

* The learned policy no longer collapses to "always scale up", but it does not beat native HPA. In simulation v4 uses 61% more replicas than the HPA rule; live it was roughly on par in cost (+6% replica-hours on average), with mixed latency and failure results.
* The GNN was trained on a synthetic 4-node chain, not real call graphs. N ≠ 4 uses untrained-for neighbourhood windows.
* One run per scenario and controller; single-node Minikube; indicative only.
* Deployments without an HPA are restored to their original count only on operator shutdown. A mid-run handback (low confidence, lease loss) keeps the current count, because nothing would catch a drop under load.
* The host laptop auto-suspends; long benchmark batches must run under `systemd-inhibit` (one run was lost to a suspend).
* Confidence is uncalibrated; handing back to HPA causes churn.
* The frontend nginx DNS race is not fixed.
* The policy files hold the shop to 28 replicas because the Minikube node is a 6 GiB container that advertises the host's 16 GB as allocatable. Start Minikube with matching `--memory` or keep the budget.

## 11. Exact demonstration commands

```bash
./scripts/start_demo.sh          # readiness report; dashboard http://127.0.0.1:8090/ , shop http://192.168.49.2/
./scripts/review_status.sh       # anytime
./scripts/stop_review.sh         # safe shutdown (restores HPAs, verifies no lease)
```
