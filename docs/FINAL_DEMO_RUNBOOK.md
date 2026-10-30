# FlexaScale Final Demo Runbook

Target length: 12–15 minutes live, plus questions. Updated 2026-10-29 for the second laptop (Windows 11, Docker Desktop, Minikube), the `fsctl` launcher and the Live Autoscaling Timeline. The same steps work on Linux with `./fsctl`.

## 0. Before the session (5 min, once)

* **Charger plugged in.** On battery the CPU slows down and every run becomes invalid for comparisons (the lab records AC/battery every 5 s).
* **Docker Desktop running** (whale icon steady). Close heavy jobs (model training, builds): they compete with the cluster for CPU.
* **Display stays on.** This laptop uses Modern Standby: when the screen turns off, the machine stands by and a running experiment freezes. During a talk the screen is on anyway; for long unattended batches `scripts/run_plan.py` keeps the display on by itself.
* Preflight (changes nothing, ~10 s):

```powershell
.\fsctl start --check
```

If it fails, the printed `Fix:` line says what to do; the troubleshooting table is at the top of RUNNING.md.

* **Which FlexaScale policy?** On the second laptop (Windows) use the default policy (v9). On the first laptop (Fedora)
  choose **FlexaScale policy → v7** in the Live lab: v9 was fitted to the second laptop and holds every service at its
  minimum on the first one (checked live 2026-10-31, `results/verification/`).

## 1. Start (one command)

```powershell
.\fsctl start --demo          # Linux/macOS: ./fsctl start --demo
```

Expected ending (≈30 s when Minikube is running, 2–4 min after a reboot):

```
READY in 31 s
  Control center : http://127.0.0.1:8090/
  Shop           : http://127.0.0.1/   (demo login: demo@flexascale.io / CustomerPass123!)
  Prometheus     : http://localhost:9090/
  Grafana        : http://localhost:3000/
```

Running it twice is safe: healthy processes are reused. On Windows the shop is reached through a managed `minikube tunnel` (the Minikube IP is not routable from Windows); the launcher starts it.

## 2. Open two browser windows

* Left: **http://127.0.0.1:8090/** (control center). Dark theme by default; the sun/moon button switches to light (better on some projectors).
* Right: **http://127.0.0.1/** (the shop). Log in with the demo account.

## 3. Demonstration sequence (the eight steps)

For a live demo, untick **Comparable start** so a run starts at once (otherwise it waits until 5.5 min after the previous run's load, so HPA's memory of the last run has expired), and say that demo runs are not benchmark runs. After the demo, move demo runs from `reports/experiments/` to `reports/experiments_demo/`.

| Step | Say | Do / show |
| :--- | :--- | :--- |
| 1. Cluster and live telemetry | "Real cluster state, refreshed every 5 s; missing values show as '—', never estimated." | **Overview**: status pills (telemetry age, cluster, Prometheus), active controller, replicas, mean CPU, estimated cost rate (labelled as an estimate), the compact timeline recording cluster state. **Service topology**: the 16 discovered services on their call graph, coloured by owner; click order-service to show its callers, callees and live latency. An idle service says "no requests", not 0 ms. |
| 2. Generate a workload | "Locust drives the shop with realistic user journeys." | **Live lab** → scenario **Flash-sale spike**, 25 users, spawn 5, 300 s. While it runs, use the shop: search, add to cart, check out (checkout calls pricing, shipping, fraud, payment, inventory, notification). |
| 3. Native HPA run | "First the baseline: Kubernetes' own HPA." | Mode **Native HPA** (shadow mode on) → **Start**. Point at the **Live Autoscaling Timeline**: traffic jumps at the flash sale, latency rises toward the SLA line, the hatched band marks SLA violation, desired replicas step up (green ▲ = observed scale-up), ready follows. The dashed green line is what FlexaScale *would* do (shadow mode: nothing applied). |
| 4. FlexaScale run, comparable conditions | "Same scenario, same settings, now the learned policy decides." | When it completes: mode **FlexaScale** → **Start**. On the timeline: the ownership strip turns green (FlexaScale holds the Lease and freezes each HPA before scaling), filled green dots are scale requests actually sent, the dotted blue line is the HPA rule's estimate on the same telemetry. Select one service (e.g. order-service) to show its own requests/s, latency and SLO from Prometheus. |
| 5. Auto mode | "Auto chooses per service, every step, with logged rules." | Mode **Auto** → **Start**, then the **Auto mode** page: each service's owner, the rule (health → confidence → SLA risk → efficiency) and the reason; the ownership strip on its timeline shows handoffs. Point at a service handed back to HPA on SLA risk. |
| 6. Live scaling graph and real replica changes | "Nothing on this chart is invented." | Back on the timeline: hover for the tooltip (time, desired/ready, both proposals, owner, traffic, p95); **Pause** freezes the view while data keeps arriving; after the run ends the chart becomes a labelled **REPLAY** with play/speed controls. Optional terminal proof: `kubectl -n flexascale-apps get hpa,deploy -w`. |
| 7. Compare SLA, latency, resources and cost | "The comparison is paired and its rule was fixed before the runs." | **Comparison**: the pre-registered study against the *tuned* HPA (POLICY_V9; 350% CPU target, 60 s window, chosen by the calibration rule) and the default HPA: replica-hours, estimated cost, p95, failures with 95% intervals and the verdict. Expect **v9 and Auto: on par / inconclusive** against HPA-tuned (replica-hours +0.3% / +0.2%), and default HPA **worse** than HPA-tuned (+10.6%). Say it plainly: the learned policy matches a well-tuned HPA here and does not beat it. **Experiments**: open any run → configuration, validity checks (complete, settled start, cleanup verified, AC power) and its replay; *Use as baseline* → *Compare with baseline* for a run-vs-run table. |
| 8. Results and limitations | "What we can and cannot claim." | Read the verdict as measured (docs/POLICY_V9.md §6/§8, docs/V7_REPORT.md for the first laptop). Limitations: single-node Minikube, 25 users, 300 s runs, run-to-run noise as large as most effects, costs are list-price estimates, the tuned HPA uses one CPU target for all services. |

Short on time? Steps 1, 3, 4 (or 5) and 7.

## 4. Showing actual scaling

* Timeline legend: solid white = desired replicas (`spec.replicas`), cyan area = ready replicas, dashed green = FlexaScale's proposal (not an action), filled green dot = a scale request sent, dotted blue = HPA's proposal (its `status.desiredReplicas` while it owns the service, the rule estimate while FlexaScale does), ▲/▼ = observed scale-up/down, strip = owner, hatched = SLA violated, event lane = workload phases, scale requests, Auto handoffs, safety interventions.
* Event log (below the timeline in the Live lab): **Policy** (proposal, not applied), **Scale request** (sent), **Replica change** (Kubernetes changed desired replicas, with the owner), **Ready**, **Auto mode** (handoff with rule and reason).
* Raw data: `reports/experiments/<run>/run.json`, `telemetry.csv`, `decisions.jsonl` (every decision with features, proposal, guards and owner).

## 5. Troubleshooting during the demo

| Problem | Action |
| :--- | :--- |
| Start returns an error | The message says why (lease held, Locust still running, Prometheus down). `.\fsctl stop`, then `.\fsctl start`. |
| Experiment stuck in *preparing* | Comparable start is on (waits for HPA's 5-minute memory to expire). Untick **Comparable start**, and say the run is then not comparable. |
| Shop unreachable | The tunnel died: `.\fsctl start` restarts it. |
| Stop button locked | The run was started elsewhere (a batch). Tick the lock checkbox only to really end it. |
| Charts empty | Samples arrive every 5 s after the workload starts; check the telemetry pill. |
| Anything looks unsafe | **Stop**, or `.\fsctl stop`: both restore every HPA's original bounds and release the Lease. |

## 6. Safe cleanup

```powershell
.\fsctl stop                  # idempotent; leaves Minikube, deployments and data untouched
.\fsctl status                # optional: "native HPA owns scaling"
```

Full teardown (destructive, asks for confirmation): `./scripts/teardown_cluster.sh flexascale --delete` (Git Bash).
