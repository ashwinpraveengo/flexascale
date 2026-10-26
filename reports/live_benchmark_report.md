# Live Benchmark: native HPA vs FlexaScale and Auto mode

Generated 2026-10-26 20:39 by `scripts/build_live_report.py` from the raw runs in `reports/experiments/`. Per-run numbers are in `reports/live_benchmark_summary.csv`. Pairing, statistics and verdicts use `flexascale.lab.benchmark`, the same code as the dashboard's Comparison page.

**Setup.** Minikube (1 node), the application's own HPAs (CPU target 70% of request, 1–10 replicas; the shop has 16 managed services in the most recent runs). Locust scenarios from `load-testing/scenarios.py` through the ingress, 25 users, 300 s. Before every run the lab resets application data and scales every service to its minimum, and waits until the previous run's HPA scale-down window has passed (comparable start). Costs are estimates (allocated vCPU and memory × AWS Fargate on-demand list prices, or a unitless resource proxy where no prices were configured), not a bill.

**Pairing.** Each candidate run is paired with the most recent complete default-HPA run with identical settings that started before it. Δ = candidate − HPA; negative cost, latency and failures are better. Intervals are 95% t-intervals of the mean over pairs.

**Verdict rule** (docs/POLICY_V6.md §3.1, fixed before the v6 results): beats on cost = replica-hours interval below 0 and the failure and p95 intervals include or lie below 0; beats on performance = p95 or failure interval below 0 and the replica-hours interval includes or lies below 0; worse = an interval above 0 without such a gain; otherwise on par.

## Summary

| Candidate | Pairs | Scenarios | Δ replica-h % | Δ cost % | Δ p95 % | Δ failures pp | Δ throughput % | Cost basis | Verdict |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |
| FlexaScale v5 (Auto mode) | 18 | 6 | -3.9% [-6.5 … -1.3] | -4.0% [-6.6 … -1.3] | +2.8% [-8.0 … +13.6] | -0.07 pp [-0.12 … -0.02] | +0.7% [-0.3 … +1.7] | estimated (list prices) | Beats HPA on cost |
| FlexaScale v5 | 12 | 6 | +8.0% [+0.8 … +15.1] | +8.0% [+0.8 … +15.1] | +6.5% [-15.3 … +28.3] | +0.49 pp [-0.83 … +1.81] | -0.0% [-7.7 … +7.7] | resource-cost proxy | Worse than HPA |
| FlexaScale v4 | 6 | 6 | +6.0% [-6.3 … +18.4] | +6.0% [-6.3 … +18.4] | -2.4% [-44.9 … +40.1] | -0.53 pp [-7.72 … +6.67] | +4.5% [-2.8 … +11.8] | resource-cost proxy | On par with HPA |
| FlexaScale v3 | 3 | 3 | +77.5% [+27.3 … +127.8] | +77.5% [+27.3 … +127.8] | +24.6% [-30.1 … +79.3] | +0.52 pp [+0.31 … +0.73] | -6.7% [-26.8 … +13.4] | resource-cost proxy | preliminary (3 pairs) |
| Native HPA, 60 s scale-down | 12 | 6 | -1.4% [-2.6 … -0.2] | -1.4% [-2.7 … -0.2] | +5.8% [-5.5 … +17.1] | +0.05 pp [-0.02 … +0.12] | -2.3% [-4.6 … -0.0] | estimated (list prices) | Beats HPA on cost |

## FlexaScale v5 (Auto mode) vs native HPA

Auto mode decides per service and per step whether FlexaScale or native HPA owns scaling, by ordered rules (controller health → policy confidence → SLA risk → efficiency; `docs/POLICY_V6.md` §5).

Per scenario, one value per pair in run order (✓ = all pairs agree in direction, ✗ = they disagree):

| Scenario | Pairs | Δ replica-h % | Δ p95 % | Δ failures pp | Δ throughput % |
| :--- | ---: | ---: | ---: | ---: | ---: |
| checkout_heavy | 3 | -6.5% / -6.4% / -11.3% ✓ | +26.1% / -8.0% / -17.2% ✗ | -0.0 / -0.1 / -0.3 ✓ | -3.2% / +1.2% / +3.2% ✗ |
| flash_sale | 3 | -9.0% / -7.7% / +1.6% ✗ | +25.0% / -4.9% / +0.0% ✗ | -0.1 / -0.2 / -0.2 ✓ | -2.3% / +2.7% / +3.4% ✗ |
| gradual_ramp | 3 | -0.6% / -0.6% / +8.8% ✗ | +7.7% / -14.3% / +75.0% ✗ | -0.1 / -0.1 / +0.1 ✗ | +1.1% / -0.9% / -1.2% ✗ |
| payment_degradation | 3 | -1.4% / -1.8% / -2.4% ✓ | +0.0% / -10.0% / +0.0% ✓ | -0.3 / +0.0 / -0.1 ✗ | +0.1% / +0.4% / +1.1% ✓ |
| steady_browsing | 3 | -3.9% / -2.5% / -3.1% ✓ | +7.8% / -2.9% / +1.5% ✗ | -0.0 / +0.0 / -0.0 ✗ | -0.1% / -1.1% / +2.0% ✗ |
| traffic_drop | 3 | -12.0% / -11.4% / -0.4% ✓ | -13.3% / -12.5% / -9.7% ✓ | +0.1 / -0.1 / -0.0 ✗ | +1.8% / +0.6% / +3.6% ✓ |

Replica changes recorded during the runs, by owner of the service at the time:

| Runs | n | Scale-ups and scale-downs |
| :--- | ---: | :--- |
| default HPA (baselines) | 18 | HPA: 86 up, 0 down |
| FlexaScale v5 (Auto mode) | 18 | FlexaScale: 52 up, 56 down; HPA: 44 up, 0 down |

| # | Scenario | HPA run | Candidate run | Δ replica-h % | Δ cost % | Δ p95 % | Δ failures pp | Δ throughput % |
| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | steady_browsing | `20261026-043500-shopping-hpa-steady_browsing` | `20261026-044431-shopping-auto-steady_browsing` | -3.9 | -4.0 | +7.8 | -0.02 | -0.1 |
| 2 | checkout_heavy | `20261026-045602-shopping-hpa-checkout_heavy` | `20261026-050723-shopping-auto-checkout_heavy` | -6.5 | -6.6 | +26.1 | -0.03 | -3.2 |
| 3 | payment_degradation | `20261026-052334-shopping-hpa-payment_degradation` | `20261026-053455-shopping-auto-payment_degradation` | -1.4 | -1.4 | +0.0 | -0.30 | +0.1 |
| 4 | flash_sale | `20261026-054626-shopping-hpa-flash_sale` | `20261026-060237-shopping-auto-flash_sale` | -9.0 | -9.1 | +25.0 | -0.07 | -2.3 |
| 5 | gradual_ramp | `20261026-061408-shopping-hpa-gradual_ramp` | `20261026-062529-shopping-auto-gradual_ramp` | -0.6 | -0.6 | +7.7 | -0.05 | +1.1 |
| 6 | traffic_drop | `20261026-064140-shopping-hpa-traffic_drop` | `20261026-065301-shopping-auto-traffic_drop` | -12.0 | -12.2 | -13.3 | +0.07 | +1.8 |
| 7 | steady_browsing | `20261026-070422-shopping-hpa-steady_browsing` | `20261026-071553-shopping-auto-steady_browsing` | -2.5 | -2.5 | -2.9 | +0.00 | -1.1 |
| 8 | checkout_heavy | `20261026-072714-shopping-hpa-checkout_heavy` | `20261026-074345-shopping-auto-checkout_heavy` | -6.4 | -6.5 | -8.0 | -0.09 | +1.2 |
| 9 | payment_degradation | `20261026-075506-shopping-hpa-payment_degradation` | `20261026-081148-shopping-auto-payment_degradation` | -1.8 | -1.8 | -10.0 | +0.02 | +0.4 |
| 10 | flash_sale | `20261026-082309-shopping-hpa-flash_sale` | `20261026-083930-shopping-auto-flash_sale` | -7.7 | -7.8 | -4.9 | -0.18 | +2.7 |
| 11 | gradual_ramp | `20261026-085101-shopping-hpa-gradual_ramp` | `20261026-090222-shopping-auto-gradual_ramp` | -0.6 | -0.6 | -14.3 | -0.05 | -0.9 |
| 12 | traffic_drop | `20261026-091833-shopping-hpa-traffic_drop` | `20261026-093004-shopping-auto-traffic_drop` | -11.4 | -11.6 | -12.5 | -0.08 | +0.6 |
| 13 | steady_browsing | `20261026-094125-shopping-hpa-steady_browsing` | `20261026-095246-shopping-auto-steady_browsing` | -3.1 | -3.2 | +1.5 | -0.00 | +2.0 |
| 14 | checkout_heavy | `20261026-100417-shopping-hpa-checkout_heavy` | `20261026-102028-shopping-auto-checkout_heavy` | -11.3 | -11.4 | -17.2 | -0.26 | +3.2 |
| 15 | payment_degradation | `20261026-103159-shopping-hpa-payment_degradation` | `20261026-104840-shopping-auto-payment_degradation` | -2.4 | -2.4 | +0.0 | -0.09 | +1.1 |
| 16 | flash_sale | `20261026-110001-shopping-hpa-flash_sale` | `20261026-111632-shopping-auto-flash_sale` | +1.6 | +1.7 | +0.0 | -0.18 | +3.4 |
| 17 | gradual_ramp | `20261026-112803-shopping-hpa-gradual_ramp` | `20261026-113924-shopping-auto-gradual_ramp` | +8.8 | +9.0 | +75.0 | +0.06 | -1.2 |
| 18 | traffic_drop | `20261026-115546-shopping-hpa-traffic_drop` | `20261026-120718-shopping-auto-traffic_drop` | -0.4 | -0.4 | -9.7 | -0.02 | +3.6 |

## FlexaScale v5 vs native HPA

Per scenario, one value per pair in run order (✓ = all pairs agree in direction, ✗ = they disagree):

| Scenario | Pairs | Δ replica-h % | Δ p95 % | Δ failures pp | Δ throughput % |
| :--- | ---: | ---: | ---: | ---: | ---: |
| checkout_heavy | 2 | -4.8% / +1.2% ✗ | +22.4% / -26.2% ✗ | +0.4 / +4.5 ✓ | -32.3% / +9.3% ✗ |
| flash_sale | 2 | +11.2% / +24.3% ✓ | -4.2% / +0.0% ✓ | +1.1 / -4.2 ✗ | +5.3% / +10.7% ✓ |
| gradual_ramp | 2 | +5.9% / +26.6% ✓ | +43.5% / +83.3% ✓ | +0.7 / -0.7 ✗ | -7.9% / -7.5% ✓ |
| payment_degradation | 2 | +7.3% / +6.2% ✓ | -15.2% / +32.3% ✗ | +2.5 / -0.0 ✗ | +1.7% / +2.8% ✓ |
| steady_browsing | 2 | +2.0% / +20.4% ✓ | +0.0% / +6.2% ✓ | -0.8 / +0.5 ✗ | +0.2% / -2.7% ✗ |
| traffic_drop | 2 | +6.2% / -10.9% ✗ | -35.1% / -29.4% ✓ | +1.8 / +0.1 ✓ | +11.4% / +8.8% ✓ |

Replica changes recorded during the runs, by owner of the service at the time:

| Runs | n | Scale-ups and scale-downs |
| :--- | ---: | :--- |
| default HPA (baselines) | 12 | HPA: 106 up, 0 down |
| FlexaScale v5 | 12 | FlexaScale: 164 up, 17 down; HPA: 21 up, 0 down |

| # | Scenario | HPA run | Candidate run | Δ replica-h % | Δ cost % | Δ p95 % | Δ failures pp | Δ throughput % |
| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | steady_browsing | `20261025-010311-shopping-hpa-steady_browsing` | `20261025-010911-shopping-flexascale-steady_browsing` | +2.0 | +2.0 | +0.0 | -0.79 | +0.2 |
| 2 | checkout_heavy | `20261025-012612-shopping-hpa-checkout_heavy` | `20261025-014313-shopping-flexascale-checkout_heavy` | -4.8 | -4.8 | +22.4 | +0.40 | -32.3 |
| 3 | payment_degradation | `20261025-020024-shopping-hpa-payment_degradation` | `20261025-021715-shopping-flexascale-payment_degradation` | +7.3 | +7.3 | -15.2 | +2.46 | +1.7 |
| 4 | flash_sale | `20261025-023426-shopping-hpa-flash_sale` | `20261025-025117-shopping-flexascale-flash_sale` | +11.2 | +11.2 | -4.2 | +1.14 | +5.3 |
| 5 | gradual_ramp | `20261025-030818-shopping-hpa-gradual_ramp` | `20261025-032459-shopping-flexascale-gradual_ramp` | +5.9 | +5.9 | +43.5 | +0.70 | -7.9 |
| 6 | traffic_drop | `20261025-033630-shopping-hpa-traffic_drop` | `20261025-035301-shopping-flexascale-traffic_drop` | +6.2 | +6.2 | -35.1 | +1.79 | +11.4 |
| 7 | steady_browsing | `20261025-040612-shopping-hpa-steady_browsing` | `20261025-042313-shopping-flexascale-steady_browsing` | +20.4 | +20.4 | +6.2 | +0.46 | -2.7 |
| 8 | checkout_heavy | `20261025-113620-shopping-hpa-checkout_heavy` | `20261025-114650-shopping-flexascale-checkout_heavy` | +1.2 | +1.2 | -26.2 | +4.53 | +9.3 |
| 9 | payment_degradation | `20261025-120311-shopping-hpa-payment_degradation` | `20261025-121432-shopping-flexascale-payment_degradation` | +6.2 | +6.2 | +32.3 | -0.02 | +2.8 |
| 10 | flash_sale | `20261025-122552-shopping-hpa-flash_sale` | `20261025-123713-shopping-flexascale-flash_sale` | +24.3 | +24.3 | +0.0 | -4.16 | +10.7 |
| 11 | gradual_ramp | `20261025-124833-shopping-hpa-gradual_ramp` | `20261025-125954-shopping-flexascale-gradual_ramp` | +26.6 | +26.6 | +83.3 | -0.67 | -7.5 |
| 12 | traffic_drop | `20261025-131705-shopping-hpa-traffic_drop` | `20261025-133406-shopping-flexascale-traffic_drop` | -10.9 | -10.9 | -29.4 | +0.07 | +8.8 |

## FlexaScale v4 vs native HPA

Per scenario, one value per pair in run order (✓ = all pairs agree in direction, ✗ = they disagree):

| Scenario | Pairs | Δ replica-h % | Δ p95 % | Δ failures pp | Δ throughput % |
| :--- | ---: | ---: | ---: | ---: | ---: |
| checkout_heavy | 1 | -2.4% | +0.0% | -11.3 | +1.5% |
| flash_sale | 1 | +21.6% | -34.6% | -0.6 | +13.1% |
| gradual_ramp | 1 | -11.0% | +40.9% | +0.0 | -0.8% |
| payment_degradation | 1 | +10.1% | -48.8% | +10.3 | +13.0% |
| steady_browsing | 1 | +3.7% | +50.0% | +0.0 | -3.0% |
| traffic_drop | 1 | +14.2% | -22.0% | -1.6 | +3.0% |

Replica changes recorded during the runs, by owner of the service at the time:

| Runs | n | Scale-ups and scale-downs |
| :--- | ---: | :--- |
| default HPA (baselines) | 6 | HPA: 56 up, 0 down |
| FlexaScale v4 | 6 | FlexaScale: 58 up, 0 down; HPA: 21 up, 0 down |

| # | Scenario | HPA run | Candidate run | Δ replica-h % | Δ cost % | Δ p95 % | Δ failures pp | Δ throughput % |
| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | steady_browsing | `20261024-152728-shopping-hpa-steady_browsing` | `20261024-153329-shopping-flexascale-steady_browsing` | +3.7 | +3.7 | +50.0 | +0.01 | -3.0 |
| 2 | checkout_heavy | `20261024-165144-shopping-hpa-checkout_heavy` | `20261024-170255-shopping-flexascale-checkout_heavy` | -2.4 | -2.4 | +0.0 | -11.29 | +1.5 |
| 3 | payment_degradation | `20261024-172006-shopping-hpa-payment_degradation` | `20261024-173657-shopping-flexascale-payment_degradation` | +10.1 | +10.1 | -48.8 | +10.30 | +13.0 |
| 4 | flash_sale | `20261024-175357-shopping-hpa-flash_sale` | `20261024-181108-shopping-flexascale-flash_sale` | +21.6 | +21.6 | -34.6 | -0.60 | +13.1 |
| 5 | gradual_ramp | `20261024-182809-shopping-hpa-gradual_ramp` | `20261024-183930-shopping-flexascale-gradual_ramp` | -11.0 | -11.0 | +40.9 | +0.01 | -0.8 |
| 6 | traffic_drop | `20261024-185611-shopping-hpa-traffic_drop` | `20261024-191302-shopping-flexascale-traffic_drop` | +14.2 | +14.2 | -22.0 | -1.61 | +3.0 |

## FlexaScale v3 vs native HPA

Per scenario, one value per pair in run order (✓ = all pairs agree in direction, ✗ = they disagree):

| Scenario | Pairs | Δ replica-h % | Δ p95 % | Δ failures pp | Δ throughput % |
| :--- | ---: | ---: | ---: | ---: | ---: |
| flash_sale | 1 | +77.0% | +50.0% | +0.4 | -16.0% |
| gradual_ramp | 1 | +98.0% | +13.3% | +0.5 | -3.1% |
| traffic_drop | 1 | +57.6% | +10.5% | +0.6 | -1.0% |

Replica changes recorded during the runs, by owner of the service at the time:

| Runs | n | Scale-ups and scale-downs |
| :--- | ---: | :--- |
| default HPA (baselines) | 3 | HPA: 28 up, 0 down |
| FlexaScale v3 | 3 | FlexaScale: 34 up, 0 down; HPA: 11 up, 1 down |

| # | Scenario | HPA run | Candidate run | Δ replica-h % | Δ cost % | Δ p95 % | Δ failures pp | Δ throughput % |
| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | flash_sale | `20261023-001403-shopping-hpa-flash_sale` | `20261023-002554-shopping-flexascale-flash_sale` | +77.0 | +77.0 | +50.0 | +0.43 | -16.0 |
| 2 | gradual_ramp | `20261023-004215-shopping-hpa-gradual_ramp` | `20261023-005916-shopping-flexascale-gradual_ramp` | +98.0 | +98.0 | +13.3 | +0.52 | -3.1 |
| 3 | traffic_drop | `20261023-011607-shopping-hpa-traffic_drop` | `20261023-013258-shopping-flexascale-traffic_drop` | +57.6 | +57.6 | +10.5 | +0.60 | -1.0 |

## Native HPA, 60 s scale-down vs native HPA

Tuned-HPA reference (`docs/POLICY_V6.md` §5.2): native HPA with only the scale-down stabilisation window shortened from 300 s to 60 s, each run directly after the default-HPA run it is paired with, on AC power. It asks whether Auto's saving is more than scaling down sooner, and does not change the Auto verdict.

Per scenario, one value per pair in run order (✓ = all pairs agree in direction, ✗ = they disagree):

| Scenario | Pairs | Δ replica-h % | Δ p95 % | Δ failures pp | Δ throughput % |
| :--- | ---: | ---: | ---: | ---: | ---: |
| checkout_heavy | 2 | -3.0% / -3.7% ✓ | +2.4% / -23.7% ✗ | +0.1 / -0.1 ✗ | -3.0% / +4.3% ✗ |
| flash_sale | 2 | -4.5% / +0.7% ✗ | +52.3% / +15.5% ✓ | +0.2 / +0.1 ✓ | -9.8% / -7.2% ✓ |
| gradual_ramp | 2 | -0.2% / -0.8% ✓ | +0.0% / +10.5% ✓ | -0.0 / +0.1 ✗ | +0.3% / -0.6% ✗ |
| payment_degradation | 2 | -0.8% / -2.1% ✓ | +4.5% / +0.0% ✓ | -0.1 / +0.1 ✗ | -0.9% / -1.9% ✓ |
| steady_browsing | 1 | +0.6% | -8.1% | +0.0 | -0.6% |
| traffic_drop | 3 | -1.5% / +1.7% / -3.0% ✗ | +10.5% / +5.3% / +0.0% ✓ | +0.0 / +0.2 / -0.0 ✗ | -1.1% / -3.6% / -3.5% ✓ |

Replica changes recorded during the runs, by owner of the service at the time:

| Runs | n | Scale-ups and scale-downs |
| :--- | ---: | :--- |
| default HPA (baselines) | 12 | HPA: 56 up, 0 down |
| Native HPA, 60 s scale-down | 12 | HPA: 58 up, 19 down |

| # | Scenario | HPA run | Candidate run | Δ replica-h % | Δ cost % | Δ p95 % | Δ failures pp | Δ throughput % |
| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | payment_degradation | `20261026-144625-shopping-hpa-payment_degradation` | `20261026-150236-shopping-hpa_fast-payment_degradation` | -0.8 | -0.8 | +4.5 | -0.15 | -0.9 |
| 2 | flash_sale | `20261026-151407-shopping-hpa-flash_sale` | `20261026-153038-shopping-hpa_fast-flash_sale` | -4.5 | -4.6 | +52.3 | +0.23 | -9.8 |
| 3 | gradual_ramp | `20261026-154159-shopping-hpa-gradual_ramp` | `20261026-155840-shopping-hpa_fast-gradual_ramp` | -0.2 | -0.2 | +0.0 | -0.00 | +0.3 |
| 4 | traffic_drop | `20261026-161001-shopping-hpa-traffic_drop` | `20261026-162633-shopping-hpa_fast-traffic_drop` | -1.5 | -1.5 | +10.5 | +0.00 | -1.1 |
| 5 | steady_browsing | `20261026-163804-shopping-hpa-steady_browsing` | `20261026-164925-shopping-hpa_fast-steady_browsing` | +0.6 | +0.6 | -8.1 | +0.04 | -0.6 |
| 6 | checkout_heavy | `20261026-170546-shopping-hpa-checkout_heavy` | `20261026-171707-shopping-hpa_fast-checkout_heavy` | -3.0 | -3.0 | +2.4 | +0.09 | -3.0 |
| 7 | payment_degradation | `20261026-173348-shopping-hpa-payment_degradation` | `20261026-174509-shopping-hpa_fast-payment_degradation` | -2.1 | -2.1 | +0.0 | +0.13 | -1.9 |
| 8 | flash_sale | `20261026-180130-shopping-hpa-flash_sale` | `20261026-181251-shopping-hpa_fast-flash_sale` | +0.7 | +0.7 | +15.5 | +0.14 | -7.2 |
| 9 | gradual_ramp | `20261026-182422-shopping-hpa-gradual_ramp` | `20261026-184033-shopping-hpa_fast-gradual_ramp` | -0.8 | -0.9 | +10.5 | +0.05 | -0.6 |
| 10 | traffic_drop | `20261026-185204-shopping-hpa-traffic_drop` | `20261026-190836-shopping-hpa_fast-traffic_drop` | +1.7 | +1.7 | +5.3 | +0.20 | -3.6 |
| 11 | checkout_heavy | `20261026-193856-shopping-hpa-checkout_heavy` | `20261026-195537-shopping-hpa_fast-checkout_heavy` | -3.7 | -3.8 | -23.7 | -0.06 | +4.3 |
| 12 | traffic_drop | `20261026-200708-shopping-hpa-traffic_drop` | `20261026-202339-shopping-hpa_fast-traffic_drop` | -3.0 | -3.1 | +0.0 | -0.03 | -3.5 |

## Auto mode vs tuned native HPA (indirect)

Both are paired differences against default HPA, so they are compared through those differences: v5 (Auto mode) (18 pairs) minus Native HPA, 60 s scale-down (12 pairs), with a 95% Welch interval. The two sets use different baseline runs at different times of day, so this is indirect, and it does not change the verdicts above. Rule fixed before the six-scenario tuned batch (`docs/POLICY_V6.md` §5.2): for replica-hours, an interval below 0 means Auto saves more than a tuned HPA, above 0 means the tuned HPA saves more, and an interval that includes 0 shows no difference. p95 and failures are descriptive.

| Metric | Auto mean Δ | Tuned-HPA mean Δ | Auto − tuned [95% CI] | Reading |
| :--- | ---: | ---: | ---: | :--- |
| Replica-hours | -3.9% | -1.4% | -2.5% [-5.4 … +0.3] | no difference shown |
| Estimated cost | -4.0% | -1.4% | -2.6% [-5.4 … +0.3] | descriptive |
| p95 latency | +2.8% | +5.8% | -3.0% [-17.9 … +12.0] | descriptive |
| Failures | -0.07 pp | +0.05 pp | -0.13 pp [-0.21 … -0.04] | descriptive |

## Runs

*Outside load* is the host CPU used outside the Kubernetes containers during the load window, and any time on battery (`reports/host_load_by_run.csv`, from `scripts/check_host_load.py`; ⚠ = host-affected under `docs/POLICY_V6.md` §5.2).

| Run | Controller | Model | Scenario | Users | State | Req/s | Fail % | p95 | Avg repl. | Replica-h | Est. cost $ | Cleanup safe | Outside load |
| :--- | :--- | :--- | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |
| 20261022-231341-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 10 | completed (prelim.) | 5.01 | 2.33 | 360 | 7.00 | 0.1269 | — | True | no CPU data, battery 67 s ⚠ |
| 20261022-233320-shopping-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 30 | completed (prelim.) | 12.04 | 2.02 | 2,100 | 18.57 | 0.4117 | — | True | no CPU data, battery 99 s ⚠ |
| 20261022-233616-shopping-hpa-flash_sale | hpa | — | flash_sale | 40 | completed | 13.34 | 3.94 | 2,600 | 21.62 | 1.4178 | — | True | no CPU data, battery 214 s ⚠ |
| 20261022-234747-shopping-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 40 | completed | 5.26 | 42.62 | 10,000 | 39.61 | 3.9554 | — | False | no CPU data |
| 20261023-000028-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 40 | failed (prelim.) | — | — | — | — | — | — | False | — |
| 20261023-000038-shopping-flexascale-steady_browsing | flexascale | unknown | steady_browsing | 40 | failed (prelim.) | — | — | — | — | — | — | False | — |
| 20261023-000048-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 40 | failed (prelim.) | — | — | — | — | — | — | False | — |
| 20261023-000058-shopping-flexascale-gradual_ramp | flexascale | unknown | gradual_ramp | 40 | failed (prelim.) | — | — | — | — | — | — | False | — |
| 20261023-000108-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 40 | failed (prelim.) | — | — | — | — | — | — | False | — |
| 20261023-000118-shopping-flexascale-checkout_heavy | flexascale | unknown | checkout_heavy | 40 | failed (prelim.) | — | — | — | — | — | — | False | — |
| 20261023-000128-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 40 | failed (prelim.) | — | — | — | — | — | — | False | — |
| 20261023-000138-shopping-flexascale-traffic_drop | flexascale | unknown | traffic_drop | 40 | failed (prelim.) | — | — | — | — | — | — | False | — |
| 20261023-001403-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 10.44 | 2.07 | 1,400 | 15.52 | 1.2458 | — | True | no CPU data |
| 20261023-002554-shopping-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 25 | completed | 8.77 | 2.50 | 2,100 | 29.43 | 2.2047 | — | True | no CPU data |
| 20261023-004215-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 7.05 | 6.45 | 3,000 | 13.98 | 1.1096 | — | True | no CPU data |
| 20261023-005916-shopping-flexascale-gradual_ramp | flexascale | flexascale_v3 | gradual_ramp | 25 | completed | 6.84 | 6.96 | 3,400 | 27.12 | 2.1971 | — | True | no CPU data |
| 20261023-011607-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 5.50 | 6.75 | 1,900 | 14.67 | 1.1927 | — | True | no CPU data |
| 20261023-013258-shopping-flexascale-traffic_drop | flexascale | flexascale_v3 | traffic_drop | 25 | completed | 5.44 | 7.35 | 2,100 | 23.73 | 1.8794 | — | True | no CPU data |
| 20261023-014451-bookstore-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 15 | completed (prelim.) | 6.01 | 0.00 | 130 | 14.63 | 0.5034 | 0.0021 | True | no CPU data |
| 20261023-161341-shopping-hpa-flash_sale | hpa | — | flash_sale | 40 | stopped (prelim.) | — | — | — | — | — | — | True | — |
| 20261023-161429-shopping-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 40 | stopped (prelim.) | — | — | — | — | — | — | True | — |
| 20261024-152728-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 25 | completed | 11.36 | 3.30 | 1,000 | 14.50 | 1.1942 | — | True | no CPU data |
| 20261024-153329-shopping-flexascale-steady_browsing | flexascale | flexascale_v4 | steady_browsing | 25 | completed | 11.02 | 3.32 | 1,500 | 14.97 | 1.2384 | — | True | no CPU data |
| 20261024-165144-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 8.50 | 30.19 | 6,000 | 21.36 | 1.4137 | — | True | no CPU data |
| 20261024-170255-shopping-flexascale-checkout_heavy | flexascale | flexascale_v4 | checkout_heavy | 25 | completed | 8.62 | 18.90 | 6,000 | 18.25 | 1.3803 | — | True | no CPU data |
| 20261024-172006-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 9.03 | 21.85 | 4,100 | 13.90 | 1.1011 | — | True | no CPU data |
| 20261024-173657-shopping-flexascale-payment_degradation | flexascale | flexascale_v4 | payment_degradation | 25 | completed | 10.20 | 32.15 | 2,100 | 15.17 | 1.2121 | — | True | no CPU data |
| 20261024-175357-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 8.39 | 3.05 | 2,600 | 14.67 | 1.1484 | — | True | no CPU data |
| 20261024-181108-shopping-flexascale-flash_sale | flexascale | flexascale_v4 | flash_sale | 25 | completed | 9.48 | 2.46 | 1,700 | 17.78 | 1.3966 | — | True | no CPU data, battery 4 s ⚠ |
| 20261024-182809-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 7.07 | 7.02 | 2,200 | 14.29 | 1.1059 | — | True | no CPU data, battery 307 s ⚠ |
| 20261024-183930-shopping-flexascale-gradual_ramp | flexascale | flexascale_v4 | gradual_ramp | 25 | completed | 7.02 | 7.03 | 3,100 | 12.48 | 0.9842 | — | True | no CPU data, battery 4 s ⚠ |
| 20261024-185611-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 4.72 | 7.41 | 5,000 | 18.29 | 1.4768 | — | True | no CPU data, battery 307 s ⚠ |
| 20261024-191302-shopping-flexascale-traffic_drop | flexascale | flexascale_v4 | traffic_drop | 25 | completed | 4.86 | 5.80 | 3,900 | 21.17 | 1.6870 | — | True | no CPU data, battery 308 s ⚠ |
| 20261024-193117-bookstore-flexascale-flash_sale | flexascale | flexascale_v4 | flash_sale | 15 | completed (prelim.) | 5.74 | 0.00 | 280 | 5.89 | 0.1963 | 0.0008 | True | no CPU data, battery 128 s ⚠ |
| 20261025-010311-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 25 | completed | 11.09 | 3.86 | 1,500 | 14.43 | 1.1593 | — | True | no CPU data |
| 20261025-010911-shopping-flexascale-steady_browsing | flexascale | flexascale_v5 | steady_browsing | 25 | completed | 11.11 | 3.07 | 1,500 | 14.60 | 1.1829 | — | True | no CPU data |
| 20261025-012612-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 11.81 | 31.44 | 4,900 | 18.38 | 1.3636 | — | True | no CPU data |
| 20261025-014313-shopping-flexascale-checkout_heavy | flexascale | flexascale_v5 | checkout_heavy | 25 | completed | 8.00 | 31.83 | 6,000 | 18.31 | 1.2974 | — | True | no CPU data |
| 20261025-020024-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 8.60 | 32.26 | 4,600 | 18.76 | 1.3618 | — | True | no CPU data, battery 307 s ⚠ |
| 20261025-021715-shopping-flexascale-payment_degradation | flexascale | flexascale_v5 | payment_degradation | 25 | completed | 8.75 | 34.72 | 3,900 | 20.09 | 1.4616 | — | True | no CPU data, battery 314 s ⚠ |
| 20261025-023426-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 7.97 | 3.34 | 2,400 | 15.71 | 1.2476 | — | True | no CPU data, battery 307 s ⚠ |
| 20261025-025117-shopping-flexascale-flash_sale | flexascale | flexascale_v5 | flash_sale | 25 | completed | 8.40 | 4.48 | 2,300 | 18.54 | 1.3879 | — | True | no CPU data, battery 309 s ⚠ |
| 20261025-030818-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 7.15 | 8.47 | 2,300 | 16.05 | 1.2436 | — | True | no CPU data, battery 307 s ⚠ |
| 20261025-032459-shopping-flexascale-gradual_ramp | flexascale | flexascale_v5 | gradual_ramp | 25 | completed | 6.58 | 9.17 | 3,300 | 17.00 | 1.3169 | — | True | no CPU data, battery 314 s ⚠ |
| 20261025-033630-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 4.87 | 6.29 | 3,700 | 17.14 | 1.3905 | — | True | no CPU data, battery 307 s ⚠ |
| 20261025-035301-shopping-flexascale-traffic_drop | flexascale | flexascale_v5 | traffic_drop | 25 | completed | 5.43 | 8.08 | 2,400 | 18.65 | 1.4769 | — | True | no CPU data, battery 310 s ⚠ |
| 20261025-040612-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 25 | completed | 11.17 | 2.89 | 1,600 | 16.12 | 1.3282 | — | True | no CPU data, battery 312 s ⚠ |
| 20261025-042313-shopping-flexascale-steady_browsing | flexascale | flexascale_v5 | steady_browsing | 25 | completed | 10.87 | 3.35 | 1,700 | 19.88 | 1.5997 | — | True | no CPU data, battery 316 s ⚠ |
| 20261025-113620-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 11.33 | 27.52 | 4,200 | 18.48 | 1.4013 | — | True | no CPU data |
| 20261025-114650-shopping-flexascale-checkout_heavy | flexascale | flexascale_v5 | checkout_heavy | 25 | completed | 12.38 | 32.05 | 3,100 | 19.32 | 1.4181 | — | True | no CPU data |
| 20261025-120311-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 9.98 | 34.38 | 3,100 | 13.22 | 1.0272 | — | True | no CPU data |
| 20261025-121432-shopping-flexascale-payment_degradation | flexascale | flexascale_v5 | payment_degradation | 25 | completed | 10.27 | 34.35 | 4,100 | 14.32 | 1.0912 | — | True | no CPU data |
| 20261025-122552-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 9.22 | 6.54 | 1,900 | 11.98 | 0.9260 | — | True | no CPU data |
| 20261025-123713-shopping-flexascale-flash_sale | flexascale | flexascale_v5 | flash_sale | 25 | completed | 10.21 | 2.38 | 1,900 | 14.19 | 1.1510 | — | True | no CPU data |
| 20261025-124833-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 7.95 | 8.32 | 1,200 | 11.57 | 0.8869 | — | True | no CPU data |
| 20261025-125954-shopping-flexascale-gradual_ramp | flexascale | flexascale_v5 | gradual_ramp | 25 | completed | 7.35 | 7.64 | 2,200 | 14.40 | 1.1232 | — | True | no CPU data |
| 20261025-131705-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 5.50 | 8.16 | 1,700 | 13.67 | 1.0800 | — | True | no CPU data |
| 20261025-133406-shopping-flexascale-traffic_drop | flexascale | flexascale_v5 | traffic_drop | 25 | completed | 5.98 | 8.22 | 1,200 | 12.29 | 0.9618 | — | True | no CPU data |
| 20261025-192442-shopping-auto-flash_sale | auto | flexascale_v5 | flash_sale | 25 | completed (prelim.) | 9.01 | 7.13 | 6,000 | 17.05 | 0.8386 | 0.0038 | True | no CPU data, battery 189 s ⚠ |
| 20261026-043500-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 25 | completed | 18.40 | 0.02 | 64 | 17.43 | 1.4707 | 0.0067 | True | 0.7 cores |
| 20261026-044431-shopping-auto-steady_browsing | auto | flexascale_v5 | steady_browsing | 25 | completed | 18.38 | 0.00 | 69 | 16.87 | 1.4136 | 0.0064 | True | 1.2 cores |
| 20261026-045602-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 20.77 | 1.19 | 230 | 22.86 | 1.9073 | 0.0087 | True | 0.8 cores |
| 20261026-050723-shopping-auto-checkout_heavy | auto | flexascale_v5 | checkout_heavy | 25 | completed | 20.10 | 1.16 | 290 | 21.40 | 1.7835 | 0.0081 | True | 1.3 cores |
| 20261026-052334-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 15.50 | 0.43 | 190 | 18.73 | 1.5737 | 0.0071 | True | 0.7 cores |
| 20261026-053455-shopping-auto-payment_degradation | auto | flexascale_v5 | payment_degradation | 25 | completed | 15.52 | 0.13 | 190 | 18.41 | 1.5512 | 0.0070 | True | 1.2 cores |
| 20261026-054626-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 15.77 | 0.49 | 360 | 24.33 | 1.9977 | 0.0091 | True | 0.9 cores |
| 20261026-060237-shopping-auto-flash_sale | auto | flexascale_v5 | flash_sale | 25 | completed | 15.41 | 0.41 | 450 | 21.94 | 1.8181 | 0.0083 | True | 1.4 cores |
| 20261026-061408-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 12.13 | 0.05 | 130 | 16.57 | 1.3958 | 0.0063 | True | 0.6 cores |
| 20261026-062529-shopping-auto-gradual_ramp | auto | flexascale_v5 | gradual_ramp | 25 | completed | 12.26 | 0.00 | 140 | 16.41 | 1.3871 | 0.0063 | True | 1.2 cores |
| 20261026-064140-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 8.74 | 0.34 | 150 | 18.92 | 1.5903 | 0.0072 | True | 0.6 cores |
| 20261026-065301-shopping-auto-traffic_drop | auto | flexascale_v5 | traffic_drop | 25 | completed | 8.90 | 0.41 | 130 | 16.54 | 1.3997 | 0.0063 | True | 1.1 cores |
| 20261026-070422-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 25 | completed | 18.69 | 0.02 | 69 | 17.27 | 1.4566 | 0.0066 | True | 0.6 cores |
| 20261026-071553-shopping-auto-steady_browsing | auto | flexascale_v5 | steady_browsing | 25 | completed | 18.49 | 0.02 | 67 | 16.90 | 1.4204 | 0.0064 | True | 1.2 cores |
| 20261026-072714-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 20.53 | 1.12 | 250 | 22.95 | 1.9101 | 0.0087 | True | 0.8 cores |
| 20261026-074345-shopping-auto-checkout_heavy | auto | flexascale_v5 | checkout_heavy | 25 | completed | 20.77 | 1.03 | 230 | 21.41 | 1.7875 | 0.0081 | True | 1.4 cores |
| 20261026-075506-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 15.62 | 0.21 | 200 | 18.67 | 1.5679 | 0.0071 | True | 0.7 cores |
| 20261026-081148-shopping-auto-payment_degradation | auto | flexascale_v5 | payment_degradation | 25 | completed | 15.68 | 0.23 | 180 | 18.29 | 1.5401 | 0.0070 | True | 1.2 cores |
| 20261026-082309-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 15.43 | 0.50 | 410 | 24.10 | 1.9824 | 0.0090 | True | 0.9 cores |
| 20261026-083930-shopping-auto-flash_sale | auto | flexascale_v5 | flash_sale | 25 | completed | 15.84 | 0.32 | 390 | 22.00 | 1.8290 | 0.0083 | True | 1.4 cores |
| 20261026-085101-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 12.36 | 0.13 | 140 | 16.57 | 1.3957 | 0.0063 | True | 0.6 cores |
| 20261026-090222-shopping-auto-gradual_ramp | auto | flexascale_v5 | gradual_ramp | 25 | completed | 12.24 | 0.08 | 120 | 16.41 | 1.3871 | 0.0063 | True | 1.2 cores |
| 20261026-091833-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 8.67 | 0.38 | 160 | 18.98 | 1.5960 | 0.0072 | True | 0.6 cores |
| 20261026-093004-shopping-auto-traffic_drop | auto | flexascale_v5 | traffic_drop | 25 | completed | 8.73 | 0.31 | 140 | 16.81 | 1.4135 | 0.0064 | True | 1.1 cores |
| 20261026-094125-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 25 | completed | 18.39 | 0.04 | 68 | 17.33 | 1.4622 | 0.0066 | True | 0.7 cores |
| 20261026-095246-shopping-auto-steady_browsing | auto | flexascale_v5 | steady_browsing | 25 | completed | 18.75 | 0.04 | 69 | 16.83 | 1.4162 | 0.0064 | True | 1.2 cores |
| 20261026-100417-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 20.16 | 1.27 | 290 | 22.98 | 1.9128 | 0.0087 | True | 0.8 cores |
| 20261026-102028-shopping-auto-checkout_heavy | auto | flexascale_v5 | checkout_heavy | 25 | completed | 20.81 | 1.01 | 240 | 20.33 | 1.6971 | 0.0077 | True | 1.6 cores |
| 20261026-103159-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 15.32 | 0.30 | 200 | 18.67 | 1.5677 | 0.0071 | True | 0.7 cores |
| 20261026-104840-shopping-auto-payment_degradation | auto | flexascale_v5 | payment_degradation | 25 | completed | 15.49 | 0.21 | 200 | 18.11 | 1.5303 | 0.0069 | True | 1.3 cores |
| 20261026-110001-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 15.10 | 0.40 | 450 | 22.70 | 1.8714 | 0.0085 | True | 0.8 cores |
| 20261026-111632-shopping-auto-flash_sale | auto | flexascale_v5 | flash_sale | 25 | completed | 15.61 | 0.21 | 450 | 23.22 | 1.9021 | 0.0086 | True | 1.4 cores |
| 20261026-112803-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 12.14 | 0.05 | 160 | 16.57 | 1.3957 | 0.0063 | True | 0.6 cores |
| 20261026-113924-shopping-auto-gradual_ramp | auto | flexascale_v5 | gradual_ramp | 25 | completed | 11.99 | 0.11 | 280 | 18.29 | 1.5189 | 0.0069 | True | 2.5 cores, battery 218 s ⚠ |
| 20261026-115546-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 8.41 | 0.52 | 310 | 19.76 | 1.6598 | 0.0075 | True | 1.6 cores, battery 308 s ⚠ |
| 20261026-120718-shopping-auto-traffic_drop | auto | flexascale_v5 | traffic_drop | 25 | completed | 8.71 | 0.50 | 280 | 19.81 | 1.6531 | 0.0075 | True | 1.9 cores, battery 314 s ⚠ |
| 20261026-144625-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 15.53 | 0.34 | 220 | 18.86 | 1.5847 | 0.0072 | True | 1.1 cores |
| 20261026-150236-shopping-hpa_fast-payment_degradation | hpa_fast | — | payment_degradation | 25 | completed | 15.39 | 0.19 | 230 | 18.75 | 1.5719 | 0.0071 | True | 0.9 cores |
| 20261026-151407-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 15.34 | 0.35 | 440 | 22.89 | 1.8882 | 0.0086 | True | 1.0 cores |
| 20261026-153038-shopping-hpa_fast-flash_sale | hpa_fast | — | flash_sale | 25 | completed | 13.83 | 0.58 | 670 | 21.79 | 1.8031 | 0.0082 | True | 0.8 cores |
| 20261026-154159-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 12.13 | 0.05 | 180 | 16.63 | 1.4014 | 0.0063 | True | 0.7 cores |
| 20261026-155840-shopping-hpa_fast-gradual_ramp | hpa_fast | — | gradual_ramp | 25 | completed | 12.17 | 0.05 | 180 | 16.60 | 1.3984 | 0.0063 | True | 0.7 cores |
| 20261026-161001-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 8.71 | 0.31 | 190 | 18.79 | 1.5792 | 0.0072 | True | 1.0 cores |
| 20261026-162633-shopping-hpa_fast-traffic_drop | hpa_fast | — | traffic_drop | 25 | completed | 8.61 | 0.31 | 210 | 18.43 | 1.5552 | 0.0071 | True | 1.2 cores |
| 20261026-163804-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 25 | completed | 18.64 | 0.00 | 74 | 17.30 | 1.4597 | 0.0066 | True | 1.2 cores |
| 20261026-164925-shopping-hpa_fast-steady_browsing | hpa_fast | — | steady_browsing | 25 | completed | 18.53 | 0.04 | 68 | 17.40 | 1.4678 | 0.0067 | True | 1.0 cores |
| 20261026-170546-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 19.71 | 1.25 | 410 | 22.33 | 1.8612 | 0.0085 | True | 0.9 cores |
| 20261026-171707-shopping-hpa_fast-checkout_heavy | hpa_fast | — | checkout_heavy | 25 | completed | 19.11 | 1.34 | 420 | 21.67 | 1.8057 | 0.0082 | True | 1.2 cores |
| 20261026-173348-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 15.72 | 0.15 | 210 | 18.79 | 1.5791 | 0.0072 | True | 1.2 cores |
| 20261026-174509-shopping-hpa_fast-payment_degradation | hpa_fast | — | payment_degradation | 25 | completed | 15.42 | 0.28 | 210 | 18.43 | 1.5456 | 0.0070 | True | 0.9 cores |
| 20261026-180130-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 14.68 | 0.20 | 580 | 23.37 | 1.9237 | 0.0088 | True | 1.5 cores |
| 20261026-181251-shopping-hpa_fast-flash_sale | hpa_fast | — | flash_sale | 25 | completed | 13.62 | 0.34 | 670 | 23.33 | 1.9366 | 0.0088 | True | 1.2 cores |
| 20261026-182422-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 12.37 | 0.03 | 190 | 17.14 | 1.4359 | 0.0065 | True | 1.1 cores |
| 20261026-184033-shopping-hpa_fast-gradual_ramp | hpa_fast | — | gradual_ramp | 25 | completed | 12.29 | 0.08 | 210 | 17.02 | 1.4237 | 0.0064 | True | 1.1 cores |
| 20261026-185204-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 8.99 | 0.07 | 190 | 17.43 | 1.4707 | 0.0067 | True | 0.9 cores |
| 20261026-190836-shopping-hpa_fast-traffic_drop | hpa_fast | — | traffic_drop | 25 | completed | 8.67 | 0.27 | 200 | 17.71 | 1.4957 | 0.0068 | True | 1.3 cores |
| 20261026-193856-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 18.81 | 1.36 | 590 | 23.14 | 1.9267 | 0.0088 | True | 1.9 cores |
| 20261026-195537-shopping-hpa_fast-checkout_heavy | hpa_fast | — | checkout_heavy | 25 | completed | 19.62 | 1.30 | 450 | 22.38 | 1.8547 | 0.0084 | True | 1.5 cores |
| 20261026-200708-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 9.05 | 0.15 | 180 | 18.24 | 1.5362 | 0.0070 | True | 1.2 cores |
| 20261026-202339-shopping-hpa_fast-traffic_drop | hpa_fast | — | traffic_drop | 25 | completed | 8.73 | 0.11 | 180 | 17.71 | 1.4900 | 0.0068 | True | 0.8 cores |

## Exclusions and history

- Runs invalidated by infrastructure or application faults are kept, with the reason, in `reports/experiments_invalid/` (see its README): host suspends and a shutdown when the battery ran out, a host clock 5.5 h fast, and the first HPA-vs-Auto batch (2026-10-25 20:02 – 2026-10-26 04:31), in which an unbounded order-history endpoint OOM-killed order-service in both arms.
- The laptop ran on battery (CPU about 1 GHz, every service about 4x slower) from 2026-10-26 11:52:05 to 13:07:42. This covered 218 s of the 314 s load window of the repeat-3 gradual_ramp Auto run (its HPA arm ran on AC) and the whole last HPA-vs-Auto pair (traffic_drop, 11:55/12:07). Both pairs are kept under the pre-registered rule; without them the Auto result is -4.9% replica-hours (95% CI -7.2 … -2.6, 16 pairs), with the same verdict. The tuned-HPA runs made on battery are excluded as not comparable.
- Host load: `scripts/check_host_load.py` measures, for every run, the host CPU used outside the Kubernetes containers during the load window (`reports/host_load_by_run.csv`). Under the criterion in `docs/POLICY_V6.md` §5.2 (battery, or more than 2.0 cores outside Kubernetes) three tuned-HPA pairs run between 13:08 and 14:46, when other jobs on the laptop used up to 12 extra cores, are excluded. Two were rerun; the steady_browsing rerun ran on battery (19:25–19:34) and is reported as missing. No Auto-batch run exceeded 1.64 cores outside the battery period.
- Earlier batches, checked afterwards against the laptop's charge history (Prometheus host-CPU data from before the 2026-10-25 Minikube restart is gone): 5 of the 12 v5 pairs ran on battery in both arms (2026-10-25 02:00–04:30; on the 7 AC pairs v5 used +6.4% replica-hours, 95% CI -6.7 … +19.5), and 3 of the 6 v4 pairs touched a battery period (on the 3 AC pairs +3.8%, CI -11.7 … +19.3). These pairs are kept, as the rules of those batches did not cover host conditions; the learned policy does not beat native HPA either way.
- Demo and rehearsal runs started from the dashboard are kept in `reports/experiments_demo/` (see its README). One Auto flash_sale rehearsal (2026-10-26 13:33) would have been a 19th pair; with it the Auto result is -3.5% replica-hours (95% CI -6.1 … -0.9), with the same verdict.
- All runs before 2026-10-26 04:35 (v3, v4, v5) used that unbounded endpoint, with a smaller but growing order table; its effect on those results cannot be measured afterwards.
- v3 (`models/flexascale_v3`) scaled every service up on almost every decision, also in simulation (`docs/POLICY_V4.md`). v3–v5 ran on the 7-service shop; Auto mode on the 16-service shop.

## How to read the cost columns

- *Replica-hours* and *allocated vCPU/GiB-hours* integrate ready replicas × requested resources over the run.
- *Estimated cost* = allocated vCPU-h × $0.04048 + GiB-h × $0.004445 (AWS Fargate on-demand list prices) where prices are configured; older runs use the unitless *resource-cost proxy* (vCPU-h + 0.125 × GiB-h). Neither is a cloud bill.
- Lower latency bought with more replicas is a trade-off, not a free improvement; both directions are reported.

## Data checks

- Runs found: 119; complete: 109. Runs whose cleanup was not verified safe: `20261022-234747-shopping-flexascale-flash_sale` (completed), `20261023-000028-shopping-hpa-steady_browsing` (failed), `20261023-000038-shopping-flexascale-steady_browsing` (failed), `20261023-000048-shopping-hpa-gradual_ramp` (failed), `20261023-000058-shopping-flexascale-gradual_ramp` (failed), `20261023-000108-shopping-hpa-checkout_heavy` (failed), `20261023-000118-shopping-flexascale-checkout_heavy` (failed), `20261023-000128-shopping-hpa-traffic_drop` (failed), `20261023-000138-shopping-flexascale-traffic_drop` (failed).
- `requests` (Locust final stats) and `requests_seen_in_samples` (last 5 s sample) are both in the CSV; they differ only by requests completed after the last sample.
