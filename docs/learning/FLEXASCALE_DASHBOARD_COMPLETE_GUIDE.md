# FlexaScale Control Center — Complete Operating Guide

This guide teaches you to operate the FlexaScale dashboard from the very beginning, assuming you have never used it.
For *what* each component is and *why* it exists, read `docs/learning/FLEXASCALE_COMPLETE_EXPLANATION.md`; this guide
is about *how to use it*. Every button below says what happens in the backend when you press it.

## Contents

1. [Starting the dashboard](#1-starting-the-dashboard)
2. [The frame: sidebar, header, status chips](#2-the-frame-sidebar-header-status-chips)
3. [Overview page](#3-overview-page)
4. [Live lab](#4-live-lab)
5. [Auto mode page](#5-auto-mode-page)
6. [The Live Autoscaling Timeline (scaling visualisation)](#6-the-live-autoscaling-timeline)
7. [Comparison page](#7-comparison-page)
8. [Service topology](#8-service-topology)
9. [Models page](#9-models-page)
10. [Experiments (results and history)](#10-experiments-results-and-history)
11. [Practical operating examples](#11-practical-operating-examples)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Starting the dashboard

### 1.1 Prerequisites (one-time setup, already done on the project laptop)

* Docker, Minikube, `kubectl`, `helm` installed; a Minikube profile named `flexascale` with the shop (Helm release
  `shopping-app`, chart 1.1.0), monitoring (release `monitoring`, kube-prometheus-stack) and optionally the in-cluster
  operator (release `flexascale`) installed. The shop's container images are **built locally inside Minikube** and are
  not in a public registry (see `RUNNING.md` for building them on a new machine).
* A Python virtual environment `.venv` with the project installed (`pip install -e .`) and Locust.
* The dashboard is already built into `src/flexascale/lab/static/`. Only if you change `dashboard/src/` do you need
  `cd dashboard && npm install && npm run build`.

### 1.2 Startup command

From the repository folder:

```bash
./fsctl start            # Linux/macOS (Windows PowerShell: .\fsctl.cmd start)
./fsctl start --check    # only check everything; start nothing, change nothing
./fsctl start --demo     # start, and also print a suggested demo sequence
```

**What happens (8 steps, printed as `== 1/8 …`):** checks tools → starts the existing Minikube profile if it is stopped
(2–4 minutes; it never creates or deletes anything) → checks the namespaces and that every Deployment is ready →
checks the shop through the ingress → starts port-forwards for Prometheus (9090), Grafana (3000) and the bookstore
(18081) → checks Prometheus scrape targets → checks the trained model, the policy file and **that native HPA owns
everything with no FlexaScale Lease held** → starts the lab server (the dashboard) on port 8090.

### 1.3 Expected output (last lines)

```
READY in 57 s
  Control center : http://127.0.0.1:8090/
  Shop           : http://192.168.49.2/   (demo login: demo@flexascale.io / CustomerPass123!)
  Prometheus     : http://localhost:9090/
  Grafana        : http://localhost:3000/
  Bookstore      : http://localhost:18081/
  Status         : fsctl status        Stop safely: fsctl stop
```

A `[WARN]` line is information, a `[FAIL]` line stops startup and prints a `Fix:` hint. A cold Minikube can make the
first Prometheus check show fewer targets than services; that settles within a minute.

### 1.4 URLs

| What | URL |
|---|---|
| FlexaScale control center (this dashboard) | http://127.0.0.1:8090/ |
| Shopping application | http://<minikube ip>/ (printed by `fsctl start`; usually http://192.168.49.2/) |
| Prometheus | http://localhost:9090/ |
| Grafana | http://localhost:3000/ |

Pages have their own addresses: `#overview`, `#topology`, `#live`, `#auto`, `#compare`, `#experiments`, `#models`
(e.g. http://127.0.0.1:8090/#live).

### 1.5 Health checks

* `./fsctl status` — read-only report: processes, ports, ownership (who owns each Deployment), Lease.
* `curl http://127.0.0.1:8090/api/lab/health` → `{"status":"ok"}`.
* In the dashboard header: the **Telemetry**, **Cluster** and **Prometheus** chips must be green.

### 1.6 Safe shutdown

```bash
./fsctl stop                         # normal
./fsctl stop --force-release-lease   # only if a Lease is stuck (see Troubleshooting)
```

It asks a running experiment to stop, stops only processes it started (never anything by port), restores every HPA
FlexaScale froze, and verifies that no Lease is held. It leaves Minikube, Deployments, Helm releases and database data
untouched. To stop Minikube as well: `minikube stop -p flexascale`.

---

## 2. The frame: sidebar, header, status chips

* **Sidebar (left).** Three groups: *Observe* (Overview, Service topology), *Operate* (Live lab, Auto mode),
  *Analyze* (Comparison, Experiments, Models). A green dot next to *Live lab* means an experiment is running. At the
  bottom: **Deployed policy** (the model the shop's default policy uses, e.g. `flexascale_v9`; "observe by default; live
  only during experiments") and **Open the shop**.
* **Header (top).** Page title and subtitle. On the right:
  * **Active-run chip** (e.g. "Native HPA · 1:05"): the running experiment's controller and elapsed time.
  * **Telemetry · 4 s**: age of the last live data. Green when fresh; amber/red when the backend stops answering.
  * **Cluster flexascale**: the Kubernetes context; red if `kubectl` cannot reach the cluster.
  * **Prometheus**: red if Prometheus is unreachable.
  * **Application selector**: *E-commerce shop (16 services)* or *Synthetic bookstore (5 services)*. Disabled while a run
    is active.
  * **Sun/moon button**: light/dark theme (remembered in your browser).
* **Rule of the whole dashboard:** a missing value is shown as **"—"**, never as 0 and never estimated. "no requests"
  means a service was measured and genuinely served zero requests.

---

## 3. Overview page

The "is everything healthy?" page.

### 3.1 Top cards

| Card | What it shows | How to read it |
|---|---|---|
| **Active controller** | Native HPA when idle; otherwise the running experiment's controller, scenario and elapsed/total time | Coloured blue (HPA), green (FlexaScale) or purple (Auto) |
| **Cluster** | Ready nodes / total nodes, context, Prometheus up/down | Green only if kubectl, Prometheus and all nodes are OK |
| **End-to-end SLA** | Locust p95 of the last ~10 s window during a run, and the target (≤ 1000 ms) | Green = met, red = violated, grey = no run |
| **Replicas** | Ready replicas, "ready of N desired", the replica budget (48), a sparkline of the last minutes | Ready < desired means pods are starting |
| **Mean CPU** | Average CPU (% of request) over services that report it, and how many report | "16/16 services reporting" is healthy |
| **Estimated cost rate** | $/hour of what is allocated *now* (ready replicas × requests × list prices); vCPU and GiB allocated | An estimate, not a bill (hover for the price basis) |

### 3.2 Workload now

A strip of 8 values from the running experiment's latest Locust window: **Throughput** (req/s and virtual users),
**p50**, **p90**, **p95** (red icon when above the SLO), **p99**, **Error rate** (failures of total), **SLA time
violated** (share of 5 s samples whose p95 was above the SLO), **Mean memory**. When no experiment runs it says *Idle*
and shows "—" (not zeros).

### 3.3 Live Autoscaling Timeline (compact)

The same visualisation as in the Live lab (Section 6). Idle, it records the live cluster every 5 s from the moment you
open the page (no traffic or policy data then).

### 3.4 Application topology

The call graph: one box per service with its owner colour stripe (blue HPA, green FlexaScale, purple Auto-owned,
grey "reset"), CPU % and replica count; arrows are caller → callee. Click a box for its details (owner, replicas, HPA
range, CPU, req/s, mean / p95 latency). Above the graph: how many services each owner holds (e.g. "HPA ×16").

### 3.5 Alerts

Derived from the live state only. Examples: *Prometheus unreachable* (critical), *X: latency above SLO*, *X: CPU
pressure* (≥ 85%), *X: 5xx errors* (> 5%), *X: HPA left frozen* (frozen with no experiment running — run
`./fsctl stop`), *Controller lease held outside an experiment*, *Replica budget nearly used*, *FlexaScale fell back to
native HPA* (the watchdog acted), *Cleanup not verified*. "All clear" when none apply. Below: **Recent scaling &
ownership events** (Fallback, Scale, Replicas, Owner, Safety) with run time.

### 3.6 Benchmark verdict and cost per experiment

* **Benchmark verdict:** the newest FlexaScale (or Auto) comparison against native HPA: Δ replica-hours, Δ p95, Δ failure
  rate with 95% confidence intervals and a verdict badge. Fewer than 6 pairs → "Preliminary". *Details* opens the
  Comparison page.
* **Cost per experiment:** replica-hours of the last 30 recorded runs (blue = native HPA, green = FlexaScale/Auto).
  Hover a bar for scenario, controller, p95 and run id.

---

## 4. Live lab

Where you run experiments. Left column: controls. Right column: live results.

### 4.1 Controls and what happens in the backend

| Control | Meaning | Backend effect when you press Start |
|---|---|---|
| **Autoscaling mode: Native HPA** | Kubernetes HPA scales every service (CPU target 70%) | No Lease, no frozen HPA. If *shadow mode* is ticked, the operator starts with `--mode observe` and only logs proposals |
| **FlexaScale** | The GNN+PPO policy owns every service | Operator starts with `--mode live`; takes the Lease `flexascale-shopping`; freezes each HPA before scaling |
| **Auto** | Per-service choice between FlexaScale and HPA | Operator starts with `--mode live --auto` |
| **Native HPA, 60 s scale-down** | HPA with a shorter scale-down window (default 300 s) | The lab patches every HPA's `behavior` for the run and restores it afterwards |
| **Native HPA, tuned** | HPA with the calibrated CPU target and window (`config/lab.yaml`, `hpa_tuned`) | Patches CPU target and window for the run; restored afterwards |
| **FlexaScale policy** | Default policy or a variant (v5, v7, v9, rules, `verify_sla_risk`) | Chooses the policy file (`config/lab.yaml` → `variants`) passed to the operator |
| **Workload scenario** | One of the Locust scenarios (description shown below the box) | Sets `FLEXASCALE_SCENARIO` for Locust |
| **Peak users** | Maximum simultaneous virtual users (1–500; comparisons used 25; above ~40 the single node may run out of memory, a red note appears) | `FLEXASCALE_USERS` |
| **Spawn / s** | How many users start per second | `FLEXASCALE_SPAWN_RATE` |
| **Duration s** | Length of the load (30–3600; 300 is standard) | `FLEXASCALE_DURATION`; the run is "short/preliminary" below 300 s |
| **Comparable start** | Reset data and start from minimum replicas | Restock inventory, empty test carts, freeze HPAs at their minimum, scale down, wait until ready (and until HPA's 5-minute memory of the previous load has expired), restore the HPAs, verify they stay settled |
| **FlexaScale shadow mode** (HPA modes only) | Log FlexaScale's proposals without acting | Operator in observe mode; its proposals appear as "would propose" |
| **Start** | Starts the experiment | `POST /api/lab/experiments`. Refused (with a message) if another experiment is active, a Locust or operator is still running, or a FlexaScale Lease is held |
| **Stop → Confirm stop** | Ends the run early | `POST /api/lab/experiments/stop`: Locust and operator stopped, every HPA restored, Lease checked; state becomes *stopped* |

**Which policy to pick on which laptop.** Each trained model was fitted to one laptop's measurements. The default
policy is **v9**, fitted to the second laptop (Windows, RTX 3050). On the **first laptop (Fedora)** v9 holds every
service at its minimum even at 40 users (its scale-up threshold is not reached there), so for a demonstration with
visible FlexaScale scaling choose **FlexaScale policy → v7** (fitted to the first laptop; Auto then uses this laptop's
calibrated HPA target, 250%). This was checked live on 2026-10-31 (`results/verification/`).

**Duplicate and unsafe transitions are prevented:** only one experiment at a time; all controls are disabled while a
run is active; the mode cannot be changed mid-run; Stop needs a confirmation; a run started elsewhere (e.g. by a batch
script) has Stop locked until you tick *unlock*.

### 4.2 Open alongside

Buttons for the **Shopping application**, **Grafana** and **Prometheus**. Browsing the shop by hand adds to the load.

### 4.3 Controller ownership card

"Lease held by FlexaScale" or "Lease free", owner counts (HPA ×n, FlexaScale ×n, Reset hold ×n), the operator's mode
(*live/observe*, *Auto arbitration*), its step number and loaded model. "NO MODEL (CPU heuristic)" would mean the model
failed to load (live mode is then refused).

### 4.4 Current experiment (right column)

* **Header:** run id, state (*preparing → running → stopping → completed/stopped/failed*), progress bar. During
  *preparing* there is no load yet (comparable start).
* **Stat tiles:** Elapsed, Users, Throughput (10 s window), Error rate, **p50 / p95** (sub-line: p90 and p99),
  Replicas ready/desired, **E2E SLA** (Met / Violated, against p95 ≤ 1000 ms — exactly the p95 shown).
* **Fallback banner (red):** appears if FlexaScale became unhealthy and the watchdog returned every service to native
  HPA, with the time and the reason.
* **Whole-run result** (after the run): throughput, p50/p90/p95/p99, failure %, replica-hours, estimated cost, and the
  cleanup result ("native HPA ownership verified").
* **Live Autoscaling Timeline** (Section 6) with the **per-service replica strips** (one mini-row per service on the
  same time axis; click one to focus the main chart on that service).
* **CPU per service** and **Memory per service** charts (first 8 services coloured; pick others with the chips).
* **Services table** (5 s refresh): owner, ready/desired, HPA min–max (and "frozen; was 1–10" while FlexaScale holds
  it), CPU % of request, memory %, req/s, mean latency, p95 (hover for p50/p90/p95/p99; "≥" means at least that value,
  beyond the largest histogram bucket), telemetry status (*ok*, *stale*, or which metric is missing).
* **FlexaScale policy panel:** counts of *Proposal batches* (policy output, not actions), *Applied scale requests*
  (sent to Kubernetes) and *Safety interventions* (blocked changes, hand-backs, fallbacks), with the latest ten.
* **Event log:** every event with time and kind; click kind buttons to hide/show kinds. Kinds: Preflight, Ownership,
  Workload, Traffic (phase changes), Metric (CPU/SLO crossings), Policy (proposals), Scale request (applied by
  FlexaScale), Replica change and Ready (observed in Kubernetes), Safety, Auto mode, Fallback, Warning, Error.

---

## 5. Auto mode page

### 5.1 Explanation card and *Run in Auto mode*

Explains the rule order. The HPA recommendation formula shown uses the CPU target Auto actually uses
(`auto.hpa_target_pct` of the policy, 350% for the shop's default policy). *Run in Auto mode* opens the Live lab.

### 5.2 Timeline

The running Auto run, or a **replay** of the most recent one. The **owner band** under the replica chart is coloured per
time (blue HPA, green FlexaScale); swap icons mark *Auto handoffs*.

### 5.3 The four rule cards

Rule 1 *Controller health*, Rule 2 *Policy confidence*, Rule 3 *SLA risk: capacity first*, Rule 4 *Efficiency*. Each
shows its condition (with the policy's real thresholds), whether it switches immediately or after 2 consecutive steps,
and how many decisions it decided in this run (and the share).

### 5.4 Per-service ownership table

| Column | Meaning |
|---|---|
| **Service** | Deployment name |
| **Decision · rule · logged reason** | The owner chosen in the last step (FlexaScale / HPA), the rule that chose it, and the operator's own sentence, e.g. "CPU 92% ≥ 60%; HPA would scale to 3, FlexaScale proposes 2" |
| **FlexaScale → / HPA →** | The two **recommendations** (replica counts). These are *not* actions |
| **Desired / Ready** | What Kubernetes reports: the applied result |
| **CPU %, Mem %** | Telemetry of the latest sample |
| **Latency / SLO** | Mean latency and the service SLO ("—" when no per-service SLO is configured) |
| **Conf.** | The policy's probability for its action |
| **Telemetry** | fresh / stale / missing |
| **Last change** | Time and direction of the last ownership change |

**Recommendation vs action, with an example.** Row: `order-service · HPA · sla_risk · FlexaScale → 2 / HPA → 4 ·
Desired/Ready 4/3`. FlexaScale *recommended* 2 and HPA *recommended* 4; HPA owns the service, so HPA's decision was
applied: Kubernetes now wants 4 replicas, 3 are ready, 1 is starting. FlexaScale's "2" was never sent anywhere.

### 5.5 Ownership changes and configuration

* **Ownership changes:** every logged hand-off (time, new owner, reason). Fallback events also appear here.
* **Configuration:** the `auto:` block in force: latency risk ratio, CPU risk %, switch dwell steps, take-over and
  hand-back confidence, HPA target ± tolerance, and whether the configuration is valid.

**Controller health** is visible in three places: the header chips (Prometheus), the Live-lab ownership card (operator
step advancing) and the Telemetry column (fresh/stale/missing).

---

## 6. The Live Autoscaling Timeline

The standout visualisation: it shows actual Kubernetes scaling while the load runs.

### 6.1 Controls

* **Service selector**: *All services (total)* or one service.
* **Window**: 1 min, 5 min, 15 min, All (live) — or *Run* (whole run) in a replay.
* **CPU / mem**: adds CPU and memory lines (for one service).
* **Pause / Resume**: freezes the view; data keeps arriving and appears when you resume. The chart never resets on
  refresh; new samples are appended.
* **Replay controls** (finished runs): **Play/Pause**, speed **1× / 4× / 16×**, and a **scrubber** to jump in time
  (shown as +m:ss since the load started).

### 6.2 Panels and axes

1. **Events lane (top):** markers for workload phases (⚡), FlexaScale scale requests (◆), Auto handoffs (⇄), safety
   interventions (▲), fallbacks (red ▲) and SLA-violation stretches (red bars).
2. **Replicas (main chart).** X axis = time; Y axis = replica count (sum over services in *All services*).
   * **White solid line — Desired** (`spec.replicas`): what Kubernetes has been told.
   * **Teal filled area — Ready** (`status.readyReplicas`): what is actually serving.
   * **Green dashed line with circles — FlexaScale proposal**: the policy's own count, before safety. A proposal, not
     an action.
   * **Dotted line — HPA proposal**: the HPA's `status.desiredReplicas`, or (when the HPA is frozen) the HPA-rule
     estimate from the same telemetry, labelled as an estimate.
   * **▲/▼ green/red triangles — Scale-up / down (observed)**: drawn where *desired* actually changed.
   * **Owner band** beneath: blue = HPA, green = FlexaScale, per time.
3. **Traffic:** Locust requests/s and users (dashed); failures in red. For one service: its Prometheus request rate.
4. **Latency:** end-to-end Locust p50 and p95 with the SLO line (1000 ms) and red hatching where violated; for one
   service: its mean and p95 latency.

**Hover** anywhere: a tooltip with the timestamp, elapsed time, desired/ready, proposals, owner, users, req/s,
p50/p90/p95/p99, CPU/memory and the events at that moment.

**Gaps** mean "no telemetry recorded"; nothing between samples is interpolated or invented.

### 6.3 Reading a real scale-up

1. Traffic panel: the flash-sale phase begins (⚡ "flash_sale_spike → 40 users"), req/s climbs.
2. A few seconds later CPU rises (CPU / mem on).
3. *FlexaScale owner:* the green dashed proposal steps up (e.g. 1 → 3) — still only a proposal.
4. A **◆ scale request** appears in the events lane: FlexaScale sent the change (safety approved it).
5. The **white desired line** steps up and a **▲** appears: Kubernetes accepted it.
6. About 10 s later the **teal ready area** rises to meet the white line: pods are ready.
7. Latency falls back under the SLO line.

Under *native HPA* the same story has no ◆ markers: the dotted HPA line moves first, then desired and ready.

### 6.4 Reading a scale-down

Traffic drops → CPU falls → after the cooldown (FlexaScale 30 s) or the stabilisation window (HPA 300 s by default) the
proposal steps down by 1 → ◆ → desired ▼ → ready follows immediately (terminating pods stop being ready at once).

### 6.5 Proposed vs applied

* Proposal = green dashed line / "Policy" events / "would propose" in shadow mode. **Not** an action.
* Applied = ◆ scale request + desired line change + ▲/▼. Only these changed the cluster.
* If the proposal moves but desired does not, the step was blocked (see Safety markers: cooldown, readiness, budget)
  or the service was owned by HPA.

---

## 7. Comparison page

### 7.1 Compared with

* **Native HPA (default)** — HPA as installed (70% target, 300 s scale-down window).
* **Native HPA, tuned (fair baseline)** — the calibrated HPA (pre-registered block studies only).

### 7.2 Paired benchmark card

* **Candidate** dropdown: each FlexaScale model/mode with recorded pairs (e.g. "v9 (Auto mode) · 11 pairs").
* **Verdict badge:** *Beats HPA on cost*, *Beats HPA on performance*, *On par / inconclusive*, *Worse than HPA*, or
  *Preliminary* (< 6 pairs). The rule is printed under the tiles.
* **Tiles:** mean Δ and 95% CI for Replica-hours, Cost, p95 latency, Failure rate (percentage points), Throughput.
  Negative = FlexaScale lower. A CI that crosses 0 means "no proven difference".

### 7.3 By scenario

Per scenario: each pair's Δ (dots) and the mean (bar) for the selected metric; "2/2 agree" means both pairs point the
same way.

### 7.4 Pairs table

Every comparable pair: scenario, HPA run, FlexaScale run, Δ replica-hours, Δ p95, Δ failures, Δ throughput.

### 7.5 Experiment history and manual comparison

Pick a **Base** (usually native HPA) and a **Cand.** (candidate) of the same scenario; a full comparison table appears
with throughput, total requests, failure rate, **p50/p90/p95/p99**, SLA-violation time and fraction, recovery
(longest violation), CPU, memory, average/peak replicas, replica-hours, vCPU/GiB-hours, CPU allocation efficiency, cost,
scaling events and oscillations. If the runs are not comparable (different users/duration, unsettled start, incomplete),
the issues are listed and **percentages are hidden**.

**What makes a result good:** lower replica-hours/cost *with* p95, failures and SLA time not worse — and consistent
across pairs (CI not crossing 0).

---

## 8. Service topology

* **Nodes** = services (box colour stripe = owner, CPU %, replicas, a red border when over the SLO).
* **Edges** = caller → callee from the policy's `topology` (the same graph the GNN uses).
* **Click a node:** owner, replicas ready/desired, HPA range, CPU, memory, req/s, mean / p95 latency (with p90 and p99),
  missing metrics, and its callers and callees.
* **Service health** = telemetry fresh, ready = desired, CPU not saturated, latency within SLO.

---

## 9. Models page

* **Deployed policy & inference:** artifact path; policy type (PPO + graph network, 2 message-passing rounds); actions
  (−1 0 +1 +2 +3); observation (v3, 10 unit-free inputs per service); **topology compatibility** ("16 services ≤ 20
  graph slots: every service, real call graph"); **inference (operator)**: "loaded · observe · step 7" when an operator
  is running, or the load error; **loaded model sha256** (proves which file is running); **fallback** (CPU heuristic if
  the model cannot load; live mode refused).
* **Held-out simulation tables (v4–v6):** 300 paired test episodes per version: reward/step, SLO violations, average
  replicas, CPU, changes/step, each ± 95% half-width. A simulator result does not prove live performance.
* **Model cards:** one per model. For v7/v9: model, training (agent-steps, minutes, device — v9 trained on an RTX 3050
  GPU), simulator (the application twin), actions, observation, reward weights, selected run, validation reward and
  whether it **passed the gate**.

---

## 10. Experiments (results and history)

* **Filters:** controller, scenario, search by id or block label (e.g. `v9-b04`, `verify-auto`), and **valid only**.
* **Validity:** a run is valid when it completed its whole load window, started from settled minimum replicas, cleaned
  up safely and never ran on battery. Otherwise the first reason is shown (hover for all).
* **Select a run** to see its configuration (controller, policy, model, scenario, users, duration, initial replicas,
  HPA settings), the whole-run result (p50/p90/p95/p99, failures, replica-hours, cost), cleanup, and a **replay** of its
  timeline.
* **Finding the best FlexaScale scenarios:** filter controller = FlexaScale or Auto and *valid only*, then use the
  Comparison page's *By scenario* chart to see where the pairs favour FlexaScale (e.g. flash sale against default HPA).
  Invalid runs are kept in `reports/experiments_invalid/` and demo runs in `reports/experiments_demo/`; they never
  enter a comparison. The curated, explained results are in `results/RESULTS.md`.

---

## 11. Practical operating examples

All examples assume `./fsctl start` printed READY and http://127.0.0.1:8090/ is open.

### 11.1 Steady browsing workload (native HPA)

1. Live lab → *Native HPA*, shadow mode ticked.
2. Scenario *Steady browsing*, users 25, spawn 5, duration 300, *Comparable start* ticked → **Start**.
3. Wait through *preparing* (up to ~6 min if a run just ended), then watch the traffic panel rise to 25 users.
4. Expect most services to stay at 1 replica. The Policy panel shows what FlexaScale *would* do.

### 11.2 Flash-sale spike

Scenario *Flash-sale spike*, 25–40 users. Watch for the ⚡ "flash_sale_spike" marker at 25% of the duration, the CPU
rise on catalog/order/inventory, scale-ups, and the drop back at 65%.

### 11.3 HPA experiment

As 11.1 with *Flash-sale spike*. Afterwards: Experiments → the run → replay. Desired changes are labelled "owner: HPA".

### 11.4 FlexaScale experiment

Mode *FlexaScale*, policy *Default*, same scenario/users/duration as the HPA run. During the run: the ownership card
says *Lease held by FlexaScale*, the services table shows HPAs "frozen; was 1–10", ◆ scale requests appear. After the
run the cleanup line must say *native HPA ownership verified*.

### 11.5 Auto experiment

Mode *Auto*. Open the Auto mode page during the run: the table shows each service's owner, rule and reason. To see
mixed ownership on demand, choose policy *verify_sla_risk* (a controlled verification configuration: services above 60%
CPU whose HPA would add more replicas go to HPA).

### 11.6 Comparing results

Comparison → *Experiment history*: tick *Base* on the HPA run and *Cand.* on the FlexaScale run of the same scenario →
read the table (green = better, red = worse). For a statistical verdict you need ≥ 6 pairs (the paired benchmark card).

### 11.7 Viewing actual scaling

Live lab timeline → select a service (e.g. *order-service*) → window *All*. Follow 6.3: proposal → ◆ → desired ▲ →
ready.

### 11.8 Recovering safely after a failed experiment

1. Look at the run's error in the Live lab (red note) and the event log.
2. Press **Stop** if it is still *running*.
3. Run `./fsctl stop` — it restores every frozen HPA and checks the Lease. Then `./fsctl start`.
4. If `fsctl status` still shows a Lease held by a dead process: `./fsctl stop --force-release-lease`.
5. Check Overview → Alerts is "All clear".

---

## 12. Troubleshooting

| Problem | What you see | What to do |
|---|---|---|
| **Metrics are missing** | "—" values, alert "No CPU telemetry for any service" | Prometheus chip red? → `./fsctl start` (restarts the port-forward). Prometheus up but no data → check targets at http://localhost:9090/targets; after a Minikube restart wait 1–2 min |
| **Latency unavailable** for a service | "no requests" | The service genuinely served nothing in the last minute (e.g. user-service when nobody logs in). "—" instead means its metrics endpoint is not scraped |
| **Latency shows "≥ 10000"** | ≥ sign | The percentile is beyond the largest histogram bucket (10 s); the service is badly overloaded |
| **Pods are not ready** | Ready < desired for long, alert "replicas starting" | `kubectl -n flexascale-apps get pods`; `kubectl describe pod …` for Pending (memory) or CrashLoopBackOff; reduce users |
| **HPA does not scale** | Desired flat while CPU is high | HPA frozen? (services table "frozen") → a FlexaScale run owns it, or a frozen HPA was left behind → `./fsctl stop`. Otherwise check `kubectl -n flexascale-apps get hpa` (TARGETS must not be `<unknown>`; metrics-server needs ~1 min) |
| **FlexaScale does not make decisions** | Policy panel empty, ownership card "No operator running" | The run's `operator.log` in `reports/experiments/<id>/`; model load error is shown on the Models page; "lease_unavailable" means another controller holds the Lease |
| **Auto selects HPA** | Owner HPA, rule shown | Read the rule: *controller_health* (telemetry missing/stale, no Lease, no model), *policy_confidence*, *sla_risk* (CPU ≥ risk level and HPA wants more). That is the designed safe behaviour |
| **Auto selects FlexaScale** | Owner FlexaScale, rule *efficiency* | Normal: no risk and the policy is healthy. A switch to FlexaScale waits 2 steps ("waiting 1/2 steps") |
| **A scaling action is rejected** | Safety ▲ markers, reasons in the log | Reasons: `scale_up_cooldown`, `scale_down_cooldown`, `scale_up_waiting_for_readiness`, `scale_up_blocked_replica_budget`, `scale_down_blocked_cpu/memory/slo`, `restore_replica_bounds`, `telemetry_unavailable`. Each is a guard working as designed |
| **Dashboard data is stale** | Telemetry chip amber/red | Lab server stopped? `./fsctl status`, then `./fsctl start`. A hard browser refresh loads a rebuilt dashboard |
| **Locust fails** | Run *failed* soon after start; error "could not resolve the application URL" or many failures | Shop reachable? `curl http://$(minikube ip -p flexascale)/api/system/status`; see `reports/experiments/<id>/locust.log` |
| **Prometheus unavailable** | Prometheus chip red, Start refused ("Prometheus not reachable") | `./fsctl start`; check `kubectl -n flexascale-monitoring get pods` |
| **Controller ownership is stuck** | Alert "HPA left frozen" or "Lease held outside an experiment" | `./fsctl stop` (restores HPAs). Lease still held by a dead process → `./fsctl stop --force-release-lease`. Never delete HPAs by hand |
| **FlexaScale fell back to native HPA** | Red fallback banner | The operator died or hung; the watchdog already restored every HPA. The run continues under HPA and is not valid as a FlexaScale result; check `operator.log` |
