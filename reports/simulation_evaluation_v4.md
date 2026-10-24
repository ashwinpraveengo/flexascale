# Simulation Evaluation: v4 policy (dependency-aware simulator)

Generated 2026-10-24 15:18:43 by `scripts/evaluate_v4.py`. 300 paired episodes on the **test services** (never seen in training or selection), 30 one-minute steps each. Each policy controls the top service of a 4-service call chain and is scored on it; the downstream services follow the same HPA-like rule with random deviations in every run. ± is a 95% confidence half-width.

Selected model: `lr1e-4_ent0.01_s3/final` (highest validation reward of 8 candidates, 200 validation-service episodes each).

| Policy | Reward / step | SLO violation rate | Avg replicas | Avg CPU % | Replica changes / step |
| :--- | ---: | ---: | ---: | ---: | ---: |
| ppo_v4 | -0.425 ± 0.097 | 0.376 ± 0.040 | 4.54 ± 0.25 | 43.5 ± 2.4 | 0.07 ± 0.01 |
| hpa_rule | -0.288 ± 0.091 | 0.407 ± 0.038 | 2.82 ± 0.15 | 63.7 ± 1.0 | 0.37 ± 0.03 |
| ppo_v3 | -0.861 ± 0.086 | 0.335 ± 0.039 | 9.54 ± 0.05 | 19.3 ± 1.2 | 0.17 ± 0.01 |
| hold | -0.698 ± 0.115 | 0.414 ± 0.042 | 5.18 ± 0.30 | 42.0 ± 3.2 | 0.00 ± 0.00 |
| always_up | -0.862 ± 0.086 | 0.334 ± 0.039 | 9.56 ± 0.04 | 19.3 ± 1.2 | 0.17 ± 0.01 |
| random | -0.787 ± 0.100 | 0.419 ± 0.039 | 5.31 ± 0.27 | 41.7 ± 2.8 | 0.61 ± 0.01 |

## Paired differences (v4 minus baseline, same episodes)

| Baseline | Δ reward | Δ SLO violation rate | Δ avg replicas |
| :--- | ---: | ---: | ---: |
| hpa_rule | -0.137 ± 0.039 | -0.030 ± 0.015 | 1.72 ± 0.20 |
| ppo_v3 | 0.436 ± 0.038 | 0.042 ± 0.013 | -5.00 ± 0.21 |

## By scenario

| Group | Episodes | v4 viol. | HPA viol. | v4 replicas | HPA replicas | v4 reward | HPA reward |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| event=drop | 63 | 0.171 | 0.210 | 3.34 | 1.94 | +0.179 | +0.236 |
| event=none | 72 | 0.395 | 0.421 | 4.46 | 2.58 | -0.375 | -0.199 |
| event=ramp | 64 | 0.498 | 0.512 | 5.13 | 3.59 | -0.753 | -0.560 |
| event=spike | 101 | 0.414 | 0.452 | 4.98 | 3.05 | -0.629 | -0.505 |
| bottleneck=False | 180 | 0.191 | 0.209 | 4.44 | 2.73 | -0.021 | +0.096 |
| bottleneck=True | 120 | 0.655 | 0.703 | 4.70 | 2.96 | -1.030 | -0.863 |

Reward weights: slo 1.0, efficiency 0.3, stability 0.1, cost 1.0. The simulator is a model; live results are in reports/live_benchmark_report.md.
