# FlexaScale Policy v4: Why v3 Over-Provisioned and What Changed

## 1. The problem

The v3 policy (`models/flexascale_v3`) scaled almost every service up on almost every decision. In the live benchmark it used 58–98% more replica-hours than native HPA and was not faster (`reports/live_benchmark_report.md`).

## 2. Diagnosis (measured, not assumed)

| Evidence | Value |
| :--- | :--- |
| v3 actions on the original simulator's test split (200 episodes, 4,000 decisions) | 99.2% *scale up*, 0.7% hold, 0.1% scale down |
| v3 live decisions (1,316 recorded, shopping app) | 72% *scale up* overall; 77% *scale up* when CPU < 20% of request |
| v3 at live idle (CPU 3%, 1 replica, 0 req/s, no latency samples) | *scale up* with probability 0.925 |

So the policy had collapsed to "always scale up" in simulation already. The live system faithfully executed a bad policy. The safety layer limited the damage (replica budget, readiness waits) but cannot make a bad policy good.

Root causes in the original simulator (`simulator/flexascale_env.py`) and reward:

1. **One absolute latency target (100 ms) for every Alibaba service.** About 9% of trace services are above 100 ms at any provisioning. The only way to shrink their penalty was more replicas, and the SLO penalty (up to −10 per step) dwarfed the cost term (at most −0.5).
2. **All latency was the service's own queueing delay**, so in simulation more replicas always meant lower latency. Real applications have latency that replicas cannot remove: downstream calls and shared dependencies. In the shopping app every service shares one PostgreSQL instance; in the live v3 runs extra replicas made latency *worse* (catalog-service mean latency 29 ms with HPA vs 58 ms with v3).
3. **Raw-unit inputs.** The model saw raw request rates (trace: hundreds to thousands of req/s) and raw milliseconds. A live service at idle (0 req/s, no latency samples) was far outside the training distribution, and the same numbers mean different things in different applications.
4. **A training objective that did not match how the model is used.** Live, the runtime evaluates each service on a 4-service window and uses only the first slot's decision. Training averaged one reward over four services and four action heads, so each decision was credited with the other services' outcomes.

## 3. What v4 changes

| Area | v3 | v4 |
| :--- | :--- | :--- |
| Simulator | `FlexaScaleEnv` | `FlexaScaleEnvV2` (`simulator/dependency_env.py`), same Alibaba demand, same 4-service chain and action space |
| Latency | own queueing only | own queueing + a random fraction of the callee's latency (slot *i* calls slot *i+1*) + latency that replicas cannot remove + (40% of episodes) a shared dependency whose latency grows with total load |
| SLO | 100 ms for every service | per service: 1.2–2.0 × its latency when every service runs at the configured CPU target (70%), so it is attainable by provisioning to the same target the operator is given |
| Traffic | trace only | trace × one app-wide event per episode (spike ×1.5–3, ramp to ×1.5–2.5, drop to ×0.2–0.5, or none) |
| Policy input (per service) | `[cpu %, mem %, replicas, req/s, latency ms]` | `[cpu/request, mem/limit, replicas/max, req-rate trend over 1 min, latency/SLO]`: unit-free, identical in simulation and live |
| Reward | `slo + 0.3 eff + 0.1 stab + 0.5 cost`, SLO penalty down to −10 | same terms, cost weight 1.0, SLO penalty bounded at −3 |
| Training objective | four heads, reward averaged over four services | `control: focal`: the policy decides for slot 0 and is rewarded for slot 0; its downstream services follow an HPA-like rule with 20% random actions |
| Data split | temporal (test episodes were 3–4 steps) | by service: train/validation/test services are disjoint, every episode is the full 30 minutes |
| Live inputs | operator passed raw metrics | operator computes the same unit-free features (`operator/app_operator.py::_policy_inputs`); latency/SLO uses the app's `slo_latency_ms` (per-service override supported) |
| Live timing | a scale-up every 10 s possible | `scale_up_cooldown_seconds: 30`: telemetry is a 1-minute rate scraped every 10–15 s, so the next scale-up waits until the previous one is visible |
| Runtime safety | version implied | observation version read from the model card and cross-checked against the bounds stored in the model; focal models are always evaluated per service (never all heads at once) |

Nothing in the shopping or bookstore application was changed to make v4 look better: same SLO (250 ms), same replica bounds and budget, same scenarios, same users.

## 4. How v4 was trained and selected

The protocol was fixed before any v4 result was seen:

* Reward weights and simulator settings above are fixed; only PPO training settings were varied.
* Every candidate (best and final checkpoint of every run) is scored on the same 200 episodes of the **validation services**. The highest mean reward per step is deployed (`scripts/evaluate_v4.py`).
* The deployed model is then run once on 300 episodes of the **test services** together with the baselines.

Training attempts, all kept on disk:

| Attempt | Setup | Outcome |
| :--- | :--- | :--- |
| A (`models/flexascale_v4_attemptA`) | four heads, reward averaged over four services, 1 env, lr 3e-4, stopped at ~180k steps | Converged to "mostly hold" at ~8 replicas: validation reward −0.42 to −0.52 per step vs −0.15 for the HPA rule. Led to the focal objective. |
| B (`models/flexascale_v4_attemptB`) | focal, 8 envs, lr 1e-4, 500k steps, 3 seeds | Directionally right (scales down at low CPU, up at saturation) but too timid. Best validation reward −0.384 vs −0.279 for the HPA rule. |
| C (`models/flexascale_v4/<run>`) | focal, 8 envs, 1M steps, grid: lr {3e-4, 1e-4} × entropy {0.01, 0.003} × seeds | see section 5 |

Reproduce: `./scripts/train_v4.sh` then `python scripts/evaluate_v4.py`.

## 5. Results

Every number below is from `reports/simulation_evaluation_v4.md` (300 test-service episodes, run once). Live results are in `reports/live_benchmark_report.md`.

Attempt C was first interrupted at ~830k of 1M steps (kept in `models/flexascale_v4_interrupted`, never evaluated) and then rerun to completion. Selected on validation: `lr1e-4_ent0.01_s3/final` (−0.440 per step; the other 7 candidates were −0.441 to −0.508).

| Policy | Reward / step | SLO violation rate | Avg replicas | Avg CPU % |
| :--- | ---: | ---: | ---: | ---: |
| ppo_v4 | −0.425 ± 0.097 | 37.6% | 4.54 | 43.5 |
| hpa_rule | −0.288 ± 0.091 | 40.7% | 2.82 | 63.7 |
| ppo_v3 | −0.861 ± 0.086 | 33.5% | 9.54 | 19.3 |

**What this shows.**

* **v4 no longer collapses to "always scale up".** It uses 52% fewer replicas than v3 (4.54 vs 9.54) on the same episodes. v3 now behaves exactly like `always_up` on this simulator.
* **v4 does not beat the HPA rule.** Paired against HPA on the same episodes, it has 3.0 ± 1.5 points fewer SLO violations but 1.72 ± 0.20 more replicas (+61%), and a lower reward (−0.137 ± 0.039). The pattern is the same in every traffic-event and bottleneck group.
* **v4 changes replicas far less often** (0.07 vs 0.37 per step). It is stable, but slow to give capacity back.

**Live (shop, 25 users, 300 s, one run per arm, `reports/live_benchmark_report.md` §v4).** Over six scenarios v4 used +6% replica-hours relative to HPA on average (range −11% to +22%; v3: +58% to +98%). The mean changes were p95 −2.4%, throughput +4.5% and failure rate −0.5 pp. Per-scenario differences were large in both directions and are not statistically established.

Over-provisioning was reduced, not removed. The protocol fixed the reward and simulator before results were seen, so they were not tuned against the test services afterwards.
