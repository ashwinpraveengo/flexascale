# v9 live comparison without the late reruns (descriptive)

Not the pre-registered verdict (that is `evaluation.md`, unchanged). The valid reruns ran at 01:53–02:31, hours after the other runs of their block and under memory pressure; every pair that contains one is left out here. Δ = candidate − reference, 95% t-intervals over the remaining pairs.

Reruns left out: `20261030-015346-shopping-flexascale-gradual_ramp`, `20261030-020558-shopping-auto-traffic_drop`, `20261030-021821-shopping-flexascale-traffic_drop`

## rl vs hpa_tuned (9 of 11 pairs)

| Metric | Mean Δ [95% CI] |
| :--- | :--- |
| Replica-hours | +0.1% [-0.1 … +0.4] |
| p95 | +3.8% [-6.2 … +13.9] |
| Mean latency | +5.8% [+0.0 … +11.5] |
| Failures | +0.0 pp [-0.1 … +0.1] |
| Throughput | -0.0% [-0.8 … +0.8] |
| E2E SLO violation | +5.0 s [-5.0 … +15.0] |

## auto vs hpa_tuned (10 of 11 pairs)

| Metric | Mean Δ [95% CI] |
| :--- | :--- |
| Replica-hours | +0.2% [-0.2 … +0.6] |
| p95 | +13.8% [-5.6 … +33.2] |
| Mean latency | +19.4% [-18.1 … +56.9] |
| Failures | +0.1 pp [-0.1 … +0.3] |
| Throughput | -1.0% [-3.7 … +1.7] |
| E2E SLO violation | +4.6 s [-3.8 … +13.0] |

## rl vs hpa_default (9 of 11 pairs)

| Metric | Mean Δ [95% CI] |
| :--- | :--- |
| Replica-hours | -8.2% [-13.2 … -3.2] |
| p95 | -2.0% [-20.6 … +16.5] |
| Mean latency | -1.0% [-11.9 … +10.0] |
| Failures | -0.1 pp [-0.2 … +0.1] |
| Throughput | +1.3% [-2.3 … +4.8] |
| E2E SLO violation | -10.0 s [-32.8 … +12.8] |

## auto vs hpa_default (10 of 11 pairs)

| Metric | Mean Δ [95% CI] |
| :--- | :--- |
| Replica-hours | -7.8% [-12.9 … -2.7] |
| p95 | +14.5% [-10.8 … +39.7] |
| Mean latency | +31.2% [-40.5 … +102.8] |
| Failures | +0.1 pp [-0.1 … +0.3] |
| Throughput | -0.9% [-4.0 … +2.3] |
| E2E SLO violation | -1.3 s [-12.7 … +10.0] |
