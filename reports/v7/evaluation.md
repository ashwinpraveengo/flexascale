# v7 live evaluation (docs/POLICY_V7.md §3)

60 valid runs in 12 blocks; 0 excluded. Pairs are within block; Δ = candidate − reference; 95% t-intervals over pairs; d_z = mean / SD of the paired differences.

## Arms (means over valid runs)

| Arm | runs | replica-h | cost USD | p50 ms | p95 ms | p99 ms | mean ms | failures % | req/s | e2e SLO s | events | osc |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HPA-default | 12 | 1.578 | 0.00716 | 68 | 944 | 2140 | 209 | 0.729 | 13.42 | 67.1 | 4.1 | 0.0 |
| HPA-tuned | 12 | 1.363 | 0.00617 | 64 | 782 | 2067 | 185 | 0.555 | 13.64 | 68.0 | 0.2 | 0.0 |
| FlexaScale-RL | 12 | 1.364 | 0.00617 | 55 | 651 | 1878 | 160 | 0.482 | 13.96 | 55.0 | 0.2 | 0.1 |
| FlexaScale-Auto | 12 | 1.366 | 0.00618 | 56 | 553 | 1751 | 151 | 0.488 | 14.03 | 49.6 | 0.5 | 0.2 |
| FlexaScale-heuristic | 12 | 1.361 | 0.00616 | 56 | 568 | 1747 | 150 | 0.418 | 14.11 | 49.2 | 0.3 | 0.2 |

## Against HPA-tuned

### HPA-default vs HPA-tuned: **Worse** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | +15.8% [+10.1 … +21.5] | +1.75 |
| Estimated cost | +16.0% [+10.2 … +21.8] | +1.76 |
| p50 | +2.8% [-9.0 … +14.6] | +0.15 |
| p95 | +10.4% [-3.4 … +24.3] | +0.48 |
| p99 | +11.7% [-12.5 … +35.8] | +0.31 |
| Mean latency | +7.8% [-3.0 … +18.7] | +0.46 |
| Failures | +0.17 pp [-0.23 … +0.58] | +0.27 |
| Throughput | -1.8% [-4.3 … +0.7] | -0.47 |
| E2E SLO violation (s) | -0.8 s [-11.0 … +9.4] | -0.05 |
| Oscillations | +0.0 [+0.0 … +0.0] |  |
| Scaling events | +3.9 [+2.9 … +5.0] | +2.34 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): no; C3 failures not worse (interval not > 0, mean <= +0.10 pp): no; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: no

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: +31.4 / +30.0  |  -13.4 / +56.0
* flash_sale: +19.8 / +14.2  |  +6.7 / +17.6
* gradual_ramp: +3.7 / +3.2  |  +34.8 / -30.4
* payment_degradation: +16.4 / +16.4  |  +0.0 / +15.4
* steady_browsing: +8.0 / +9.4  |  +1.4 / +10.0
* traffic_drop: +19.7 / +16.8  |  +16.0 / +11.1

### FlexaScale-RL vs HPA-tuned: **On par / inconclusive** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | +0.0% [-0.1 … +0.2] | +0.16 |
| Estimated cost | +0.0% [-0.1 … +0.2] | +0.16 |
| p50 | -16.6% [-26.2 … -7.0] | -1.10 |
| p95 | -2.5% [-40.0 … +35.1] | -0.04 |
| p99 | +8.4% [-33.1 … +49.8] | +0.13 |
| Mean latency | -9.5% [-26.5 … +7.5] | -0.36 |
| Failures | -0.07 pp [-0.20 … +0.06] | -0.36 |
| Throughput | +2.4% [-0.8 … +5.7] | +0.48 |
| E2E SLO violation (s) | -12.9 s [-34.2 … +8.3] | -0.39 |
| Oscillations | +0.1 [-0.1 … +0.3] | +0.29 |
| Scaling events | +0.1 [-0.1 … +0.3] | +0.29 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -0.0 / -0.0  |  -34.3 / +0.0
* flash_sale: -0.2 / +0.9  |  -39.3 / -29.4
* gradual_ramp: -0.0 / -0.0  |  +4.3 / -54.3
* payment_degradation: -0.0 / -0.0  |  +172.0 / -29.2
* steady_browsing: -0.0 / -0.0  |  -8.6 / +0.0
* traffic_drop: +0.0 / -0.0  |  +20.0 / -30.6

### FlexaScale-Auto vs HPA-tuned: **Beats on performance** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | +0.2% [-0.3 … +0.7] | +0.26 |
| Estimated cost | +0.2% [-0.3 … +0.7] | +0.26 |
| p50 | -17.0% [-25.8 … -8.3] | -1.24 |
| p95 | -21.6% [-33.5 … -9.8] | -1.16 |
| p99 | -7.9% [-26.7 … +10.8] | -0.27 |
| Mean latency | -17.1% [-26.1 … -8.0] | -1.20 |
| Failures | -0.07 pp [-0.20 … +0.06] | -0.33 |
| Throughput | +3.2% [+0.3 … +6.0] | +0.71 |
| E2E SLO violation (s) | -18.3 s [-33.0 … -3.6] | -0.79 |
| Oscillations | +0.2 [-0.0 … +0.5] | +0.55 |
| Scaling events | +0.3 [-0.1 … +0.7] | +0.51 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: no

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: +2.7 / +0.0  |  -25.4 / -12.0
* flash_sale: +0.0 / -0.2  |  -41.3 / -47.1
* gradual_ramp: -0.0 / -0.1  |  +4.3 / -50.0
* payment_degradation: -0.0 / +0.0  |  -12.0 / -40.8
* steady_browsing: -0.0 / -0.0  |  -5.7 / -5.0
* traffic_drop: +0.0 / +0.0  |  -8.0 / -16.7

### FlexaScale-heuristic vs HPA-tuned: **Beats on performance** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -0.1% [-0.3 … +0.0] | -0.50 |
| Estimated cost | -0.1% [-0.3 … +0.0] | -0.50 |
| p50 | -16.6% [-24.4 … -8.7] | -1.34 |
| p95 | -20.4% [-33.5 … -7.3] | -0.99 |
| p99 | -12.8% [-28.2 … +2.6] | -0.53 |
| Mean latency | -17.3% [-25.2 … -9.4] | -1.40 |
| Failures | -0.14 pp [-0.27 … -0.01] | -0.66 |
| Throughput | +3.5% [+0.0 … +6.9] | +0.64 |
| E2E SLO violation (s) | -18.8 s [-36.4 … -1.1] | -0.68 |
| Oscillations | +0.2 [-0.1 … +0.4] | +0.43 |
| Scaling events | +0.2 [-0.1 … +0.4] | +0.43 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -0.0 / -0.0  |  -37.3 / -8.0
* flash_sale: -0.6 / -0.6  |  -56.0 / -41.2
* gradual_ramp: -0.0 / -0.1  |  -17.4 / -47.8
* payment_degradation: -0.0 / -0.0  |  -12.0 / -23.1
* steady_browsing: -0.0 / -0.0  |  -7.1 / -3.0
* traffic_drop: -0.0 / -0.0  |  +8.0 / +0.0


## Against HPA-default

### HPA-tuned vs HPA-default: **Beats on cost** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -13.1% [-17.4 … -8.9] | -1.98 |
| Estimated cost | -13.3% [-17.6 … -9.1] | -1.98 |
| p50 | +0.6% [-12.9 … +14.2] | +0.03 |
| p95 | -5.9% [-18.8 … +6.9] | -0.29 |
| p99 | -3.2% [-19.0 … +12.6] | -0.13 |
| Mean latency | -5.0% [-15.2 … +5.3] | -0.31 |
| Failures | -0.17 pp [-0.58 … +0.23] | -0.27 |
| Throughput | +2.0% [-0.7 … +4.7] | +0.48 |
| E2E SLO violation (s) | +0.8 s [-9.4 … +11.0] | +0.05 |
| Oscillations | +0.0 [+0.0 … +0.0] |  |
| Scaling events | -3.9 [-5.0 … -2.9] | -2.34 |

Checks: C1 replica-h interval < 0: yes; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -23.9 / -23.1  |  +15.5 / -35.9
* flash_sale: -16.5 / -12.4  |  -6.2 / -15.0
* gradual_ramp: -3.6 / -3.1  |  -25.8 / +43.8
* payment_degradation: -14.1 / -14.1  |  +0.0 / -13.3
* steady_browsing: -7.4 / -8.6  |  -1.4 / -9.1
* traffic_drop: -16.5 / -14.4  |  -13.8 / -10.0

### FlexaScale-RL vs HPA-default: **Beats on cost** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -13.1% [-17.3 … -8.9] | -1.97 |
| Estimated cost | -13.3% [-17.6 … -9.0] | -1.97 |
| p50 | -17.8% [-27.0 … -8.7] | -1.23 |
| p95 | -10.0% [-47.6 … +27.6] | -0.17 |
| p99 | +1.6% [-41.8 … +45.1] | +0.02 |
| Mean latency | -15.1% [-32.7 … +2.4] | -0.55 |
| Failures | -0.25 pp [-0.65 … +0.15] | -0.39 |
| Throughput | +4.5% [+0.0 … +9.0] | +0.64 |
| E2E SLO violation (s) | -12.1 s [-36.1 … +11.8] | -0.32 |
| Oscillations | +0.1 [-0.1 … +0.3] | +0.29 |
| Scaling events | -3.8 [-4.9 … -2.8] | -2.26 |

Checks: C1 replica-h interval < 0: yes; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -23.9 / -23.1  |  -24.1 / -35.9
* flash_sale: -16.7 / -11.6  |  -43.1 / -40.0
* gradual_ramp: -3.6 / -3.2  |  -22.6 / -34.4
* payment_degradation: -14.1 / -14.1  |  +172.0 / -38.7
* steady_browsing: -7.4 / -8.6  |  -9.9 / -9.1
* traffic_drop: -16.5 / -14.4  |  +3.4 / -37.5

### FlexaScale-Auto vs HPA-default: **Beats on cost** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -13.0% [-17.0 … -9.0] | -2.04 |
| Estimated cost | -13.2% [-17.3 … -9.1] | -2.05 |
| p50 | -18.6% [-25.5 … -11.6] | -1.70 |
| p95 | -27.9% [-38.2 … -17.6] | -1.72 |
| p99 | -13.6% [-32.8 … +5.6] | -0.45 |
| Mean latency | -22.3% [-30.9 … -13.7] | -1.64 |
| Failures | -0.24 pp [-0.58 … +0.10] | -0.45 |
| Throughput | +5.3% [+0.9 … +9.6] | +0.77 |
| E2E SLO violation (s) | -17.5 s [-36.4 … +1.3] | -0.59 |
| Oscillations | +0.2 [-0.0 … +0.5] | +0.55 |
| Scaling events | -3.6 [-4.5 … -2.7] | -2.60 |

Checks: C1 replica-h interval < 0: yes; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -21.9 / -23.1  |  -13.8 / -43.6
* flash_sale: -16.5 / -12.6  |  -45.0 / -55.0
* gradual_ramp: -3.6 / -3.2  |  -22.6 / -28.1
* payment_degradation: -14.1 / -14.1  |  -12.0 / -48.7
* steady_browsing: -7.4 / -8.6  |  -7.0 / -13.6
* traffic_drop: -16.4 / -14.4  |  -20.7 / -25.0

### FlexaScale-heuristic vs HPA-default: **Beats on cost** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -13.2% [-17.5 … -9.0] | -1.99 |
| Estimated cost | -13.4% [-17.7 … -9.1] | -1.99 |
| p50 | -18.0% [-24.1 … -11.9] | -1.87 |
| p95 | -27.0% [-38.1 … -15.8] | -1.53 |
| p99 | -18.3% [-33.9 … -2.7] | -0.75 |
| Mean latency | -22.2% [-30.3 … -14.2] | -1.75 |
| Failures | -0.31 pp [-0.70 … +0.08] | -0.50 |
| Throughput | +5.6% [+0.6 … +10.6] | +0.72 |
| E2E SLO violation (s) | -17.9 s [-38.3 … +2.4] | -0.56 |
| Oscillations | +0.2 [-0.1 … +0.4] | +0.43 |
| Scaling events | -3.8 [-4.8 … -2.7] | -2.26 |

Checks: C1 replica-h interval < 0: yes; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -23.9 / -23.1  |  -27.6 / -41.0
* flash_sale: -17.1 / -13.0  |  -58.8 / -50.0
* gradual_ramp: -3.6 / -3.2  |  -38.7 / -25.0
* payment_degradation: -14.1 / -14.1  |  -12.0 / -33.3
* steady_browsing: -7.4 / -8.6  |  -8.5 / -11.8
* traffic_drop: -16.5 / -14.4  |  -6.9 / -10.0

## Recovery after load decreases (descriptive, flash_sale and traffic_drop)

Seconds from the phase change that lowers users until total desired replicas are within 1 of the run's minimum.

| Arm | runs | mean s | values |
| :--- | ---: | ---: | :--- |
| HPA-default | 4 | 135 | 105, 165, 105, 165 |
| HPA-tuned | 4 | 5 | 5, 5, 5, 5 |
| FlexaScale-RL | 4 | 5 | 5, 5, 5, 5 |
| FlexaScale-Auto | 4 | 5 | 5, 5, 5, 5 |
| FlexaScale-heuristic | 4 | 5 | 5, 5, 5, 5 |

## Attribution (replica changes by owner during the runs)

| Arm | changes by owner (sum over runs) | Auto rule decisions |
| :--- | :--- | :--- |
| HPA-default | HPA up: 49 | – |
| HPA-tuned | HPA up: 2 | – |
| FlexaScale-RL | FlexaScale down: 1, FlexaScale up: 2 | – |
| FlexaScale-Auto | FlexaScale down: 3, FlexaScale up: 3 | efficiency: 5952 |
| FlexaScale-heuristic | FlexaScale down: 2, FlexaScale up: 2 | – |
