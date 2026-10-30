# FlexaScale Final Readiness Report

> **2026-10-29:** §0 covers the second laptop (Windows 11, RTX 3050): its defects, fixes, verification and the v9 evaluation. Sections 1–11 are the first laptop's record, unchanged.
>
> **2026-10-31:** §00 is the final completion pass on the first laptop (Fedora 43): end-to-end verification of the three
> controller modes on the live cluster, Helm on both releases, telemetry fixes, dashboard polish, `results/`,
> `docs/learning/` and repository cleanup. It supersedes the status lines of the older sections where they differ.

## 00. Final completion pass (2026-10-31, first laptop)

Environment: Fedora 43, Minikube profile `flexascale` (Kubernetes v1.31, 1 node, 9 GiB), Python 3.14 venv, no NVIDIA
GPU on this laptop. Branch `flexascale-v7`, starting from `main` at `fd8e100` (the second laptop's v9 work).

### 00.1 Defects found and fixed in this pass

| # | Defect | Impact | Fix (test) |
| :--- | :--- | :--- | :--- |
| 40 | p90 latency was never collected (only p50/p95/p99) | Dashboard and reports could not show p90 | p90 from the same histogram/window per service and from Locust, in live samples, summaries, `telemetry.csv`, Compare, Experiments, Overview, Live lab, timeline tooltip; older runs read it from their own Locust CSV (`tests/test_workload_metrics.py`, `tests/test_lab.py`) |
| 41 | A percentile beyond the largest histogram bucket (10 s) was shown as exactly 10000 ms | Understated latency of overloaded services | Flagged as a lower bound (`latency_capped`), shown as "≥ 10000" (`test_percentiles_in_the_inf_bucket_are_flagged_as_lower_bounds`) |
| 42 | A FlexaScale operator that was killed (SIGKILL) or hung left every HPA frozen until the run ended | No autoscaler for the rest of the run | Lab watchdog: operator exited, or status not advanced for 4 poll intervals → stop it, restore every HPA, `fallback` event and `operator_failure` record, red banner/alert in the dashboard; verified live (§00.3) (`test_watchdog_*`) |
| 43 | Helm chart: the operator Deployment's selector had no release label, so two releases in one namespace selected each other's pods | `kubectl logs/exec deploy/<release>-operator` read the wrong release's pod (found by the lifecycle test failing 1 of 33 checks with the main release installed) | Chart 0.5.1: release-specific selector for new installs; an existing Deployment keeps its immutable selector (Helm `lookup`), so upgrades keep working; lifecycle script selects pods by instance label (`test_operator_selector_is_release_specific_for_new_installs`) |
| 44 | Model paths recorded on Windows (`models\flexascale_v9\…`) were not parsed on Linux | Comparison page labelled candidates with raw Windows paths | Split on both separators (`test_model_tag_reads_windows_and_posix_paths`) |
| 45 | Dashboard layout: Comparison model tabs overflowed and clipped; Experiments filters and table clipped; run-detail and Live-lab tiles truncated values ("18 / 6…", "Viola…"); v7/v9 model cards showed blank or wrong fields; Auto page showed HPA's formula with 70% instead of Auto's 350% | Unreadable or misleading values in a presentation | Candidate dropdown; wider list and 2-column filters; wrapping 3-column detail grid; 7 tiles only on very wide screens; twin model cards (training, simulator, reward, validation, gate); Auto page uses `auto.hpa_target_pct` |
| 46 | `k8s/grafana-dashboard*.{json,yaml}`, applied by `scripts/deploy_monitoring.sh` and RUNNING.md, still had the 7-container panels; the fixed copy (defect 17) lived in `observability/grafana/` | Re-running the monitoring setup would have reverted the live Grafana dashboard | One source: the stale copies removed, script and docs point at `observability/grafana/dashboard-configmap.yaml` (the live ConfigMap is that file) |
| 47 | `kubectl` killed by a signal returned an empty error | "hpa_freeze_failed: freeze_failed: " with no reason (one occurrence, during an operator shutdown) | The exit code is reported when stderr is empty |
| 48 | Auto hysteresis events read "X -> native HPA (efficiency) … waiting 1/2" | Looked like a switch to HPA while it was a pending switch to FlexaScale | "X stays with native HPA; efficiency rule chose FlexaScale … (waiting 1/2)" |
| 49 | `requirements.txt` listed an unused package (python-dotenv) and lacked four used ones (requests, psutil, locust, httpx) | A fresh install could not run the lab or the tests | Updated; the operator image keeps its own `deploy/flexascale/requirements.txt` |
| 50 | Live-lab form kept showing its own defaults while a run started elsewhere was active | Displayed mode/users did not match the running experiment | The disabled form mirrors the active run's request |

### 00.2 Final status

| Area | What was checked | Status |
| :--- | :--- | :--- |
| Test suite | `pytest`: **373 passed, 0 failed** on 2026-10-31 (`logs/pytest_final_2026-10-31.out`) (was 364 at the start of this pass; 9 new tests for the fixes above); `npm run build` type-checks and builds the dashboard | VERIFIED |
| Startup / shutdown | `./fsctl start` (cold Minikube: 57 s, 8 steps, READY) and `./fsctl stop` (HPAs restored, no Lease, processes stopped) on this laptop | VERIFIED |
| Metrics pipeline | 16/16 services scraped (ServiceMonitor 15 s + annotation job 30 s, de-duplicated), cAdvisor 10 s; CPU/memory per service; zero vs missing distinguished (`no_traffic`); only `shopping-frontend` (nginx, no `/metrics`, excluded from scaling) is down as a target | VERIFIED |
| Per-service latency | Every service with traffic reports mean and p50/p90/p95/p99 from its own histogram (not the gateway's), consistent order p50 ≤ p90 ≤ p95 ≤ p99; idle services "no requests" | VERIFIED |
| State aggregation / features | v3 features computed by the same `FeatureTracker` in training and live; `policy_input` logged per decision (10 values per service) | VERIFIED |
| Dependency graph + GNN | 25 policy edges, sorted node order, 16 ≤ 20 slots; `ppo_graph` inference (GraphFocalExtractor) in every live decision; model sha256 recorded | VERIFIED |
| PPO policy loading | v9 (`2f95764b…`) and v7 (`5d4fcc20…`) load on Linux; failure → heuristic + live refused (unit tests) | VERIFIED |
| Safety guards and execution | bounds, budget, readiness, cooldowns, blocks, telemetry checks recorded per decision; FlexaScale scale requests applied and confirmed by Kubernetes (desired, then ready) | VERIFIED (§00.3) |
| Exclusive ownership | No applied action without FlexaScale ownership and an HPA freeze in any verification run; Lease held only during live runs; cleanup verified safe after every run | VERIFIED |
| Native HPA mode | HPA scaled order 1→3, catalog 1→3 under a 40-user flash sale; FlexaScale shadow logged 496 proposals, applied 0 | VERIFIED |
| FlexaScale mode | v9: live, Lease, 512 accepted decisions but only holds (v9 is fitted to the other laptop); v7 (this laptop's model) at 40 and 25 users: also live, 512 accepted decisions each, holds only — at these loads the shop is latency-bound (event loop), not CPU-bound, and both policies key on CPU (§00.4). FlexaScale-mode scale changes confirmed by Kubernetes are in earlier runs on this cluster (`20261028-061846-shopping-flexascale-flash_sale`: order-service 1→2→1, v7) and in Auto mode below | PARTIALLY VERIFIED (mode, ownership, safety and execution path verified today; no scale change today) |
| Auto mode selects FlexaScale and applies scaling | Default policy: order-service 1→2 by the v9 policy under Auto (rule efficiency), desired confirmed at +295 s, ready at +305 s; after the outage, 6 FlexaScale scale-downs applied; Auto with v7: all services FlexaScale-owned (efficiency), holds only | VERIFIED |
| Auto mode selects HPA (SLA risk) and mixed ownership | Controlled variant `verify_sla_risk` (CPU risk 60%): **mixed ownership in 21 of 31 steps** (api-gateway, cart, catalog, inventory, order → HPA by `sla_risk`, 11 services FlexaScale in the same step); HPA scaled the risky services to 3; FlexaScale applied 7 actions (order 1→2 at +29 s, then scale-downs) | VERIFIED |
| Fallback: telemetry unavailable | Prometheus stopped for 60 s: all 16 services → HPA in the same step (controller_health), HPAs unfrozen, HPA scaled meanwhile; back to FlexaScale after 2 steps | VERIFIED |
| Fallback: FlexaScale unhealthy | Operator SIGKILLed: watchdog restored 16 HPAs 1 s later; HPA scaled the rest of the run; cleanup safe | VERIFIED |
| Dashboard | All 7 pages render with real data (screenshots in `results/screenshots/`); live run, replay, Auto table, Comparison, Models | VERIFIED |
| Live scaling timeline | Desired/ready, FlexaScale and HPA proposals, scale-request markers, owner band, traffic and latency from real samples; live and replay | VERIFIED |
| Helm (bookstore) | Chart 0.5.1, image 0.6.0 built here and loaded into Minikube: install (observe) → upgrade (live, v9) → rollback → uninstall, **33/33 checks** (`logs/helm_lifecycle_0.5.1.linux.out`); the first attempt found defect 43 (`…selector-defect.out`) | VERIFIED |
| Helm (main release) | `flexascale` 0.4.1 → 0.5.1 (image 0.6.0, v7, observe), rollback to 0.4.1, forward again (rev 12); shop release, 18 Deployments, PVC uid and data unchanged (`logs/helm_main_release_0.5.1.out`) | VERIFIED |
| Images | Built locally (not in a registry): `build_shop_images.sh` and the operator Dockerfile; documented in RUNNING.md | VERIFIED (documented; a fresh cluster still needs the build) |
| Training (Part 8) | No new training: this laptop has no NVIDIA GPU; v9 (GPU-trained on the second laptop) is not measurably better than v7 on held-out twin tests and is on par live; more training is not justified by any evidence. v7 and v9 stay as they are; nothing was overwritten | NOT RUN (decision documented) |
| Results folder | `results/RESULTS.md`, data, charts, screenshots, verification | VERIFIED |
| Learning docs | `docs/learning/FLEXASCALE_COMPLETE_EXPLANATION.md`, `docs/learning/FLEXASCALE_DASHBOARD_COMPLETE_GUIDE.md` | VERIFIED |

### 00.3 Live verification of the controller modes

See `results/verification/README.md` (generated from the runs' own decision logs, lab events and kubectl snapshots).
Incident: the laptop idle-suspended from 00:51 to 03:04 during one verification run; that run is in
`reports/experiments_invalid/` and was repeated under a `systemd-inhibit` sleep lock.

### 00.4 Remaining limitations

* Auto mode's default thresholds were calibrated on the second laptop (CPU risk 400%, HPA estimate at 350%) and the shop
  has no per-service latency SLO, so on this laptop at 40 users Auto kept FlexaScale (v9) in charge while end-to-end p95
  reached 6 s; the SLA-risk rule itself works (controlled variant). Per-laptop calibration and an end-to-end SLO input
  for Auto are future work.
* The default policy (v9) suits the second laptop; on this laptop use the v7 variant for demonstrations.
* Single-node Minikube, 25–40 users; images not in a registry; FlexaScale is on par with a tuned HPA, not better.


Date: 2026-10-23, updated 2026-10-24 (v4 policy, six-scenario live benchmark, replica restore for HPA-less Deployments, chart/image 0.3.0) 2026-10-25 (v5 policy, live benchmark with two repeats, chart/image 0.4.0) and 2026-10-26 (16-service shop, v6 policy attempt, Auto mode, redesigned control center; evening: six-scenario tuned-HPA batch, host-load check of every run, in-cluster Helm rollback/uninstall test with a fix in chart 0.4.1). Environment: Fedora 43, Docker, Minikube profile `flexascale` (Kubernetes v1.31, single node, a Docker container with 9 GiB RAM, raised from 6 GiB), Python 3.14 venv.

Status keys: **VERIFIED** (executed and checked here), **PARTIALLY VERIFIED**, **NOT VERIFIED**, **BLOCKED**.

## 0. Second laptop (2026-10-28/29): Windows 11, RTX 3050

Environment: Windows 11 Home 25H2, AMD Ryzen 7 6800H (8 cores / 16 threads), 15.3 GB RAM, NVIDIA RTX 3050 Laptop GPU (4 GB, driver 592, CUDA 13.1), Docker Desktop 29.7 (WSL2 VM, 7.9 GB), Minikube profile `flexascale` (docker driver, 4 vCPU, 6 GB, Kubernetes v1.31), Python 3.12 venv (`.venv`, CPU PyTorch 2.13) plus a separate training venv (`.venv-gpu`, PyTorch 2.13 + CUDA 13.0). Power plan "Turbo"; Modern Standby (S0 low-power idle) laptop.

### 0.1 State found

The cluster still ran the original 4-service demo; none of the 16-service shop's images existed on this laptop. No live experiment could run on Windows, every trained model failed to load, the start scripts depended on an untracked file, and FlexaScale's CPU/memory telemetry was empty for every service. Everything below was found by running the system end to end.

### 0.2 Defects found on the second laptop (all fixed; found by running the system)

| # | Defect | Impact | Fix (test) |
| :--- | :--- | :--- | :--- |
| 20 | Lab process manager was POSIX-only (`/proc`, `os.getpgid`, `killpg`, SIGKILL) | No experiment could start on Windows | psutil identity (creation time + command line), own process group, graceful CTRL_BREAK → SIGBREAK before a tree terminate; the operator handles SIGBREAK. Verified live: "Signal 21 received: returning control to HPA" (`lab/processes.py`, `tests/test_lab.py`) |
| 21 | SB3 checkpoints failed to load on Windows ("PytorchStreamReader failed … file read failed") although every zip CRC passed | Every trained model unusable; FlexaScale refused live runs | PyTorch 2.13 cannot read the member stream SB3 passes; it is buffered to memory first (`rl/sb3_compat.py`; 62 policy/operator tests) |
| 22 | `scripts/lib/review_common.sh` was never committed (the Python `.gitignore` rule `lib/`) | `start_review.sh` / `stop_review.sh` failed on every fresh clone | Tracked; the bash entry points delegate to one cross-platform launcher, `fsctl start/stop/status` (`lab/launcher.py`, `fsctl`, `fsctl.cmd`) |
| 23 | Shell scripts checked out with CRLF (`core.autocrlf=true`) | bash scripts break on Windows | `.gitattributes` (`*.sh eol=lf`, `*.cmd eol=crlf`) (`test_shell_scripts_have_lf_line_endings`) |
| 24 | Minikube IP unreachable from the host with the Docker driver on Windows/macOS | Shop and Locust unreachable | `fsctl start` runs a managed `minikube tunnel`; the lab resolves the reachable ingress URL (`lab/experiments.resolve_app_url`) |
| 25 | `localhost` port-forwards bound to 127.0.0.1 only | Every Prometheus query took 2.04 s (IPv6 tried first): 22 s per 5 s sample | Port-forwards bind both loopbacks (`lab/portforward.py`); 0.018 s per query |
| 26 | cAdvisor exports pod-level cgroups only (Docker runtime, cgroup v2); queries required a `container` label | CPU/memory missing for every service: FlexaScale would hold every service (`telemetry_unavailable`) | Container-level series if present, else pod-level (`metrics/workload_metrics.py`, `tests/test_workload_metrics.py`) |
| 27 | Pods scraped by a ServiceMonitor *and* the annotation job; `sum by (pod)` | Request rates 2× too high, on this laptop and on the first one (v7 twin: gateway ≈ 1.96 × Locust rate) | Sum per (pod, job), max over jobs; disclosed in `docs/POLICY_V9.md` §8 |
| 28 | A scraped pod without request series reported as "missing" | Idle services looked broken; zero and missing were not distinguishable | `up == 1` and no series → 0 req/s, `no_traffic`; the dashboard shows "no requests" |
| 29 | Host-load check: cAdvisor gap, upower-only battery history, node-exporter inside the VM | Every Windows run would be "unknown" | Lab records `host` (AC, whole-machine CPU, clock) every 5 s; `check_host_load.py` uses it; pod-level fallback; Windows limit from a measured idle baseline (`tests/test_v9_tools.py`) |
| 30 | `run_plan.py` training freezer (`pgrep`, SIGSTOP) and battery checks were Linux-only; nothing kept Windows awake | Batches could not pause training, would not wait for AC, and could be cut by idle sleep | psutil suspend/resume and battery; `SetThreadExecutionState` for the runner's lifetime (`tests/test_run_plan.py`) |
| 31 | 103 text-file reads/writes without an encoding (Windows default cp1252) | Crashes on "Δ", "→" in reports and run files | Explicit UTF-8 everywhere (AST-based rewrite, full suite green) |
| 32 | Frontend image build copied the host's `node_modules` (Windows binaries) | `npm run build` exit 127 in the image | `apps/shopping-frontend/.dockerignore` |
| 33 | `index.html` served without a cache policy | A rebuilt dashboard kept showing the old bundle | `Cache-Control: no-cache` for the page; hashed assets stay cacheable |
| 34 | The dashboard re-downloaded the whole active run (up to ~1 MB) every 3 s | Slow and wasteful; the chart re-rendered from scratch | Index-based incremental API (`samples_from`, `events_from`) and client-side merge (`tests/test_lab_timeline.py`) |
| 35 | The shop's policy selected every Deployment in the namespace | Four leftover demo Deployments were discovered as shop services | Policies select the shop chart's label `app.kubernetes.io/part-of=flexascale-ecommerce` |
| 36 | The imitation warm start built its batches on the CPU while the policy was on the GPU | GPU training of every warm-started (focal_bc) run failed at its first batch | Batches go to the policy's device; unchanged on CPU (`rl/imitation_v7.py`; `tests/test_imitation.py`, `tests/test_v7.py`, GPU smoke test) |
| 37 | Against the default HPA the dashboard judged the pre-registered block studies by the v6 rule, and dropped a valid pair over a duration difference | Comparison page and Overview showed v9 as "Beats HPA on cost" under a "pre-registered" label; the pre-registered verdict is on par / inconclusive | Block studies use their own table (POLICY_V7 §3.5) against either reference; a study pair is not dropped for duration alone (`lab/benchmark.py`, `tests/test_hpa_tuned.py`); the Comparison page describes block pairing and names the reference in "Δ = candidate − …" (`pages/Compare.tsx`). All six v9 comparisons now equal `reports/v9/evaluation.json`, checked in the browser |
| 38 | The operator image's build allowlist included all of `src/`, so the 7.4 GB Alibaba trace in `src/flexascale/data/raw` went into the image | 9.36 GB image; on an out-of-memory host the copy most likely overloaded the Minikube node (control-plane restart, 02:44) | `.dockerignore` excludes `src/flexascale/data/raw` (training input, never read by the operator): image 1.43 GB |
| 39 | When a new run started while the dashboard still held the previous one, the server answered the dashboard's incremental request for the new run using the old run's sample count | The second of two back-to-back runs showed "prep" in the header and an empty timeline until it passed the first run's length, and its first events were missing (found running the whole app, 2026-10-30) | A new run's first answer to an incremental request is replaced by a full snapshot (`timeline/feeds.ts`); checked live: HPA run after an Auto run, without a reload, timeline and elapsed time correct from the first samples |

### 0.3 Verified on this laptop

| Check | Result | Status |
| :--- | :--- | :--- |
| `pytest` (framework + shop + new tests) | 354 passed, 0 failed on Windows on 2026-10-28 (was 39 failures before the fixes); **362 passed, 0 failed on 2026-10-29 13:27** (with the GPU warm-start fix); **364 passed on 2026-10-30 03:12** after the v9 work (§0.6) | VERIFIED |
| Shop images (17) built into Minikube; shop chart 1.1.0 installed; database seeded | all 16 services, frontend and PostgreSQL ready; storefront and API through the ingress tunnel | VERIFIED |
| `fsctl start` / `fsctl stop` / `fsctl status` | full startup in 25–44 s (122 s with a cold Minikube after a reboot); stop restores every HPA and verifies no Lease | VERIFIED |
| Native-HPA smoke run (Locust + shadow operator) and a FlexaScale v5 flash-sale run | Lease taken, HPAs frozen, 14 scale actions applied, cleanup verified safe; operator received SIGBREAK and handed back gracefully | VERIFIED (demo runs, `reports/experiments_demo/`) |
| v7 graph policy against this cluster (observe) | 32 decisions in `ppo_graph` mode, no missing telemetry | VERIFIED |
| Live Autoscaling Timeline (live, replay, single-service view, tooltip, pause) | checked in the browser against a real FlexaScale run | VERIFIED |
| Second application (bookstore, 5 services, 2 without HPA) deployed | 5/5 ready, 3 HPAs | VERIFIED (in-cluster Helm lifecycle with the v9 model, 33/33 checks: §0.5) |
| GPU assessment | §2 of docs/POLICY_V9.md | see there |

### 0.4 v9 policy and pre-registered live evaluation (2026-10-28 → 30)

Protocol fixed in `docs/POLICY_V9.md` before the first calibration run; every step, incident and deviation is logged in its §8. Reports: `reports/v9/` (index in its README).

| Step | Result | Status |
| :--- | :--- | :--- |
| HPA-tuned calibration (§3; 8 runs + 1 rerun of a host-affected run) | CPU target **350% of request**, 60 s scale-down window (`reports/v9/calibration.md`) | VERIFIED |
| Twin refitted to this laptop (§5) | against the calibration runs: replica-hours 2.0%, p95 8.9%, mean latency 4.4% mean absolute error (v7's twin: 1.9%, 20.5%, 17.7%); only the steady calibration load was available to check it (`twin_check.md`) | VERIFIED (limited) |
| GPU rule (§2: train on cuda if ≥ 1.5× the best CPU agent-steps/s) | RTX 3050 **1.79×** → 4 runs × 2,000,000 agent-steps in 63 min; one defect fixed (36) | VERIFIED |
| Selection (validation, 40 workloads, v7 reward) | focal_bc_s2 **−2.47**, focal_bc_s1 −2.99, no graph −2.92, old reward −3.30, best rule −2.99; seed spread (0.52) is as large as any design effect | VERIFIED |
| Gate (§5: v9 must beat v7 on the v9 twin's validation set) | v9 −2.47 vs v7 −2.91: **passed**, v9 became the RL arm and the shop's default policy. Selection and gate use the same validation set, which favours v9 | VERIFIED |
| Live evaluation (§6: 12 blocks × 4 arms, order fixed by seed) | 48 runs + 5 reruns; **7 host-affected, all FlexaScale or Auto** (their runs use about 1 core more outside Kubernetes than the HPA arms; not the model, which the HPA arms also run in shadow mode, but the live operator's work on the cluster, which part not measured; memory pressure later); 46 valid runs | VERIFIED |
| **Verdict vs HPA-tuned (primary)** | **FlexaScale-RL: on par / inconclusive** (11 pairs; replica-hours +0.3% [−0.2 … +0.7], p95 +155% [−165 … +475]); **FlexaScale-Auto: on par / inconclusive** (11 pairs; replica-hours +0.2%, p95 +41.5% [−22.6 … +105.7]) | VERIFIED |
| Verdict vs HPA-default | RL and Auto use **7.3% and 7.7% fewer replica-hours** (intervals below 0) but fail the p95 check → on par / inconclusive. HPA-default vs HPA-tuned: **worse** (+10.6% replica-hours [+4.2 … +17.1]) | VERIFIED |
| Sensitivity (descriptive, added after the verdict) | Without the pairs containing a late rerun (run 1–2 h after their block under memory pressure; one of them is the +1,588% p95 pair): RL vs HPA-tuned replica-hours +0.1%, p95 +3.8% [−6.2 … +13.9]; RL vs HPA-default replica-hours −8.2%, p95 −2.0% [−20.6 … +16.5] (`evaluation_sensitivity.md`). The verdict is unchanged | reported only |
| Twin test sets (run once, after the live runs) | T1 (6 live scenarios × 5 seeds): **HPA-tuned −1.20**, v9 −1.26, rule −1.28, HPA-default −6.33; T2 (60 random shop workloads): v9 −2.55, rule −2.79, HPA-tuned −3.06; T3 (40 random applications): graph seed 1 −76.0, no graph −76.7, v9 −79.0, HPA-tuned −82.4 (`ablation.md`) | VERIFIED |
| v9 vs v7 on the held-out test sets (descriptive, added after) | Paired by episode on both laptops' twins: every reward interval includes 0 (this laptop's twin T1 −0.001 [−0.068 … +0.066], T2 +0.007 [−0.31 … +0.32]; T3 −3.65 [−7.74 … +0.43]). **v9 is not measurably better than v7**; the gate's margin came from the selection set. No live head-to-head (`v9_vs_v7.md`) | VERIFIED |
| Graph ablation (seed 1, paired by episode) | reward Δ −0.001 [−0.026 … +0.024] (T1), +0.16 [−0.36 … +0.68] (T2), +0.71 [−3.30 … +4.72] (T3): **no measurable benefit**; the graph policy uses fewer replicas at higher p95 | VERIFIED |

What it means: on this laptop the v9 policy is as good as a well-tuned HPA, not better. HPA-tuned matches its cost saving over default HPA without any model (both keep most services at their minimum at 25 users). The twin agrees on the live scenarios and shows v9 ahead only on random workloads, which were not run live.

Incidents (all in `docs/POLICY_V9.md` §8, runs filed in `reports/experiments_invalid/`): the lid was closed at 18:25 during run 20's preparation (Modern Standby until 19:08; the runner's sleep inhibition does not cover the lid), so that run was stopped before its load and run again. By 23:47, when it was first measured, the laptop had run out of physical memory (36 MB available, ~20,000 pages/s), and latency of the same scenario rose by up to ~60% between the first and second repetition; arms are compared within blocks. Status commands run during run 40's load window most likely pushed it over the host-load limit.

### 0.5 Helm on this laptop (operator image 0.6.0, chart 0.5.0)

| Check | Result | Status |
| :--- | :--- | :--- |
| Chart renders and lints | `helm lint` passes with `values-bookstore.yaml` and with the new `values-v9.yaml`; `helm template` renders ServiceAccount, policy ConfigMap, Role/RoleBinding in the application namespace, operator Deployment and the hand-back hook Job, and the v9 values select `/app/models/flexascale_v9/…` | VERIFIED |
| Operator image 0.6.0 (v5, v7 and v9 models; `values-v9.yaml` added) | First build at 02:44 failed at `COPY src`: it was copying the 7.4 GB Alibaba trace (defect 38) into a node on an out-of-memory host, and the node's control plane and pods restarted. After a reboot and the `.dockerignore` fix the image is **1.43 GB** (was 9.36 GB) and contains CPU PyTorch 2.15 and the three models (`logs/operator_image_0.6.0.rebuild.log`) | VERIFIED |
| Install → upgrade (live, v9) → rollback → uninstall on the bookstore | `scripts/helm_lifecycle_test.sh`, 2026-10-30 11:21–11:23: **33 of 33 checks passed** (`logs/helm_lifecycle_0.6.0.out`). Observe: v5 model (`ppo_neighborhood`), HPAs untouched, no Lease, read-only RBAC. Live with v9: Lease taken, 3 HPAs frozen and 2 HPA-less Deployments marked, decisions in `ppo_graph` mode, write RBAC limited to HPAs and the scale subresource. Rollback and uninstall: HPAs back to 1–5, every marker cleared, Lease released, no RBAC left. A first run failed the 3 live checks because Git Bash rewrote `/app/...` in `--set` for `helm.exe` (test-script defect, fixed with `MSYS_NO_PATHCONV=1`); the operator then refused live control on the missing model path, as designed (`logs/helm_lifecycle_0.6.0.pathconv-failed.out`) | VERIFIED |

### 0.6 Tests

`pytest`: **364 passed, 0 failed** on 2026-10-30 03:12 (`logs/pytest_final_v9.out`; 362 before, plus 2 tests for defect 37). The dashboard type-checks and builds (`npm run build`, 03:07).

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
