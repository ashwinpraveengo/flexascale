# FlexaScale Final Demo Runbook

Target length: 12–15 minutes live, plus questions. Updated 2026-10-26 for the 16-service shop, Auto mode and the control-center dashboard.

## 0. Before the session (5 min, once)

```bash
cd ~/flexascale
timedatectl | grep synchronized       # must say "yes": a wrong host clock breaks Prometheus and cluster tokens
cat /sys/class/power_supply/BAT*/status   # plug the charger in: on battery the CPU drops to ~1 GHz and every service is ~4x slower
top -b -n1 -o %CPU | sed -n 7,12p          # close other heavy jobs (model training, builds): they slow every service in the shop
./scripts/start_review.sh --check     # preflight only, changes nothing (~5 s)
```

If it fails, follow the printed `Recovery:` line or the troubleshooting table in RUNNING.md (Quick Start).

## 1. Start (one command)

```bash
./scripts/start_demo.sh               # = ./scripts/start_review.sh --demo
```

Expected ending (≈15 s when Minikube is already running; 2–4 min if it had to start):

```
READY in 14s
  Presentation dashboard : http://127.0.0.1:8090/
  Shopping application   : http://192.168.49.2/   (demo login: demo@flexascale.io / CustomerPass123!)
  Prometheus             : http://localhost:9090/
  Grafana                : http://localhost:3000/
```

Running it twice is safe: healthy processes are reused, never duplicated.

## 2. Open two browser windows

* Left: **http://127.0.0.1:8090/** (FlexaScale control center). The sun/moon button switches between dark and light themes. Use light on a projector.
* Right: **http://192.168.49.2/** (the shop). Log in with the demo account.

## 3. Demonstration sequence

A *comparable start* (data reset, every service at its minimum, then a wait until 5.5 min after the previous run's load) is what the benchmark uses. For the live demo, untick **Comparable start** so the run starts at once, and say that this run is a demonstration, not a benchmark run. The benchmark numbers come from the stored runs (step 7). The Comparison page counts any complete run that started at minimum replicas, so after a rehearsal or the demo, move completed demo runs from `reports/experiments/` to `reports/experiments_demo/` to keep the benchmark at its 18 planned pairs.

| Step | Say | Do / show |
| :--- | :--- | :--- |
| 1 | "This is real cluster state, not a simulation." | **Overview**: the status pills (native HPA in control, telemetry age, cluster, Prometheus), 16/16 services reporting, the estimated cost rate (Fargate list prices, labelled as an estimate), the topology of the 16 services coloured by owner, and the alerts panel. Missing values show "—": nothing is estimated. |
| 2 | "First the baseline: Kubernetes' own HPA." | **Live lab** → mode **Native HPA**, scenario **Flash-sale spike**, 25 users, spawn 5, 300 s, *shadow mode* on, *Comparable start* off → **Start**. Do not exceed ~30 users: it is a single-node cluster. |
| 3 | "While Locust generates load, I use the shop normally." | In the shop: search, open a product (reviews and recommendations come from two more services), add to cart, check out. Checkout calls pricing, shipping, fraud, payment, inventory and notification. |
| 4 | "Watch traffic, latency and the HPA reacting." | Throughput and p95 charts, the replica chart stepping up, the timeline: *Replica change … (owner: native HPA)*, *Ready*. The shadow-mode panel shows what FlexaScale would have done, with confidence. Nothing is applied. |
| 5 | "Now Auto mode: FlexaScale only where the rules allow it." | After completion (or **Stop**): mode **Auto**, same settings → **Start**. Open **Auto mode**: every service with its current owner, the rule that decided it (health, confidence, SLA risk, efficiency) and the logged reason. Point at a service handed back to HPA on SLA risk, and at FlexaScale scale-downs. |
| 6 | "Safety: one owner per Deployment, always reversible." | **Live lab** → controller ownership: the Lease is held by FlexaScale. Only services FlexaScale owns have their HPA frozen (min = max), and the original bounds are stored on the HPA. **Stop** restores every HPA and verifies it ("Cleanup verified"). |
| 7 | "The result, measured honestly." | **Comparison**: the paired benchmark *FlexaScale v5 (Auto mode) vs native HPA (default)*. Read the replica-hours, cost, p95 and failure means with their 95% intervals and the verdict. Say that the verdict rule was fixed before the results (`docs/POLICY_V6.md` §3.1). Then switch to *v5*: the RL policy alone used 8% **more** replica-hours. Then *Native HPA, 60 s scale-down (tuned reference)*: 12 pairs, −1.4% replica-hours with 2.3% lower throughput. Say it plainly: a shorter HPA window gives part of the saving; Auto's saving is larger in the point estimate, but the difference is not statistically shown (`docs/POLICY_V6.md` §5.2). |
| 8 | "Why the RL policy alone does not win." | **Models**: v5 is deployed, with inference health, and v6, trained in a simulator matching the live control loop, still lost to native HPA in simulation. The saving comes from Auto's safe, faster scale-down, not from a smarter policy. |
| 9 | "Portability." | App selector → *Synthetic bookstore (5 services)*: different names, HPAs named `*-autoscaler`, 2 services without an HPA. The same operator and model, no code change (`config/apps/bookstore.yaml`). |
| 10 | "Clean shutdown." | `./scripts/stop_review.sh`. It prints *native HPA owns every managed Deployment; FlexaScale holds no lease*. |

Short on time? Do steps 1, 5, 6 and 7.

## 4. Showing actual scaling

* Timeline kinds: **Policy** (model proposal, not applied), **Scale request** (sent to Kubernetes), **Replica change** (desired replicas changed, with the owner), **Ready** (pods ready), **Auto mode** (an ownership hand-over with its rule and reason).
* Terminal, if asked: `kubectl -n flexascale-apps get hpa,deploy -w`, and `kubectl -n flexascale-apps get lease flexascale-shopping -o yaml` during a FlexaScale or Auto run.
* Raw data for any run: `reports/experiments/<run>/run.json`, `telemetry.csv`, `decisions.jsonl` (every Auto decision with rule, inputs and reason).

## 5. Troubleshooting during the demo

| Problem | Action |
| :--- | :--- |
| Start button returns an error | The message says why (lease held, Locust still running, Prometheus down). `./scripts/stop_review.sh`, then `./scripts/start_review.sh`. |
| Experiment stuck in *preparing* | Comparable start is on: it holds the HPAs at their minimum until 5.5 min after the previous run's load (HPA downscale window). Untick **Comparable start** to skip this, and say the run is then not comparable. |
| Stop button locked | The run was started elsewhere (for example a benchmark batch). Tick the lock checkbox only if you really want to end that run. |
| Cluster becomes slow / API timeouts | Too many replicas for the node. **Stop** the run, wait for `kubectl get --raw /readyz`, then `./scripts/stop_review.sh` (restores frozen HPAs from their annotations). |
| Charts empty | Samples arrive every 5 s after the workload starts. Check the telemetry pill in the header. |
| Prometheus rejects samples / "Unauthorized" errors after a laptop sleep | Check the clock (`timedatectl`). See `reports/experiments_invalid/README.md` (2026-10-25 clock incident) for the recovery. |
| Anything looks unsafe | **Stop**, or `./scripts/stop_review.sh`. Both restore every HPA's original bounds and release the lease. |

## 6. Safe cleanup

```bash
./scripts/stop_review.sh              # idempotent; leaves Minikube, deployments and data untouched
./scripts/review_status.sh            # optional: confirm "SAFE (native HPA owns scaling)"
```

Full teardown (destructive, asks for confirmation): `./scripts/teardown_cluster.sh flexascale --delete`.
