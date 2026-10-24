# FlexaScale Final Demo Runbook

Target length: 12–15 minutes live, plus questions. Everything below was run on this machine on 2026-10-22.

## 0. Before the session (5 min, once)

```bash
cd ~/flexascale
./scripts/start_review.sh --check     # preflight only, changes nothing (~5 s)
```

If it fails, follow the printed `Recovery:` line or the troubleshooting table in RUNNING.md (Quick Start).

## 1. Start (one command)

```bash
./scripts/start_demo.sh               # = ./scripts/start_review.sh --demo
```

Expected ending (≈15 s when Minikube is already running; 2–4 min if it had to start):

```
== 8/8 Live Autoscaling Lab dashboard
  [ OK ] lab started (log: .runtime/logs/lab.log)
  [ OK ] dashboard UI served

READY in 14s
  Presentation dashboard : http://127.0.0.1:8090/
  Shopping application   : http://192.168.49.2/   (demo login: demo@flexascale.io / CustomerPass123!)
  Prometheus             : http://localhost:9090/
  Grafana                : http://localhost:3000/
```

Running it twice is safe: healthy processes are reused, never duplicated.

## 2. Open two browser windows

* Left: **http://127.0.0.1:8090/** (FlexaScale Live Autoscaling Lab)
* Right: **http://192.168.49.2/** (the shop). Log in with the demo account.

## 3. Demonstration sequence

| Step | Say | Do / show |
| :--- | :--- | :--- |
| 1 | "This is real cluster state, not a simulation." | Header: cluster and Prometheus health. Services table: 7 managed services, `postgres` and `shopping-frontend` excluded with reasons, every service owned by **Native HPA**, lease free. |
| 2 | "First the baseline: Kubernetes' own HPA." | Controller **Native HPA**, scenario **Flash-sale spike**, **25 users**, spawn 5, 300 s, *shadow mode* on → **Start**. Do not exceed ~30 users on this laptop: the Minikube node has 6 GiB. |
| 3 | "While Locust generates load, I use the shop normally." | In the shop: browse, add to cart, check out. Manual traffic is independent of Locust. |
| 4 | "Watch traffic, latency and the HPA reacting." | Throughput and p95 charts, replica chart stepping up, timeline: *Traffic phase 'flash_sale_spike'*, *Replica change (owner: HPA)*, *Ready*. Shadow *Policy* entries show what FlexaScale would have done, with confidence. |
| 5 | "Now the same load under FlexaScale." | After completion: controller **FlexaScale**, same settings → **Start**. Timeline: *Ownership: operator holds the controller lease; HPAs are frozen per service*, then *Scale request … (scale_up, confidence 0.9, ppo_neighborhood)* → *Replica change (owner: FlexaScale)* → *Ready*. |
| 6 | "Safety: proposal ≠ request ≠ actual." | Point at a low-confidence step: *controller hpa; safety: confidence_below_activation*. Show the services table: the HPA column shows "frozen; was 1–10" only for services FlexaScale owns. |
| 7 | "Compare." | **Results & comparison** → baseline = HPA run, candidate = FlexaScale run. Read throughput, p95/p99, SLO-violation seconds, replica-hours and cost proxy together. Be upfront: in the recorded runs FlexaScale used 58–98% more replica-hours and was not faster. The system and its safety work; the learned policy over-provisions (reports/live_benchmark_report.md). |
| 8 | "Portability." | App selector → *Synthetic bookstore (5 services)*: different names, 5 services, HPAs named `*-autoscaler`, 2 services without HPA. The same operator and model, no code change (`config/apps/bookstore.yaml`). |
| 9 | "Clean shutdown." | `./scripts/stop_review.sh`. It prints *native HPA owns every managed Deployment; FlexaScale holds no lease*. |

Short on time? Do steps 1, 5, 6 and 7, using a stored HPA run from Results as the baseline.

## 4. Showing actual scaling

* Timeline kinds: **Policy** (model proposal, not applied), **Scale request** (sent to Kubernetes), **Replica change** (desired replicas changed, with the owner), **Ready** (pods ready).
* Terminal, if asked: `kubectl -n flexascale-apps get hpa,deploy -w`, and `kubectl -n flexascale-apps get lease flexascale-shopping -o yaml` during a FlexaScale run.

## 5. Troubleshooting during the demo

| Problem | Action |
| :--- | :--- |
| Start button returns an error | The message says why (lease held, Locust still running, Prometheus down). `./scripts/stop_review.sh`, then `./scripts/start_review.sh`. |
| Experiment stuck in *preparing* | For a comparable start it holds the HPAs at their minimum until 5.5 min have passed since the previous run's load ended (HPA downscale window). Untick "Reset replicas" to skip this, and say the run is then not comparable. |
| Cluster becomes slow / API timeouts | Too many replicas for the 6 GiB node. **Stop** the run, wait for `kubectl get --raw /readyz`, then `./scripts/stop_review.sh` (restores frozen HPAs from their annotations). |
| Charts empty | Samples arrive every 5 s after the workload starts. Check Prometheus in the header. |
| Shop page errors right after a cluster restart | Frontend nginx DNS race: `kubectl -n flexascale-apps rollout restart deploy/shopping-frontend`. |
| Anything looks unsafe | **Stop**, or `./scripts/stop_review.sh`. Both restore every HPA's original bounds and release the lease. |

## 6. Safe cleanup

```bash
./scripts/stop_review.sh              # idempotent; leaves Minikube, deployments and data untouched
./scripts/review_status.sh            # optional: confirm "SAFE (native HPA owns scaling)"
```

Full teardown (destructive, asks for confirmation): `./scripts/teardown_cluster.sh flexascale --delete`.
