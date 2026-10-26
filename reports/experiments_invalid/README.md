# Invalid runs (kept for transparency, excluded from all reports)

| Run | Reason |
| :--- | :--- |
| 20261024-154539-shopping-hpa-checkout_heavy | Host laptop suspended (systemd-logind) at 15:52:34, ~50 s into the workload, and resumed at 16:51. Load, metrics and controller were frozen for ~58 min. Rerun under `systemd-inhibit`. |

## 20261025-043714-shopping-hpa-checkout_heavy (v5 batch, repeat 2)

Completed, but its FlexaScale pair never ran: at 04:57, as this run ended, pods across the cluster restarted after repeated memory-cgroup OOM kills of the app services, and the Prometheus port-forward died, so the next 10 runs were refused at preflight. Rule applied (before any rerun result was seen): a pair counts only if both arms complete on a healthy cluster, so the whole checkout_heavy pair of repeat 2 was rerun. The 10 preflight refusals remain in reports/experiments as failed runs.

## 20261025-050040-shopping-hpa-checkout_heavy (v5 batch, repeat 2, rerun)

The host suspended at 05:02:45 and then went down at about 05:09, without a clean shutdown, during this run. Found later (2026-10-26) in the laptop's charge history (`/var/lib/upower`): it had been on battery since 02:04:50 and reached 0% at 05:07:49, so the suspend and the shutdown were the battery running out. It was restarted at 11:31. The run has no run.json and is excluded. Same rule as above: the whole checkout_heavy pair, and the four remaining pairs of repeat 2, were rerun after `./scripts/start_review.sh` reported a healthy cluster.

The 10 preflight refusals of 04:57–04:58 (each about 10 s, "Prometheus not reachable") were moved here from reports/experiments on 2026-10-25 for clarity. They never had a workload.

## 20261025-232041-shopping-hpa-checkout_heavy (16-service shop, sanity check)

The first run on the 16-service shop. It was a smoke test, not a benchmark run: 4 PPO training processes were using all 16 host cores at the time, and order-service was OOM-killed repeatedly (4 replicas, 256 MiB limit). That was caused by one HTTP client per downstream call, fixed in order-service/cart-service/api-gateway 1.2. Result for reference: 13.2 req/s, 10.6% failures, p95 2.7 s, peak 30 replicas.

## 2026-10-25 19:29–19:52: first HPA-vs-Auto batch (36 runs; 1 completed, 35 refused)

The host clock had been running about 5.5 hours fast (NTP off, RTC in local time). It was corrected at 19:21. Service-account tokens issued while the clock was wrong were then rejected ("Unauthorized"). After the first run, the ingress controller could no longer read EndpointSlices and kept routing to a deleted api-gateway pod. Every later run was refused at preflight because the configured data reset (`PUT /api/inventory/{id}`) timed out (log: `logs/live_auto_batch_failed.out`). The single completed HPA run (steady_browsing, 19:29) lost its Auto pair and is excluded under the pairing rule. Fix: all system workloads restarted, a full Minikube restart to clear in-memory clock state (HPA stabilisation history, leases), and pods created with future timestamps recreated. The batch was then rerun from scratch.

Also excluded for the same reason: `20261025-192442-shopping-auto-flash_sale` is a 180 s Auto smoke test, not part of the benchmark. It is kept in reports/experiments as the first live Auto-mode run, but it has no HPA pair and its duration differs.

## 2026-10-25 20:02 – 2026-10-26 04:31: overnight HPA-vs-Auto batch (36 runs; 35 completed, 1 failed)

All 36 runs are excluded. The batch itself ran without interruption (log: `logs/live_auto_batch.out`), but the workload was faulty in both arms. `GET /api/orders/user/{id}`, which the load test calls, had no limit. The two load-test users had accumulated 43,380 orders (78,662 items) because the pre-run reset does not delete orders. Every call loaded about 21k orders into Python, and order-service (256 MiB limit) was OOM-killed. Prometheus (`kube_pod_container_status_restarts_total`) shows order-service restarts in nearly every run window from 20:04 to 04:29; `20261026-031931-shopping-hpa-flash_sale` failed at setup because order-service was in CrashLoopBackOff. Working-set memory rose from about 65 MiB to more than 230 MiB within minutes even at under 1 checkout/s, so this was a data-size bug, not a scaling effect. Because the order count only grows, later runs (and the HPA arm, which always runs first within a pair) were not equally exposed, so the pairs are not a fair comparison.

Fix: order-service 1.3 returns the 20 most recent orders (`limit` query parameter, maximum 100). After the fix, memory stayed at 65 MiB over 200 consecutive calls. The batch was rerun from scratch as `logs/live_auto_batch_v2.out`, starting 2026-10-26 04:35.

Earlier batches (including the v5 HPA-vs-FlexaScale batch) used the same unbounded endpoint, with a smaller but growing order table. Prometheus history from before the 2026-10-25 TSDB reset is gone, so their exposure cannot be measured. This is a possible confound, listed in the report limitations.

## 2026-10-26 12:20–13:01: tuned-HPA reference runs (`hpa_fast`, 3 completed, 1 stopped in preparation)

All excluded. The host laptop lost AC power at 11:52:05 (`/var/lib/upower` charge history: "discharging" from 94%), and the CPUs then ran at about 1 GHz on battery against a 4.6 GHz maximum. Every service became about 4× slower, including services with no database (mean latency: recommendation 34 → 144 ms, search 31 → 108 ms, order 200 → 898 ms). Throughput under the same Locust load fell, for example checkout_heavy from 20.2–20.8 to 15.4 req/s. These runs can only be compared with default-HPA runs made on AC power, so the comparison would be invalid. The runner was stopped at 13:00, and the fourth run was stopped before its load began (cleanup verified, HPA behaviour restored on all 16 HPAs). The tuned-HPA question (`docs/POLICY_V6.md` §5.2) remains open.

The last HPA-vs-Auto pair (traffic_drop, repeat 3, 11:55 and 12:07) also ran on battery, with both arms in the same state. It is **kept** in the main result, because the pre-registered exclusion rule covers runs that did not complete on a healthy cluster and both runs completed normally. Including it is the conservative choice: it is the pair with the smallest saving (−0.4%). Without it, over 17 pairs: replica-hours −4.1% (95% CI −6.9 … −1.4), with the same verdict.

## 2026-10-26 13:08–14:46: three tuned-HPA pairs run under outside host load

Excluded under the host-load criterion (`docs/POLICY_V6.md` §5.2, added 16:45 from host measurements only; evidence in `reports/host_load_by_run.csv`, produced by `scripts/check_host_load.py`). In bursts from 13:18 to 14:47, processes on the same laptop that are not part of FlexaScale (among them another project's model-training job, from 14:18) used up to 12 extra CPU cores, and the host was swapping. Normal values today are 0.6–0.9 cores outside Kubernetes for HPA runs and 1.1–1.6 for Auto runs.

| Pair | Default-HPA arm (outside load) | `hpa_fast` arm (outside load) |
| :--- | :--- | :--- |
| traffic_drop | 20261026-130803-shopping-hpa-traffic_drop (1.0 cores) | 20261026-131404-shopping-hpa_fast-traffic_drop (5.6 cores) |
| steady_browsing (repeat 1) | 20261026-140550-shopping-hpa-steady_browsing (5.5) | 20261026-141201-shopping-hpa_fast-steady_browsing (5.4) |
| checkout_heavy (repeat 1) | 20261026-142333-shopping-hpa-checkout_heavy (4.6) | 20261026-143454-shopping-hpa_fast-checkout_heavy (3.9) |

The traffic_drop pair is the single "AC-power pair" that was reported earlier as "tuned HPA −12.5% replica-hours". Only its tuned arm ran under the outside load, so that comparison is withdrawn. The three pairs are rerun once after repeat 2 of the tuned batch. The same check shows that the 13:33 Auto rehearsal (`reports/experiments_demo/`) ran with 6.4 cores of outside load.

## 2026-10-26 19:20–19:39: rerun of the steady_browsing tuned-HPA pair (invalid; the pair is reported as missing)

The laptop was unplugged from 19:25:29 to 19:33:52 (AC adapter state polled every 20 s by the batch monitor). The default-HPA arm `20261026-192013-shopping-hpa-steady_browsing` ran its whole load window (19:26:22–19:31:31) on battery: p95 240 ms against 74–120 ms in the other steady_browsing runs, 1.77 replica-hours against 1.46–1.52. The pair is therefore host-affected (`docs/POLICY_V6.md` §5.2). Its `hpa_fast` arm `20261026-193135-shopping-hpa_fast-steady_browsing` could no longer make the pair valid, so it was stopped at 19:38:44 (cleanup verified) to let the remaining reruns start earlier. Each invalid pair is rerun only once under the batch rule, so the repeat-1 steady_browsing pair is reported as missing.

## 2026-10-27 01:14–01:38: three HPA-tuned calibration runs (docs/POLICY_V7.md §2.1, §3.4)

| Run | Block | Reason (no outcome metric used) | Rerun (valid) |
| :--- | :--- | :--- | :--- |
| 20261027-010839-shopping-hpa_tuned-calibration_steady | cal-150 | on battery for 85 s of its load window (`scripts/check_host_load.py`) | 20261027-022925-shopping-hpa_tuned-calibration_steady (0.89 cores outside Kubernetes) |
| 20261027-012008-shopping-hpa_tuned-calibration_steady | cal-250 | 2.24 cores outside Kubernetes (limit 2.0) | 20261027-024524-shopping-hpa_tuned-calibration_steady (0.92) |
| 20261027-013641-shopping-hpa_tuned-calibration_steady | cal-70 | unclean reboot of the laptop at about 01:38 while the run was still settling; it wrote no data | not needed: the plan resumed at 01:44 with the same run in the same position |

Moved by `scripts/rerun_plan.py`, which also wrote the one-time rerun plan `reports/v7/calibration_plan.reruns.json`.
