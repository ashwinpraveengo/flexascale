# FlexaScale Policy v5: HPA-imitation warm start + PPO fine-tuning

## 1. Why

v4 (`docs/POLICY_V4.md`) fixed v3's "always scale up" collapse but scored **below** the HPA-like rule on its own reward and simulator. The rule is a policy the network can represent exactly, so this is an optimisation failure, not a limit of the model. A headroom check on the validation services (100 episodes) showed there is room above the rule:

| Policy (validation services) | Reward / step | SLO violations | Avg replicas |
| :--- | ---: | ---: | ---: |
| Threshold rule, up > 77% / down < 45% | −0.215 | 36.7% | 3.00 |
| One-step-lookahead oracle (sees the true simulator; not deployable) | −0.229 | 36.1% | 2.71 |
| HPA-like rule, up > 77% / down < 63% | −0.333 | 40.6% | 2.73 |
| v4 PPO (200 episodes, from its selection) | −0.440 | 36.2% | 4.78 |

## 2. Method

Nothing in the simulator, reward, observation or action space changed from v4.

1. **Warm start** (`rl/imitation.py`): roll out the HPA-like rule (with 30% random slot-0 actions for state coverage) on the training services. Train the actor with cross-entropy on the rule's action for every slot, and the critic on discounted Monte-Carlo returns, together.
2. **PPO fine-tuning** from that starting point, with small steps (clip 0.1, low learning rate, KL limit) so it improves on the rule instead of overwriting it.

## 3. Protocol (fixed before any v5 result was seen, 2026-10-25)

* Grid (`scripts/train_v5.sh`): learning rate {1e-4, 3e-5} × seeds {1, 2}; clip 0.1, entropy 0.001, target KL 0.02, γ 0.95, 8 envs, 500k steps. The training settings were chosen once and not tuned on validation.
* **Selection:** every candidate (warm-start-only, best and final checkpoint of each run) runs the same 200 validation-service episodes as v4's selection. The highest mean reward per step is selected. If no fine-tuned model beats the warm start, the warm start is selected and reported.
* **Test:** one run on the test services, **fresh seeds 30000–30299** (v4's test used 20000–20299 on the same services; this reuse of the test services is disclosed). Baselines: HPA-like rule, v4, and the best threshold rule *chosen on validation* (up > 77 / down < 45), so that "beats HPA" is not just "found a better threshold".
* **Live:** the same six scenarios as v4, 25 users, 300 s, alternating with HPA, **two runs per arm** so run-to-run variation is visible. Everything reported as measured.

## 4. Results

### 4.1 Selection (validation services, 200 episodes each)

Each fine-tuned run beat its own warm start (by 0.03 to 0.07 reward per step). Selected: `lr3e-5_s2/final` (−0.226; its warm start scored −0.291). Full list: `logs/evaluate_v5.out`.

### 4.2 Test (test services, 300 paired episodes, seeds 30000–30299)

Full tables: `reports/simulation_evaluation_v5.md`. ± is a 95% confidence half-width on paired differences (v5 minus baseline, same episodes).

| v5 vs | Δ reward / step | Δ SLO violation rate | Δ avg replicas | Episodes v5 better |
| :--- | ---: | ---: | ---: | ---: |
| HPA-like rule | **+0.064 ± 0.031** | **−0.034 ± 0.009** | +0.44 ± 0.08 | 43% |
| Tuned threshold rule 77/45 | −0.048 ± 0.013 | +0.006 ± 0.004 | +0.14 ± 0.08 | 23% |
| v4 | +0.200 ± 0.027 | −0.003 ± 0.010 | −1.56 ± 0.20 | 86% |
| v5 with neighbours neutralised | +0.016 ± 0.015 | +0.013 ± 0.004 | −0.45 ± 0.10 | 53% |

What this shows:

* **v5 beats the HPA-like rule** in the simulator. It has higher reward and 3.4 points fewer SLO violations, and it uses 0.44 more replicas on average. It also changes replicas about half as often (0.20 vs 0.39 changes per step). The gain is biggest on ramps (−0.40 vs −0.57 reward).
* **v5 does not beat a better-tuned threshold rule.** The 77/45 rule, chosen on validation, is still ahead. So in this simulator most of v5's gain over HPA could also come from picking better thresholds. That is the honest limit of the result.
* **The dependency-graph input has a small effect.** Neutralising the neighbours costs 0.016 ± 0.015 reward, which is just at the edge of significance. It also changes behaviour: with its neighbours, v5 uses 0.45 fewer replicas and has 1.3 points more SLO violations. The GNN is used, but it is not what drives the gain.
* v5 fixes v4's over-provisioning (1.56 fewer replicas, same SLO violation rate).

### 4.3 Live (shopping, six scenarios × {HPA, v5} × 2 repeats)

12 comparable pairs, all completed, all safe. Full tables and per-run data: `reports/live_benchmark_report.md`. Changes are v5 relative to HPA in the same scenario and repeat. Repeat 2 was partly rerun after the host went down (its battery ran out at 05:07; `reports/experiments_invalid/README.md`).

| Scenario | Δ p95 % (rep 1 / rep 2) | Δ failures pp | Δ throughput % | Δ replica-h % |
| :--- | ---: | ---: | ---: | ---: |
| checkout_heavy | +22.4 / −26.2 | +0.4 / +4.5 | −32.3 / +9.3 | −4.8 / +1.2 |
| flash_sale | −4.2 / +0.0 | +1.1 / −4.2 | +5.3 / +10.7 | +11.2 / +24.3 |
| gradual_ramp | +43.5 / +83.3 | +0.7 / −0.7 | −7.9 / −7.5 | +5.9 / +26.6 |
| payment_degradation | −15.2 / +32.3 | +2.5 / −0.0 | +1.7 / +2.8 | +7.3 / +6.2 |
| steady_browsing | +0.0 / +6.2 | −0.8 / +0.5 | +0.2 / −2.7 | +2.0 / +20.4 |
| traffic_drop | −35.1 / −29.4 | +1.8 / +0.1 | +11.4 / +8.8 | +6.2 / −10.9 |
| **Mean of 12 pairs** | **+6.5** | **+0.5** | **−0.0** | **+8.0** |

What this shows:

* **Live, v5 does not beat HPA overall.** On average it uses 8% more replica-hours, for about the same throughput, a slightly higher p95 and 0.5 pp more failures. Five of the 12 pairs (repeat 1 payment_degradation, flash_sale, gradual_ramp, traffic_drop and repeat 2 steady_browsing, 2026-10-25 02:00–04:30) ran on battery in both arms, found afterwards in the laptop's charge history (`reports/host_load_by_run.csv`); on the 7 AC-power pairs v5 used +6.4% replica-hours (95% CI −6.7 … +19.5), so the direction is the same but the interval includes 0 ("on par" under the §3.1 rule instead of "worse"). (v4: +6% replica-hours, −2.4% p95, one run per arm.)
* **Consistent in both repeats:** v5 is better on traffic_drop (p95 −35% / −29%, throughput +11% / +9%). It is worse on gradual_ramp (p95 +44% / +83%). On a slow ramp it scales up later than HPA. It uses more replicas on flash_sale and payment_degradation.
* **Everything else flips sign between repeats.** Run-to-run noise is as large as the effect. For example, HPA alone on checkout_heavy gave 31.4% then 27.5% failures. Two repeats are not enough to claim a difference either way in those scenarios.
* **The simulator's gain over HPA did not carry over to the cluster.** In the simulator, v5 bought fewer SLO violations with +0.44 replicas. Live, it spends the extra replicas (+8%) without a consistent latency or failure benefit. Most failures in checkout_heavy and payment_degradation come from the injected payment faults, which no amount of scaling fixes.

### 4.4 Conclusion

v5 is the first FlexaScale policy that beats the HPA-like rule in the simulator, with confidence intervals on paired test episodes. It does not beat native HPA on the live cluster, and it does not beat a well-tuned threshold rule in the simulator. The claim that is supported: imitation warm start + PPO fine-tuning gives a stable learned autoscaler that is better than the HPA-like rule in simulation and close to native HPA live (within run-to-run noise in most scenarios). It also fixes v3/v4's over-provisioning. "Beats HPA" in production is not supported by these data.
