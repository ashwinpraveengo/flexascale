# Live Benchmark: Native HPA vs FlexaScale

Generated 2026-10-24 19:31 by `scripts/build_live_report.py` from the raw runs in `reports/experiments/`. Per-run numbers are also in `reports/live_benchmark_summary.csv`.

**Setup.** Minikube (1 node), the application's own HPAs (shopping: seven FastAPI services, CPU request 100m, limit 500m, 70% CPU, 1-10 replicas). Locust scenarios from `load-testing/scenarios.py` through the ingress. Before every run the lab resets all services to 1 replica and checks that the HPAs stay there (comparable start). FlexaScale runs use the safety layer (confidence >= 0.70 to take ownership, < 0.60 to hand back to HPA) and the model named in each section. End-to-end SLO: Locust p95 <= 1000 ms over 10 s windows.

Each FlexaScale run is paired with the most recent complete HPA run with identical settings that started before it. With one or two pairs per scenario the results are indicative, not statistically established.

## Runs

| Run | Controller | Model | Scenario | Users | State | Req/s | Fail % | p50 | p95 | p99 | SLO viol. s | Avg repl. | Replica-h | Cost proxy | Scale events | Cleanup safe |
| :--- | :--- | :--- | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| 20261022-231341-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 10 | completed (prelim.) | 5.01 | 2.33 | 27 | 360 | 1,400 | 5 | 7.00 | 0.1269 | 0.01468 | 0 | True |
| 20261022-233320-shopping-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 30 | completed (prelim.) | 12.04 | 2.02 | 300 | 2,100 | 4,100 | 55 | 18.57 | 0.4117 | 0.04761 | 19 | True |
| 20261022-233616-shopping-hpa-flash_sale | hpa | — | flash_sale | 40 | completed | 13.34 | 3.94 | 310 | 2,600 | 6,000 | 185 | 21.62 | 1.4178 | 0.16393 | 12 | True |
| 20261022-234747-shopping-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 40 | completed | 5.26 | 42.62 | 310 | 10,000 | 14,000 | 255 | 39.61 | 3.9554 | 0.45734 | 16 | False |
| 20261023-000028-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 40 | failed (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | False |
| 20261023-000038-shopping-flexascale-steady_browsing | flexascale | unknown | steady_browsing | 40 | failed (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | False |
| 20261023-000048-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 40 | failed (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | False |
| 20261023-000058-shopping-flexascale-gradual_ramp | flexascale | unknown | gradual_ramp | 40 | failed (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | False |
| 20261023-000108-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 40 | failed (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | False |
| 20261023-000118-shopping-flexascale-checkout_heavy | flexascale | unknown | checkout_heavy | 40 | failed (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | False |
| 20261023-000128-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 40 | failed (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | False |
| 20261023-000138-shopping-flexascale-traffic_drop | flexascale | unknown | traffic_drop | 40 | failed (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | False |
| 20261023-001403-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 10.44 | 2.07 | 240 | 1,400 | 3,800 | 180 | 15.52 | 1.2458 | 0.14405 | 9 | True |
| 20261023-002554-shopping-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 25 | completed | 8.77 | 2.50 | 280 | 2,100 | 4,500 | 200 | 29.43 | 2.2047 | 0.25492 | 16 | True |
| 20261023-004215-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 7.05 | 6.45 | 130 | 3,000 | 6,000 | 195 | 13.98 | 1.1096 | 0.12829 | 13 | True |
| 20261023-005916-shopping-flexascale-gradual_ramp | flexascale | flexascale_v3 | gradual_ramp | 25 | completed | 6.84 | 6.96 | 170 | 3,400 | 6,000 | 235 | 27.12 | 2.1971 | 0.25404 | 16 | True |
| 20261023-011607-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 5.50 | 6.75 | 77 | 1,900 | 6,000 | 190 | 14.67 | 1.1927 | 0.13791 | 6 | True |
| 20261023-013258-shopping-flexascale-traffic_drop | flexascale | flexascale_v3 | traffic_drop | 25 | completed | 5.44 | 7.35 | 95 | 2,100 | 6,000 | 245 | 23.73 | 1.8794 | 0.21731 | 14 | True |
| 20261023-014451-bookstore-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 15 | completed (prelim.) | 6.01 | 0.00 | 63 | 130 | 180 | 0 | 14.63 | 0.5034 | 0.05315 | 5 | True |
| 20261023-161341-shopping-hpa-flash_sale | hpa | — | flash_sale | 40 | stopped (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | True |
| 20261023-161429-shopping-flexascale-flash_sale | flexascale | flexascale_v3 | flash_sale | 40 | stopped (prelim.) | — | — | — | — | — | 0 | — | — | — | 0 | True |
| 20261024-152728-shopping-hpa-steady_browsing | hpa | — | steady_browsing | 25 | completed | 11.36 | 3.30 | 53 | 1,000 | 6,000 | 130 | 14.50 | 1.1942 | 0.13808 | 9 | True |
| 20261024-153329-shopping-flexascale-steady_browsing | flexascale | flexascale_v4 | steady_browsing | 25 | completed | 11.02 | 3.32 | 74 | 1,500 | 6,000 | 200 | 14.97 | 1.2384 | 0.14319 | 8 | True |
| 20261024-165144-shopping-hpa-checkout_heavy | hpa | — | checkout_heavy | 25 | completed | 8.50 | 30.19 | 700 | 6,000 | 6,000 | 295 | 21.36 | 1.4137 | 0.16346 | 10 | True |
| 20261024-170255-shopping-flexascale-checkout_heavy | flexascale | flexascale_v4 | checkout_heavy | 25 | completed | 8.62 | 18.90 | 970 | 6,000 | 6,000 | 295 | 18.25 | 1.3803 | 0.15959 | 12 | True |
| 20261024-172006-shopping-hpa-payment_degradation | hpa | — | payment_degradation | 25 | completed | 9.03 | 21.85 | 300 | 4,100 | 6,000 | 275 | 13.90 | 1.1011 | 0.12731 | 9 | True |
| 20261024-173657-shopping-flexascale-payment_degradation | flexascale | flexascale_v4 | payment_degradation | 25 | completed | 10.20 | 32.15 | 280 | 2,100 | 6,000 | 255 | 15.17 | 1.2121 | 0.14015 | 14 | True |
| 20261024-175357-shopping-hpa-flash_sale | hpa | — | flash_sale | 25 | completed | 8.39 | 3.05 | 260 | 2,600 | 6,000 | 185 | 14.67 | 1.1484 | 0.13278 | 8 | True |
| 20261024-181108-shopping-flexascale-flash_sale | flexascale | flexascale_v4 | flash_sale | 25 | completed | 9.48 | 2.46 | 320 | 1,700 | 3,900 | 175 | 17.78 | 1.3966 | 0.16148 | 17 | True |
| 20261024-182809-shopping-hpa-gradual_ramp | hpa | — | gradual_ramp | 25 | completed | 7.07 | 7.02 | 110 | 2,200 | 6,000 | 295 | 14.29 | 1.1059 | 0.12787 | 10 | True |
| 20261024-183930-shopping-flexascale-gradual_ramp | flexascale | flexascale_v4 | gradual_ramp | 25 | completed | 7.02 | 7.03 | 130 | 3,100 | 6,000 | 240 | 12.48 | 0.9842 | 0.11380 | 11 | True |
| 20261024-185611-shopping-hpa-traffic_drop | hpa | — | traffic_drop | 25 | completed | 4.72 | 7.41 | 130 | 5,000 | 6,100 | 285 | 18.29 | 1.4768 | 0.17075 | 10 | True |
| 20261024-191302-shopping-flexascale-traffic_drop | flexascale | flexascale_v4 | traffic_drop | 25 | completed | 4.86 | 5.80 | 130 | 3,900 | 6,000 | 295 | 21.17 | 1.6870 | 0.19506 | 17 | True |

## FlexaScale model `flexascale_v4` vs native HPA

| Scenario | Users | HPA run | FlexaScale run | Comparable | Δ p95 % | Δ throughput % | Δ failures pp | Δ SLO-violation s | Δ replica-h % | Δ cost proxy % |
| :--- | ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| checkout_heavy | 25 | `20261024-165144-shopping-hpa-checkout_heavy` | `20261024-170255-shopping-flexascale-checkout_heavy` | True | +0.0% | +1.5% | -11.3 | 0 | -2.4% | -2.4% |
| flash_sale | 25 | `20261024-175357-shopping-hpa-flash_sale` | `20261024-181108-shopping-flexascale-flash_sale` | True | -34.6% | +13.1% | -0.6 | -10 | +21.6% | +21.6% |
| gradual_ramp | 25 | `20261024-182809-shopping-hpa-gradual_ramp` | `20261024-183930-shopping-flexascale-gradual_ramp` | True | +40.9% | -0.8% | +0.0 | -55 | -11.0% | -11.0% |
| payment_degradation | 25 | `20261024-172006-shopping-hpa-payment_degradation` | `20261024-173657-shopping-flexascale-payment_degradation` | True | -48.8% | +13.0% | +10.3 | -20 | +10.1% | +10.1% |
| steady_browsing | 25 | `20261024-152728-shopping-hpa-steady_browsing` | `20261024-153329-shopping-flexascale-steady_browsing` | True | +50.0% | -3.0% | +0.0 | 70 | +3.7% | +3.7% |
| traffic_drop | 25 | `20261024-185611-shopping-hpa-traffic_drop` | `20261024-191302-shopping-flexascale-traffic_drop` | True | -22.0% | +3.0% | -1.6 | 10 | +14.2% | +14.2% |

Mean over 6 comparable pair(s): p95 latency -2.4%, throughput +4.5%, failure rate -0.5 pp, replica-hours +6.0%, resource-cost proxy +6.0% (negative cost = saving relative to HPA in the same scenario).

### flexascale_v4: checkout_heavy (25 users, 300 s)

Baseline `20261024-165144-shopping-hpa-checkout_heavy` vs candidate `20261024-170255-shopping-flexascale-checkout_heavy`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 8.4962 | 8.6228 | 0.1266 | +1.5% |
| Failure rate (%) | 30.1894 | 18.8961 | -11.2933 | -37.4% |
| p50 latency (ms) | 700.0000 | 970.0000 | 270.0000 | +38.6% |
| p95 latency (ms) | 6,000.0000 | 6,000.0000 | 0.0000 | +0.0% |
| p99 latency (ms) | 6,000.0000 | 6,000.0000 | 0.0000 | +0.0% |
| E2E p95 SLO violation (s) | 295.2000 | 295.2000 | 0.0000 | +0.0% |
| Avg total replicas | 21.3600 | 18.2500 | -3.1100 | -14.6% |
| Peak total replicas | 29 | 23 | -6 | -20.7% |
| Replica-hours | 1.4137 | 1.3803 | -0.0335 | -2.4% |
| Allocated vCPU-hours | 0.1414 | 0.1380 | -0.0033 | -2.4% |
| CPU allocation efficiency (%) | — | 82.8177 | — | — |
| Resource-cost proxy | 0.1635 | 0.1596 | -0.0039 | -2.4% |
| Scaling events | 10 | 12 | 2 | +20.0% |
| Oscillations (reversals) | 0 | 0 | 0 | — |

### flexascale_v4: flash_sale (25 users, 300 s)

Baseline `20261024-175357-shopping-hpa-flash_sale` vs candidate `20261024-181108-shopping-flexascale-flash_sale`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 8.3863 | 9.4809 | 1.0946 | +13.1% |
| Failure rate (%) | 3.0543 | 2.4579 | -0.5965 | -19.5% |
| p50 latency (ms) | 260.0000 | 320.0000 | 60.0000 | +23.1% |
| p95 latency (ms) | 2,600.0000 | 1,700.0000 | -900.0000 | -34.6% |
| p99 latency (ms) | 6,000.0000 | 3,900.0000 | -2,100.0000 | -35.0% |
| E2E p95 SLO violation (s) | 185.0000 | 175.0000 | -10.0000 | -5.4% |
| Avg total replicas | 14.6700 | 17.7800 | 3.1100 | +21.2% |
| Peak total replicas | 21 | 28 | 7 | +33.3% |
| Replica-hours | 1.1484 | 1.3966 | 0.2482 | +21.6% |
| Allocated vCPU-hours | 0.1148 | 0.1397 | 0.0248 | +21.6% |
| CPU allocation efficiency (%) | 56.4834 | 72.0936 | 15.6102 | +27.6% |
| Resource-cost proxy | 0.1328 | 0.1615 | 0.0287 | +21.6% |
| Scaling events | 8 | 17 | 9 | +112.5% |
| Oscillations (reversals) | 0 | 0 | 0 | — |

### flexascale_v4: gradual_ramp (25 users, 300 s)

Baseline `20261024-182809-shopping-hpa-gradual_ramp` vs candidate `20261024-183930-shopping-flexascale-gradual_ramp`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 7.0733 | 7.0162 | -0.0571 | -0.8% |
| Failure rate (%) | 7.0159 | 7.0275 | 0.0116 | +0.2% |
| p50 latency (ms) | 110.0000 | 130.0000 | 20.0000 | +18.2% |
| p95 latency (ms) | 2,200.0000 | 3,100.0000 | 900.0000 | +40.9% |
| p99 latency (ms) | 6,000.0000 | 6,000.0000 | 0.0000 | +0.0% |
| E2E p95 SLO violation (s) | 295.3000 | 240.2000 | -55.1000 | -18.7% |
| Avg total replicas | 14.2900 | 12.4800 | -1.8100 | -12.7% |
| Peak total replicas | 25 | 19 | -6 | -24.0% |
| Replica-hours | 1.1059 | 0.9842 | -0.1217 | -11.0% |
| Allocated vCPU-hours | 0.1106 | 0.0984 | -0.0122 | -11.0% |
| CPU allocation efficiency (%) | 83.2016 | 59.2878 | -23.9138 | -28.7% |
| Resource-cost proxy | 0.1279 | 0.1138 | -0.0141 | -11.0% |
| Scaling events | 10 | 11 | 1 | +10.0% |
| Oscillations (reversals) | 0 | 0 | 0 | — |

### flexascale_v4: payment_degradation (25 users, 300 s)

Baseline `20261024-172006-shopping-hpa-payment_degradation` vs candidate `20261024-173657-shopping-flexascale-payment_degradation`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 9.0266 | 10.2037 | 1.1771 | +13.0% |
| Failure rate (%) | 21.8475 | 32.1509 | 10.3034 | +47.2% |
| p50 latency (ms) | 300.0000 | 280.0000 | -20.0000 | -6.7% |
| p95 latency (ms) | 4,100.0000 | 2,100.0000 | -2,000.0000 | -48.8% |
| p99 latency (ms) | 6,000.0000 | 6,000.0000 | 0.0000 | +0.0% |
| E2E p95 SLO violation (s) | 275.2000 | 255.2000 | -20.0000 | -7.3% |
| Avg total replicas | 13.9000 | 15.1700 | 1.2700 | +9.1% |
| Peak total replicas | 20 | 21 | 1 | +5.0% |
| Replica-hours | 1.1011 | 1.2121 | 0.1110 | +10.1% |
| Allocated vCPU-hours | 0.1101 | 0.1212 | 0.0111 | +10.1% |
| CPU allocation efficiency (%) | 70.8334 | 70.0569 | -0.7765 | -1.1% |
| Resource-cost proxy | 0.1273 | 0.1401 | 0.0128 | +10.1% |
| Scaling events | 9 | 14 | 5 | +55.6% |
| Oscillations (reversals) | 0 | 0 | 0 | — |

### flexascale_v4: steady_browsing (25 users, 300 s)

Baseline `20261024-152728-shopping-hpa-steady_browsing` vs candidate `20261024-153329-shopping-flexascale-steady_browsing`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 11.3570 | 11.0200 | -0.3371 | -3.0% |
| Failure rate (%) | 3.3043 | 3.3164 | 0.0121 | +0.4% |
| p50 latency (ms) | 53.0000 | 74.0000 | 21.0000 | +39.6% |
| p95 latency (ms) | 1,000.0000 | 1,500.0000 | 500.0000 | +50.0% |
| p99 latency (ms) | 6,000.0000 | 6,000.0000 | 0.0000 | +0.0% |
| E2E p95 SLO violation (s) | 130.2000 | 200.2000 | 70.0000 | +53.8% |
| Avg total replicas | 14.5000 | 14.9700 | 0.4700 | +3.2% |
| Peak total replicas | 19 | 18 | -1 | -5.3% |
| Replica-hours | 1.1942 | 1.2384 | 0.0442 | +3.7% |
| Allocated vCPU-hours | 0.1194 | 0.1238 | 0.0044 | +3.7% |
| CPU allocation efficiency (%) | 59.2872 | 58.5207 | -0.7665 | -1.3% |
| Resource-cost proxy | 0.1381 | 0.1432 | 0.0051 | +3.7% |
| Scaling events | 9 | 8 | -1 | -11.1% |
| Oscillations (reversals) | 0 | 0 | 0 | — |

### flexascale_v4: traffic_drop (25 users, 300 s)

Baseline `20261024-185611-shopping-hpa-traffic_drop` vs candidate `20261024-191302-shopping-flexascale-traffic_drop`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 4.7201 | 4.8634 | 0.1434 | +3.0% |
| Failure rate (%) | 7.4100 | 5.8020 | -1.6080 | -21.7% |
| p50 latency (ms) | 130.0000 | 130.0000 | 0.0000 | +0.0% |
| p95 latency (ms) | 5,000.0000 | 3,900.0000 | -1,100.0000 | -22.0% |
| p99 latency (ms) | 6,100.0000 | 6,000.0000 | -100.0000 | -1.6% |
| E2E p95 SLO violation (s) | 285.3000 | 295.3000 | 10.0000 | +3.5% |
| Avg total replicas | 18.2900 | 21.1700 | 2.8800 | +15.8% |
| Peak total replicas | 24 | 30 | 6 | +25.0% |
| Replica-hours | 1.4768 | 1.6870 | 0.2103 | +14.2% |
| Allocated vCPU-hours | 0.1477 | 0.1687 | 0.0210 | +14.2% |
| CPU allocation efficiency (%) | 53.9810 | 49.1671 | -4.8139 | -8.9% |
| Resource-cost proxy | 0.1708 | 0.1951 | 0.0243 | +14.2% |
| Scaling events | 10 | 17 | 7 | +70.0% |
| Oscillations (reversals) | 0 | 0 | 0 | — |

## FlexaScale model `flexascale_v3` vs native HPA

| Scenario | Users | HPA run | FlexaScale run | Comparable | Δ p95 % | Δ throughput % | Δ failures pp | Δ SLO-violation s | Δ replica-h % | Δ cost proxy % |
| :--- | ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| flash_sale | 25 | `20261023-001403-shopping-hpa-flash_sale` | `20261023-002554-shopping-flexascale-flash_sale` | True | +50.0% | -16.0% | +0.4 | 20 | +77.0% | +77.0% |
| flash_sale | 40 | `20261022-233616-shopping-hpa-flash_sale` | `20261022-234747-shopping-flexascale-flash_sale` | False | — | — | +38.7 | 70 | — | — |
| gradual_ramp | 25 | `20261023-004215-shopping-hpa-gradual_ramp` | `20261023-005916-shopping-flexascale-gradual_ramp` | True | +13.3% | -3.1% | +0.5 | 40 | +98.0% | +98.0% |
| traffic_drop | 25 | `20261023-011607-shopping-hpa-traffic_drop` | `20261023-013258-shopping-flexascale-traffic_drop` | True | +10.5% | -1.0% | +0.6 | 55 | +57.6% | +57.6% |

Mean over 3 comparable pair(s): p95 latency +24.6%, throughput -6.7%, failure rate +0.5 pp, replica-hours +77.5%, resource-cost proxy +77.5% (negative cost = saving relative to HPA in the same scenario).

### flexascale_v3: flash_sale (25 users, 300 s)

Baseline `20261023-001403-shopping-hpa-flash_sale` vs candidate `20261023-002554-shopping-flexascale-flash_sale`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 10.4399 | 8.7721 | -1.6677 | -16.0% |
| Failure rate (%) | 2.0727 | 2.5047 | 0.4320 | +20.8% |
| p50 latency (ms) | 240.0000 | 280.0000 | 40.0000 | +16.7% |
| p95 latency (ms) | 1,400.0000 | 2,100.0000 | 700.0000 | +50.0% |
| p99 latency (ms) | 3,800.0000 | 4,500.0000 | 700.0000 | +18.4% |
| E2E p95 SLO violation (s) | 180.0000 | 200.2000 | 20.2000 | +11.2% |
| Avg total replicas | 15.5200 | 29.4300 | 13.9100 | +89.6% |
| Peak total replicas | 24 | 34 | 10 | +41.7% |
| Replica-hours | 1.2458 | 2.2047 | 0.9589 | +77.0% |
| Allocated vCPU-hours | 0.1246 | 0.2205 | 0.0959 | +77.0% |
| CPU allocation efficiency (%) | 69.8321 | 37.8417 | -31.9903 | -45.8% |
| Resource-cost proxy | 0.1440 | 0.2549 | 0.1109 | +77.0% |
| Scaling events | 9 | 16 | 7 | +77.8% |
| Oscillations (reversals) | 0 | 0 | 0 | — |

### flexascale_v3: flash_sale (40 users, 300 s)

Baseline `20261022-233616-shopping-hpa-flash_sale` vs candidate `20261022-234747-shopping-flexascale-flash_sale`. Comparable: **False** (durations differ by more than 10% (306s vs 434s); at least one run did not start from settled minimum replicas)

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 13.3393 | 5.2561 | -8.0833 | — |
| Failure rate (%) | 3.9392 | 42.6158 | 38.6766 | — |
| p50 latency (ms) | 310.0000 | 310.0000 | 0.0000 | — |
| p95 latency (ms) | 2,600.0000 | 10,000.0000 | 7,400.0000 | — |
| p99 latency (ms) | 6,000.0000 | 14,000.0000 | 8,000.0000 | — |
| E2E p95 SLO violation (s) | 185.0000 | 255.1000 | 70.1000 | — |
| Avg total replicas | 21.6200 | 39.6100 | 17.9900 | — |
| Peak total replicas | 33 | 45 | 12 | — |
| Replica-hours | 1.4178 | 3.9554 | 2.5376 | — |
| Allocated vCPU-hours | 0.1418 | 0.3955 | 0.2538 | — |
| CPU allocation efficiency (%) | 112.3982 | — | — | — |
| Resource-cost proxy | 0.1639 | 0.4573 | 0.2934 | — |
| Scaling events | 12 | 16 | 4 | — |
| Oscillations (reversals) | 0 | 0 | 0 | — |

### flexascale_v3: gradual_ramp (25 users, 300 s)

Baseline `20261023-004215-shopping-hpa-gradual_ramp` vs candidate `20261023-005916-shopping-flexascale-gradual_ramp`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 7.0546 | 6.8357 | -0.2190 | -3.1% |
| Failure rate (%) | 6.4486 | 6.9645 | 0.5159 | +8.0% |
| p50 latency (ms) | 130.0000 | 170.0000 | 40.0000 | +30.8% |
| p95 latency (ms) | 3,000.0000 | 3,400.0000 | 400.0000 | +13.3% |
| p99 latency (ms) | 6,000.0000 | 6,000.0000 | 0.0000 | +0.0% |
| E2E p95 SLO violation (s) | 195.2000 | 235.3000 | 40.1000 | +20.5% |
| Avg total replicas | 13.9800 | 27.1200 | 13.1400 | +94.0% |
| Peak total replicas | 25 | 33 | 8 | +32.0% |
| Replica-hours | 1.1096 | 2.1971 | 1.0875 | +98.0% |
| Allocated vCPU-hours | 0.1110 | 0.2197 | 0.1088 | +98.0% |
| CPU allocation efficiency (%) | 68.8690 | 40.6455 | -28.2234 | -41.0% |
| Resource-cost proxy | 0.1283 | 0.2540 | 0.1257 | +98.0% |
| Scaling events | 13 | 16 | 3 | +23.1% |
| Oscillations (reversals) | 0 | 0 | 0 | — |

### flexascale_v3: traffic_drop (25 users, 300 s)

Baseline `20261023-011607-shopping-hpa-traffic_drop` vs candidate `20261023-013258-shopping-flexascale-traffic_drop`. Comparable: **True**

| Metric | HPA | FlexaScale | Δ | Δ % |
| :--- | ---: | ---: | ---: | ---: |
| Throughput (req/s) | 5.4973 | 5.4410 | -0.0563 | -1.0% |
| Failure rate (%) | 6.7518 | 7.3529 | 0.6011 | +8.9% |
| p50 latency (ms) | 77.0000 | 95.0000 | 18.0000 | +23.4% |
| p95 latency (ms) | 1,900.0000 | 2,100.0000 | 200.0000 | +10.5% |
| p99 latency (ms) | 6,000.0000 | 6,000.0000 | 0.0000 | +0.0% |
| E2E p95 SLO violation (s) | 190.0000 | 245.2000 | 55.2000 | +29.1% |
| Avg total replicas | 14.6700 | 23.7300 | 9.0600 | +61.8% |
| Peak total replicas | 17 | 28 | 11 | +64.7% |
| Replica-hours | 1.1927 | 1.8794 | 0.6867 | +57.6% |
| Allocated vCPU-hours | 0.1193 | 0.1879 | 0.0687 | +57.6% |
| CPU allocation efficiency (%) | 55.9262 | 38.2978 | -17.6284 | -31.5% |
| Resource-cost proxy | 0.1379 | 0.2173 | 0.0794 | +57.6% |
| Scaling events | 6 | 14 | 8 | +133.3% |
| Oscillations (reversals) | 0 | 1 | 1 | — |

## Notes on the v3 runs

- v3 (`models/flexascale_v3`) scaled every service up on almost every decision, also in simulation; its live runs used 58-98% more replica-hours without better latency. The cause (simulator and reward defects) and the v4 redesign are in `docs/POLICY_V4.md`.
- Earlier 40-user runs (2026-10-22 23:36 and 23:47) are excluded: the FlexaScale run started unsettled and exhausted node memory (45 replicas, 42.6% failures, API server down). That incident led to the app-wide replica budget.

## Notes on the v4 runs

- v4 (`models/flexascale_v4/best_model`, selection in `docs/POLICY_V4.md`) ran all six scenarios on 2026-10-24, alternating with HPA, 25 users, 300 s, with `scale_up_cooldown_seconds: 30`.
- The per-scenario differences point in both directions (e.g. p95 −49% but failures +10 pp under payment degradation; p95 +50% under steady browsing). With one run per arm they cannot be separated from run-to-run noise.
- One HPA checkout_heavy run (2026-10-24 15:45) was invalidated by a host suspend and moved to `reports/experiments_invalid/` with the reason; it was rerun.

## How to read the cost rows

- *Replica-hours* and *allocated vCPU/GiB-hours* integrate the ready replicas x requested resources over the run.
- *CPU allocation efficiency* = observed CPU (cAdvisor) / allocated CPU.
- *Resource-cost proxy* = vCPU-h + 0.125 x GiB-h of requested resources (no prices are configured for the shop). It is unitless and not a cloud bill. A negative Δ% is a saving relative to HPA in the same scenario only.
- Lower latency bought with more replicas is a trade-off, not a free improvement; both directions are reported.

## Data checks

- Runs found: 33; complete: 23. Runs whose cleanup was not verified safe: `20261022-234747-shopping-flexascale-flash_sale` (completed), `20261023-000028-shopping-hpa-steady_browsing` (failed), `20261023-000038-shopping-flexascale-steady_browsing` (failed), `20261023-000048-shopping-hpa-gradual_ramp` (failed), `20261023-000058-shopping-flexascale-gradual_ramp` (failed), `20261023-000108-shopping-hpa-checkout_heavy` (failed), `20261023-000118-shopping-flexascale-checkout_heavy` (failed), `20261023-000128-shopping-hpa-traffic_drop` (failed), `20261023-000138-shopping-flexascale-traffic_drop` (failed). Failed runs never started load (preflight refusals); the completed one is the excluded 40-user incident run.
- `requests` (Locust final stats) and `requests_seen_in_samples` (last 5 s sample) are both listed in the CSV; they differ only by requests completed after the last sample.
