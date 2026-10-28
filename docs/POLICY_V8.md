# FlexaScale v8: is there a regime where a learned controller can beat a fair HPA?

**Context.** v7 is on par with a fairly tuned native HPA in a pre-registered, clock-controlled replication (`docs/V7_REPORT.md`). At 25 users the shop is so lightly loaded that HPA-tuned makes 0.2 scaling events per run: every service stays at its minimum and latency barely depends on replicas, so no controller can do better. A difference can only appear at a load where scaling decisions change latency or cost.

**Rules carried over from v7.** Live runs use the `performance` power profile (`docs/V7_REPORT.md` §4.1). Each run's host load, CPU clock and application CPU per request are recorded (`scripts/check_host_load.py`). Exploration runs are labelled `explore-…` and kept in `reports/experiments_demo/`. They are never part of an evaluation, and any evaluation is pre-registered here before its first run.

## 1. Exploration: does latency depend on replicas at higher load?

`calibration_steady` (not an evaluation scenario) at 75 users, 300 s, native HPA at 70% and at 250% (60 s window), one run each. The question is whether the extra replicas of the 70% target buy latency at this load, and for which services. If they do not, no controller can win here either.

### 1.1 Findings (75 users, `calibration_steady`, `performance` profile)

| Configuration | replicas | failures | p95 | mean | req/s |
| :--- | ---: | ---: | ---: | ---: | ---: |
| HPA 250% (scaled nothing) | 16 | 11.07% | 6000 ms | 665 ms | 36.4 |
| FlexaScale-RL v7 (scaled nothing) | 16 | 7.82% | 6000 ms | 582 ms | 37.7 |
| static: api-gateway, cart, order and user at 3 replicas, the rest at 1 | 24 | 1.87% | 2300 ms | 446 ms | 40.9 |

**Mechanism.** cart-service (and, by the same code pattern, other services) runs one uvicorn worker whose `async` handlers call a synchronous SQLAlchemy/psycopg session. Each database call blocks the event loop, so a pod serves about one request at a time while its CPU stays low (0.015–0.025 cores per replica). When the loop is blocked even `/healthz` times out, and cart-service was restarted by its liveness probe. More pods add concurrency, which is why the static configuration helped. A CPU-based HPA cannot see this bottleneck at any CPU target. The v7 twin queues requests on CPU time only, which is why the v7 policy did not learn to scale for it.

### 1.2 Result of the exploration: no regime found where FlexaScale dominates a calibrated HPA

HPA's cost–reliability frontier at 75 users (single runs each, so noisy), with the FlexaScale candidates:

| 75 users, calibration_steady | replica-h | failures | p95 | mean |
| :--- | ---: | ---: | ---: | ---: |
| HPA 250% | 1.35 | 11.07% | 6000 ms | 665 ms |
| **HPA 70%** | **1.69** | **2.66%** | 2900 ms | 480 ms |
| HPA 35% | 2.06 | 4.12% | 4100 ms | 529 ms |
| HPA 20% | 3.10 | 3.41% | 3000 ms | 546 ms |
| FlexaScale latency rule | 3.59 | 2.96% | 2400 ms | 489 ms |
| FlexaScale-RL v7 | 1.35 | 7.82% | 6000 ms | 582 ms |
| static: gateway, cart, order and user at 3 (not a controller) | about 2.0 | 1.87% | 2300 ms | 446 ms |

HPA at 250% collapses at this load because of a trap: an event-loop-bound service that is choked serves few requests, shows little CPU, and is never scaled. HPA at 70% avoids it. At 75 users cart-service and api-gateway do pass 70% of their CPU request, so HPA scales them, and it buys most of the reliability at the lowest cost. The latency rule is dominated by it: more replica-hours for similar failures. A better allocation of the same replicas (fewer on the database-bound catalog-service, more on order-service) might lower failures by a fraction of a point. That is within the run-to-run noise seen here (the 35% and 20% points are not even monotonic), so 12 blocks could not establish it. **Conclusion: at 75 users, as at 25, a CPU-based HPA calibrated for the load is not shown to be beatable on this testbed.** No evaluation is pre-registered, because no candidate regime survived the exploration.

## 2. Plan (design phase; nothing below is an evaluation yet)

1. **Data:** static-replica runs at 75 users to measure each service's event-loop blocking time per request. This is Prometheus latency and request rate per service at different replica counts.
2. **Twin:** each service gets a per-pod concurrency limit and a blocking time, fitted from step 1. The model is queueing on the event loop, not only on CPU. Its fidelity is checked against the static runs.
3. **Controllers:** a latency-aware rule in the operator, as warm-start teacher and heuristic arm. Then a v8 policy trained in the extended twin, with the v7 reward and selection protocol.
4. **Fair baseline at the new load:** the §2.1 calibration rule of POLICY_V7 at 75 users. Because a CPU-based HPA may not be able to buy reliability at any target, an iso-cost HPA (the target whose replica-hours match the candidate's on the calibration workload) is also considered. The exact choice is fixed in the pre-registration, before any evaluation run.
5. **Pre-registered evaluation** at the new load, with the v7 validity and parity rules.

## 3. Running record

| Time (IST) | Step |
| :--- | :--- |
| 2026-10-28 08:14 | Exploration started (§1): power profile `performance`; calibration_steady at 75 users, HPA 250% then 70% (60 s window). |
| 2026-10-28 08:21 | 75 users, HPA 250%: **no service scaled** (CPU per replica at most 0.116 cores, below every target), yet the shop collapsed. p95 6000 ms, mean 665 ms, 11.1% failures. order-service ran at 2750 ms with 0.015 cores per replica, cart-service at 1155 ms with 0.025, user-service at 1324 ms, api-gateway at 659 ms. cart-service failed its liveness probe (timeouts) and restarted 4 times. The bottleneck at this load is per-pod concurrency, not CPU, so a CPU-based HPA cannot see it at any target. The HPA 70% run could not start: the data reset got a 502 while the shop was recovering. |
| 2026-10-28 08:22 | Exploration: FlexaScale-RL (v7) at 75 users, same workload. Its features include each service's latency inflation, which a CPU-based HPA lacks. |
| 2026-10-28 08:37 | FlexaScale-RL v7 at 75 users: scaled nothing either (16 replicas); 7.8% failures, p95 6000 ms. |
| 2026-10-28 08:45 | Static-capacity test, outside the lab (all HPAs pinned, restored afterwards to min 1 / max 10): api-gateway, cart, order and user at 3 replicas cut failures from 11.1% to 1.9% and p95 from 6000 to 2300 ms, for +50% replicas (§1.1). |
| 2026-10-28 08:51 | Exploration: the latency-aware rule (`controller_rule: latency_target`, new in the operator, tested) at 75 users, calibration_steady. |
| 2026-10-28 09:02 | Latency rule at 75 users: failures 2.96%, p95 2400 ms, mean 489 ms, req/s 39.9, but replica-hours 3.59 (+165% vs HPA 250%). It also scaled catalog and search (7 each), review, inventory and wishlist, whose latency rose because more traffic reached the shared database, not because they lacked pods. The static configuration got 1.87% failures at about +50%. |
| 2026-10-28 09:03 | Exploration: HPA's cost–reliability frontier at 75 users (CPU targets 70, 35 and 20%, 60 s window). Can a lower CPU target buy the reliability a latency-aware controller gets? |
| 2026-10-28 09:42 | Frontier complete (§1.2): HPA 70% gets 2.66% failures at 1.69 replica-hours; no FlexaScale controller dominates it. Exploration closed without an evaluation; power profile back to `balanced`. |
