# v9 twin test sets and graph ablation (docs/POLICY_V9.md §5)

Run once after the live evaluation (`scripts/train_v7.py --only-test`, twin `config/twin/shopping_v9.json`). Selected model: `focal_bc_s2`; selected rule: `limit_target(0.6/0.3)`; `HPA 350%, 60 s` is HPA-tuned of the live evaluation. Reward: the v7 episode reward, higher is better. Every controller sees the same episodes.

## Validation (selection set, 40 shop workloads)

| Run | best validation reward | at step |
| :--- | ---: | ---: |
| focal_bc_s1 | -2.990 | 1,000,000 |
| focal_bc_s2 | -2.466 | 2,000,000 |
| focal_bc_nograph_s1 | -2.922 | 1,750,000 |
| focal_bc_v5reward_s1 | -3.299 | 0 |
| rule limit_target(0.6/0.3) | -2.986 | – |

## T1: the 6 live scenarios × 5 seeds

| Controller | reward | replica-h | p95 ms | mean ms | SLO violation s | events | osc |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HPA-default (70%, 300 s) | -6.325 | 1.477 | 168 | 64 | 0.0 | 2.3 | 0.0 |
| HPA 350%, 60 s | -1.196 | 1.333 | 178 | 68 | 0.0 | 0.0 | 0.0 |
| operator + limit_target(0.6/0.3) | -1.280 | 1.338 | 174 | 66 | 0.0 | 0.3 | 0.2 |
| v7 (focal_bc_s2) | -1.255 | 1.340 | 171 | 65 | 0.0 | 0.5 | 0.3 |
| v7 (focal_bc_s1) | -1.256 | 1.336 | 176 | 67 | 0.0 | 0.3 | 0.2 |
| v7 (focal_bc_nograph_s1) | -1.255 | 1.339 | 173 | 66 | 0.0 | 0.3 | 0.2 |
| v7 (focal_bc_v5reward_s1) | -1.280 | 1.338 | 174 | 66 | 0.0 | 0.3 | 0.2 |

## T2: 60 random shop workloads

| Controller | reward | replica-h | p95 ms | mean ms | SLO violation s | events | osc |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HPA-default (70%, 300 s) | -15.694 | 2.461 | 167 | 62 | 0.0 | 3.4 | 0.1 |
| HPA 350%, 60 s | -3.060 | 2.071 | 217 | 73 | 2.7 | 0.2 | 0.1 |
| operator + limit_target(0.6/0.3) | -2.789 | 2.080 | 208 | 69 | 1.5 | 0.4 | 0.2 |
| v7 (focal_bc_s2) | -2.548 | 2.078 | 198 | 68 | 1.0 | 0.7 | 0.3 |
| v7 (focal_bc_s1) | -2.682 | 2.071 | 212 | 70 | 1.8 | 0.3 | 0.1 |
| v7 (focal_bc_nograph_s1) | -2.839 | 2.094 | 194 | 67 | 0.8 | 0.7 | 0.2 |
| v7 (focal_bc_v5reward_s1) | -2.788 | 2.085 | 201 | 68 | 1.2 | 0.6 | 0.2 |

## T3: 40 random synthetic applications

| Controller | reward | replica-h | p95 ms | mean ms | SLO violation s | events | osc |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HPA-default (70%, 300 s) | -109.338 | 3.448 | 620 | 161 | 13.9 | 10.2 | 0.2 |
| HPA 350%, 60 s | -82.374 | 1.673 | 2202 | 521 | 45.4 | 1.9 | 0.4 |
| operator + limit_target(0.6/0.3) | -79.286 | 1.802 | 1399 | 337 | 28.8 | 3.7 | 0.6 |
| v7 (focal_bc_s2) | -78.962 | 1.815 | 1160 | 295 | 38.9 | 12.2 | 6.1 |
| v7 (focal_bc_s1) | -76.033 | 1.785 | 1063 | 250 | 25.1 | 3.5 | 0.9 |
| v7 (focal_bc_nograph_s1) | -76.741 | 1.969 | 849 | 204 | 18.0 | 5.3 | 1.2 |
| v7 (focal_bc_v5reward_s1) | -78.868 | 1.905 | 1123 | 269 | 23.6 | 6.1 | 1.2 |

## Graph ablation (seed 1: graph − no graph, paired by episode)

| Test set | episodes | Δ reward [95% CI] | Δ replica-h [95% CI] | Δ p95 ms [95% CI] | Δ SLO violation s [95% CI] |
| :--- | ---: | :--- | :--- | :--- | :--- |
| T1_live_scenarios | 30 | -0.001 [-0.026 … +0.024] | -0.0029 [-0.0053 … -0.0004] | +2.9 [+0.3 … +5.4] | +0.00 [+0.00 … +0.00] |
| T2_random_shop | 60 | +0.157 [-0.363 … +0.677] | -0.0228 [-0.0386 … -0.0071] | +18.0 [-5.3 … +41.3] | +1.00 [-0.86 … +2.86] |
| T3_random_apps | 40 | +0.708 [-3.304 … +4.720] | -0.1831 [-0.3018 … -0.0645] | +214.3 [-29.0 … +457.5] | +7.12 [-0.33 … +14.58] |

Positive reward Δ favours the graph; replica-h, p95 and SLO violation Δ below 0 favour the graph.
