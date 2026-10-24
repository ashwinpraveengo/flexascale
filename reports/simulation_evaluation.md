# Held-out Simulation Evaluation

Generated 2026-10-22 23:31:22 by `scripts/evaluate_policies.py`. 200 paired episodes on the **test** split (never used for training or checkpoint selection).

Environment: 4 services sampled at random per episode from the Alibaba v2021 trace, normalized demand model (replica range 1-10), random initial replicas. Original reward = SLO + 0.3 x CPU-efficiency + 0.1 x stability; cost-aware reward adds 0.5 x (-replicas/max_replicas) (latency target 100 ms, CPU target 70%).

| Policy | Reward (original) | Reward (+0.5 x cost) | Latency-SLO violation rate | Avg replicas | Avg CPU % | Scale actions / step |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| ppo_v2_best | -1.351 +/- 0.690 | -2.811 +/- 0.679 | 25.7% | 7.30 | 51.5 | 4.22 |
| ppo_v2_final | -1.297 +/- 0.673 | -2.758 +/- 0.663 | 25.5% | 7.31 | 51.4 | 4.23 |
| ppo_v3_best | -1.411 +/- 0.749 | -2.905 +/- 0.732 | 25.2% | 7.47 | 50.2 | 4.97 |
| ppo_v3_final | -1.251 +/- 0.674 | -2.751 +/- 0.659 | 24.7% | 7.50 | 49.9 | 5.00 |
| ppo_legacy | -5.266 +/- 1.057 | -6.465 +/- 1.036 | 36.5% | 5.99 | 60.6 | 1.25 |
| hpa_rule | -1.940 +/- 0.732 | -2.989 +/- 0.728 | 31.2% | 5.25 | 65.8 | 2.85 |
| hold | -6.731 +/- 1.150 | -7.829 +/- 1.127 | 40.8% | 5.49 | 64.3 | 0.00 |
| random | -7.053 +/- 1.086 | -8.157 +/- 1.063 | 41.2% | 5.52 | 64.2 | 3.34 |

Paired difference in episode reward versus the HPA-like rule (positive = better than the rule):

| Policy | Mean difference (95% CI) | Episodes better than rule |
| :--- | ---: | ---: |
| ppo_v2_best | +0.589 +/- 0.176 | 60% |
| ppo_v2_final | +0.643 +/- 0.173 | 60% |
| ppo_v3_best | +0.529 +/- 0.231 | 60% |
| ppo_v3_final | +0.689 +/- 0.169 | 62% |
| ppo_legacy | -3.326 +/- 0.613 | 30% |
| hold | -4.791 +/- 0.702 | 22% |
| random | -5.114 +/- 0.654 | 14% |

Notes:
- v2 was trained on the original reward, v3 on the cost-aware reward; both are shown under both definitions. Avg replicas and SLO violations are reward-independent and are the fairer comparison.
- `ppo_legacy` was trained on data whose CPU/memory columns were fractions (0-1) instead of percent and on a 50-replica range; it is shown for transparency only.
- The simulator uses an M/M/1-style latency model over trace demand. Simulation results do not prove live performance; see the live experiment reports for that.
