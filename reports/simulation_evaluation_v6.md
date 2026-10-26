# Simulation Evaluation: v6 policy (control-loop simulator)

Generated 2026-10-25 18:56:26 by `scripts/evaluate_v6.py`. 300 paired episodes on the **test services** (seeds 40000-40299, fresh), 120 decisions of 15 s each (30 minutes of trace). Simulator: `FlexaScaleEnvV3` (pod start-up delay, 1-minute CPU lag, the operator's guards, native-HPA neighbours). ± is a 95% confidence half-width.

Selected model: `lr1e-4_s2/warm_start` (highest validation reward of 12 candidates, 200 validation-service episodes each; native HPA on the same episodes: +0.0770).

| Policy | Reward / step | SLO violation rate | Avg replicas | Avg CPU % | Replica changes / step | Guard-blocked / step |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| ppo_v6 | 0.060 ± 0.093 | 0.270 ± 0.040 | 3.50 ± 0.22 | 56.3 ± 1.4 | 0.09 ± 0.01 | 0.17 ± 0.03 |
| ppo_v6_no_neighbours | 0.069 ± 0.093 | 0.285 ± 0.040 | 3.19 ± 0.20 | 60.8 ± 1.5 | 0.06 ± 0.00 | 0.13 ± 0.03 |
| native_hpa | 0.108 ± 0.084 | 0.264 ± 0.040 | 3.22 ± 0.17 | 58.8 ± 0.9 | 0.07 ± 0.00 | 0.00 ± 0.00 |
| hpa_ratio_rule | 0.096 ± 0.093 | 0.267 ± 0.040 | 3.34 ± 0.21 | 58.3 ± 1.4 | 0.06 ± 0.01 | 0.14 ± 0.03 |
| ppo_v5 | 0.008 ± 0.090 | 0.281 ± 0.039 | 3.70 ± 0.21 | 54.7 ± 1.5 | 0.06 ± 0.00 | 0.13 ± 0.03 |
| hold | -0.520 ± 0.119 | 0.324 ± 0.044 | 5.66 ± 0.33 | 40.6 ± 3.3 | 0.00 ± 0.00 | 0.00 ± 0.00 |

## Paired differences (v6 minus baseline, same episodes)

| Baseline | Δ reward | Δ SLO violation rate | Δ avg replicas | Episodes v6 better |
| :--- | ---: | ---: | ---: | ---: |
| native_hpa | -0.048 ± 0.018 | 0.006 ± 0.003 | 0.29 ± 0.16 | 34% |
| hpa_ratio_rule | -0.036 ± 0.010 | 0.003 ± 0.004 | 0.16 ± 0.04 | 23% |
| ppo_v5 | 0.052 ± 0.015 | -0.011 ± 0.006 | -0.20 ± 0.08 | 63% |
| ppo_v6_no_neighbours | -0.009 ± 0.013 | -0.015 ± 0.006 | 0.31 ± 0.04 | 35% |

`native_hpa` is the Kubernetes HPA algorithm without FlexaScale's guards. `ppo_v6_no_neighbours`: the same model with its three dependency-graph neighbours replaced by a fixed neutral vector.

## By scenario

| Group | Episodes | v6 reward | native HPA reward | v5 reward | v6 replicas | HPA replicas |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| event=drop | 53 | +0.463 | +0.473 | +0.386 | 2.22 | 2.11 |
| event=none | 62 | +0.083 | +0.189 | +0.064 | 3.37 | 2.53 |
| event=ramp | 89 | -0.127 | -0.067 | -0.187 | 4.03 | 3.61 |
| event=spike | 96 | -0.004 | +0.015 | -0.055 | 3.81 | 3.91 |
| bottleneck=False | 188 | +0.505 | +0.504 | +0.424 | 2.96 | 3.15 |
| bottleneck=True | 112 | -0.687 | -0.558 | -0.690 | 4.41 | 3.33 |

Reward weights: slo 1.0, efficiency 0.3, stability 0.1, cost 1.0. The simulator is a model; live results are in reports/live_benchmark_report.md.
