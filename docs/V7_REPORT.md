# FlexaScale v7 against a fairly tuned native HPA

This is the reader's summary of `docs/POLICY_V7.md`, which holds the pre-registered rules and a time-stamped running record (§5). Every number below comes from a file in `reports/v7/` or `reports/experiments/`.

## 1. Question

Does FlexaScale beat a **fairly tuned** native HPA on the 16-service shop, under rules fixed before the runs? Earlier versions were compared with the default HPA (70% CPU target, 300 s scale-down window). That baseline over-provisions this lightly loaded shop and is easy to beat.

## 2. The fair baseline: HPA-tuned

The calibration rule (§2.1) was fixed before any calibration run. On a separate workload, the HPA target is the highest CPU target whose latency and failures stay within 10% (and +0.1 pp) of the 70% target. Every target used a 60 s window, with 8 valid runs after one rerun each of two invalid ones.

| CPU target (% of request) | p95 ms | mean ms | failures % | replica-h | meets the rule |
| ---: | ---: | ---: | ---: | ---: | :--- |
| 70 | 205 | 60.2 | 0.336 | 1.569 | yes |
| 150 | 210 | 62.2 | 0.259 | 1.381 | yes |
| **250** | 210 | 61.5 | 0.299 | 1.356 | **yes (selected)** |
| 350 | 230 | 68.0 | 0.340 | 1.357 | no |

At 25 users, HPA-tuned (250%, 60 s) runs at the **floor**: 16 single replicas, 1.356 replica-hours in 300 s. A cost win against it therefore needs fewer replica-hours in at least 4 of 6 scenarios (check C7 of §3.5), which is nearly impossible. The realistic route to "beats" is lower latency at equal cost: a p95 or failure-rate interval below 0, at no more than +2% replica-hours.

## 3. The v7 policy

* **Application twin** (`config/twin/shopping.json`, `src/flexascale/simulator/twin*.py`): fitted to the live runs and checked against live native HPA (replica-hours within about 4%). It was amended once: Locust is closed-loop, so queues are bounded by the waiting users.
* **Policy:** a graph network over the shop's real call graph, deciding one service at a time ("focal" agents with per-service credit). It is warm-started from the best rule of a fixed family, `limit_target(0.6/0.3)`, then fine-tuned with PPO. Imitation needed class balancing, because the rule's own decisions contain almost no scale-ups.
* **Selection** on 40 validation workloads: `focal_bc_s2` scored −3.35, against −4.18 for the rule and −4.40 for HPA 250%.
* **Twin test set T1** (the six live scenarios, 5 seeds each), v7 against HPA 250%: replica-hours +0.6%, p95 344 vs 410 ms. The whole gain is in flash_sale (−385 ms); four scenarios are identical, because both controllers sit at the floor.

## 4. Live evaluation, 12 blocks × 5 arms (§3)

All 60 runs were valid. Verdicts are by the pre-registered §3.5 table, against HPA-tuned (Δ = candidate − HPA-tuned, mean [95% CI] over 12 paired blocks):

| Candidate | Verdict | replica-h | p95 | mean latency | throughput |
| :--- | :--- | ---: | ---: | ---: | ---: |
| FlexaScale-Auto | Beats on performance | +0.2% [−0.3, +0.7] | −21.6% [−33.5, −9.8] | −17.1% [−26.1, −8.0] | +3.2% [+0.3, +6.0] |
| FlexaScale-RL | On par / inconclusive | +0.0% [−0.1, +0.2] | −2.5% [−40.0, +35.1] | −9.5% [−26.5, +7.5] | +2.4% [−0.8, +5.7] |
| FlexaScale-heuristic (rule) | Beats on performance | −0.1% [−0.3, +0.0] | −20.4% [−33.5, −7.3] | −17.3% [−25.2, −9.4] | +3.5% [+0.0, +6.9] |
| HPA-default | Worse | +15.8% [+10.1, +21.5] | +10.4% [−3.4, +24.3] | +7.8% [−3.0, +18.7] | −1.8% [−4.3, +0.7] |

### 4.1 Why this verdict does not stand: an environment confound

The FlexaScale arms were faster **even where their decisions were identical to HPA's**:

* In steady_browsing every arm keeps all 16 services at one replica for the whole run. The FlexaScale arms still had a lower p50 in every 30–60 s window (15–16 vs 17–18 ms).
* In the first minute of every scenario, before any controller has acted, the paired p50 was lower in the FlexaScale arms in 10 of 12 blocks.
* Every shop container, idle ones included, used 10–20% more CPU-seconds in the HPA arms for the same work.

The cause is the laptop's `balanced` power profile, under which the CPU clock follows host load. Live FlexaScale control (lease, HPA freezes, scaling calls) added about 0.55 host cores; the operator process itself uses only 0.12–0.16 cores. That kept the host busier, so the whole shop ran faster in the FlexaScale arms. A setup pilot under the `performance` profile removed the effect: steady_browsing p50 was 8.0 ms in both arms, and FlexaScale's shop CPU per request was even +5% (slower). **The batch's verdict therefore cannot be attributed to FlexaScale's scaling decisions,** and the planned flash-sale study was withdrawn before producing any data.

## 5. Clock-controlled replication (§3.7)

Pre-registered at 20:15 before any of its runs: the same design under the `performance` profile, with arms HPA-tuned, RL, Auto and heuristic (48 runs). The §3.5 verdict applies, plus a parity rule: in steady_browsing, a candidate's shop must not run more than 10% faster per request than HPA-tuned's. **This verdict decides the project's claim.**

All 48 runs were valid. Environment parity held: the candidates' shops were 4.4–5.6% *slower* per request than HPA-tuned's in steady_browsing, so any remaining bias works against FlexaScale.

| Candidate vs HPA-tuned | Verdict | replica-h | p95 | p50 | failures | throughput | e2e SLO-violation |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| FlexaScale-Auto | **On par / inconclusive** | +0.1% [−0.1, +0.2] | +0.1% [−9.3, +9.5] | −1.8% [−9.0, +5.4] | +0.0 pp | +0.0% [−1.2, +1.2] | −5.9 s [−13.8, +2.1] |
| FlexaScale-RL | **On par / inconclusive** | +0.1% [−0.1, +0.2] | +7.2% [−8.1, +22.4] | +0.3% [−8.1, +8.8] | +0.0 pp | −0.3% [−2.1, +1.5] | −1.7 s [−12.1, +8.7] |
| FlexaScale-heuristic | **On par / inconclusive** | −0.0% [−0.1, +0.0] | +4.5% [−6.6, +15.6] | −0.4% [−7.0, +6.1] | +0.0 pp | +0.0% [−1.1, +1.2] | −2.9 s [−7.4, +1.5] |

The arm means (replica-hours 1.361–1.362; p95 274–295 ms; failures 0.20–0.22%) are practically identical. The flash-sale gain the twin predicted did not appear live: Auto's two flash_sale pairs were +34.3% and −9.6% in p95.

## 6. Conclusion

* **FlexaScale v7 does not beat a fairly tuned native HPA on this testbed. Under the rule fixed in advance, it matches it at equal cost.** Neither the learned policy (RL) nor Auto mode is better or worse than HPA-tuned within the noise of 12 paired blocks.
* The apparent win in the first batch (p95 −21.6%) came from the test environment, not from better scaling decisions. Under the laptop's `balanced` power profile, live FlexaScale control kept the host busier, and the whole shop ran faster as a result. Checking for such confounds, and repeating the comparison with them removed, decided the result.
* FlexaScale performs like the best single CPU target found by the explicit calibration (HPA-tuned). It decides per service, logs every decision, and has a safety layer that hands services back to native HPA.
* **Comparisons with the default HPA are also open to the confound.** A CPU-based HPA scales on CPU-seconds, and under `balanced` the HPA arms' shop burned more CPU-seconds for the same work. The batch's +15.8% replica-hours for the default HPA relative to HPA-tuned, and the earlier v6 result (Auto −3.9% against the default HPA, `docs/POLICY_V6.md`), were both measured under `balanced`, with live FlexaScale control in only one arm. They should be re-measured under `performance` before they are relied on.
* **Why there is no win to find here:** at 25 users the shop is lightly loaded. HPA-tuned already runs every service at its minimum for most of each run, and latency is dominated by request paths that more replicas do not shorten. A controller can only win where its decisions differ from HPA's and the difference matters: higher or burstier load, or services whose latency depends on replica count. Finding such a regime, and calibrating HPA fairly in it, is the next experiment. It has not been done.
