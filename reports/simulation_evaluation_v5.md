# Simulation Evaluation: v5 policy (HPA-imitation warm start + PPO)

Generated 2026-10-25 01:02:26 by `scripts/evaluate_v5.py`. 300 paired episodes on the **test services** (seeds 30000-30299, fresh; the services were also used for v4's test), 30 one-minute steps each. Same simulator, reward and scoring as v4. ± is a 95% confidence half-width.

Selected model: `lr3e-5_s2/final` (highest validation reward of 12 candidates, 200 validation-service episodes each).

| Policy | Reward / step | SLO violation rate | Avg replicas | Avg CPU % | Replica changes / step |
| :--- | ---: | ---: | ---: | ---: | ---: |
| ppo_v5 | -0.274 ± 0.093 | 0.379 ± 0.039 | 3.26 ± 0.17 | 55.4 ± 1.5 | 0.20 ± 0.01 |
| ppo_v5_no_neighbours | -0.290 ± 0.089 | 0.367 ± 0.039 | 3.71 ± 0.20 | 49.2 ± 1.5 | 0.17 ± 0.01 |
| hpa_rule | -0.338 ± 0.091 | 0.414 ± 0.037 | 2.81 ± 0.14 | 62.8 ± 1.1 | 0.39 ± 0.03 |
| tuned_rule_77_45 | -0.227 ± 0.093 | 0.374 ± 0.039 | 3.12 ± 0.16 | 56.5 ± 1.1 | 0.21 ± 0.02 |
| ppo_v4 | -0.474 ± 0.096 | 0.382 ± 0.039 | 4.81 ± 0.26 | 40.6 ± 2.4 | 0.08 ± 0.01 |
| hold | -0.803 ± 0.118 | 0.432 ± 0.042 | 5.58 ± 0.33 | 40.2 ± 3.4 | 0.00 ± 0.00 |

## Paired differences (v5 minus baseline, same episodes)

| Baseline | Δ reward | Δ SLO violation rate | Δ avg replicas | Episodes v5 better |
| :--- | ---: | ---: | ---: | ---: |
| hpa_rule | 0.064 ± 0.031 | -0.034 ± 0.009 | 0.44 ± 0.08 | 43% |
| tuned_rule_77_45 | -0.048 ± 0.013 | 0.006 ± 0.004 | 0.14 ± 0.08 | 23% |
| ppo_v4 | 0.200 ± 0.027 | -0.003 ± 0.010 | -1.56 ± 0.20 | 86% |
| ppo_v5_no_neighbours | 0.016 ± 0.015 | 0.013 ± 0.004 | -0.45 ± 0.10 | 53% |

`ppo_v5_no_neighbours`: the same model with its three dependency-graph neighbours replaced by a fixed neutral vector. A positive Δ reward against it means the policy's decisions use its neighbours' state.

## By scenario

| Group | Episodes | v5 reward | HPA reward | tuned-rule reward | v5 replicas | HPA replicas |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| event=drop | 70 | +0.140 | +0.046 | +0.177 | 2.49 | 2.03 |
| event=none | 65 | -0.238 | -0.226 | -0.204 | 3.54 | 3.00 |
| event=ramp | 68 | -0.398 | -0.570 | -0.331 | 3.62 | 3.20 |
| event=spike | 97 | -0.511 | -0.528 | -0.460 | 3.36 | 2.98 |
| bottleneck=False | 174 | +0.138 | +0.059 | +0.191 | 3.34 | 2.77 |
| bottleneck=True | 126 | -0.843 | -0.887 | -0.803 | 3.14 | 2.87 |

Reward weights: slo 1.0, efficiency 0.3, stability 0.1, cost 1.0. The simulator is a model; live results are in reports/live_benchmark_report.md.
