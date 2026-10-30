# v9 against v7 on the held-out twin test sets (descriptive)

Added after the v9 evaluation; not pre-registered and not a gate. Both deployed models (`models\flexascale_v9\best_model\best_model.zip`, `models\flexascale_v7\best_model\best_model.zip`) run the test sets of `scripts/train_v7.py` (never used to train or select either) with the same operator loop, guards (V7_GUARDS) and v7 reward, on each laptop's twin. Δ = v9 − v7 per episode; 95% t-intervals. Reward: higher is better; replica-h, p95 and SLO violation: lower is better.

## this laptop (v9 twin)

| Test set | episodes | v9 reward | v7 reward | Δ reward [95% CI] | Δ replica-h [95% CI] | Δ p95 ms [95% CI] | Δ SLO violation s [95% CI] |
| :--- | ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| T1_live_scenarios | 30 | -1.255 | -1.254 | -0.001 [-0.068 … +0.066] | +0.0004 [-0.0009 … +0.0016] | -1.1 [-4.1 … +1.8] | +0.00 [+0.00 … +0.00] |
| T2_random_shop | 60 | -2.548 | -2.554 | +0.007 [-0.307 … +0.321] | -0.0059 [-0.0126 … +0.0007] | +3.4 [-8.4 … +15.2] | +0.25 [-0.31 … +0.81] |
| T3_random_apps | 40 | -78.962 | -75.312 | -3.651 [-7.735 … +0.433] | +0.0253 [-0.0294 … +0.0800] | -304.2 [-753.5 … +145.1] | +10.50 [-5.96 … +26.96] |

## first laptop (v7 twin)

| Test set | episodes | v9 reward | v7 reward | Δ reward [95% CI] | Δ replica-h [95% CI] | Δ p95 ms [95% CI] | Δ SLO violation s [95% CI] |
| :--- | ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| T1_live_scenarios | 30 | -2.431 | -2.502 | +0.071 [-0.916 … +1.057] | -0.0075 [-0.0160 … +0.0009] | +9.1 [-78.1 … +96.2] | +0.17 [-2.51 … +2.85] |
| T2_random_shop | 60 | -3.797 | -3.703 | -0.094 [-1.030 … +0.841] | -0.0107 [-0.0227 … +0.0013] | +3.6 [-39.3 … +46.4] | +1.17 [-2.33 … +4.66] |
| T3_random_apps | 40 | -78.962 | -75.312 | -3.651 [-7.735 … +0.433] | +0.0253 [-0.0294 … +0.0800] | -304.2 [-753.5 … +145.1] | +10.50 [-5.96 … +26.96] |

