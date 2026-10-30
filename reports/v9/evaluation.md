# v9 live evaluation on the second laptop (docs/POLICY_V9.md §6)

46 valid runs in 12 blocks; 0 excluded. Pairs are within block; Δ = candidate − reference; 95% t-intervals over pairs; d_z = mean / SD of the paired differences.

## Arms (means over valid runs)

| Arm | runs | replica-h | cost USD | p50 ms | p95 ms | p99 ms | mean ms | failures % | req/s | e2e SLO s | events | osc |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HPA-default | 12 | 1.512 | 0.00685 | 44 | 241 | 838 | 85 | 0.291 | 15.13 | 22.9 | 3.0 | 0.0 |
| HPA-tuned | 12 | 1.366 | 0.00618 | 42 | 167 | 510 | 71 | 0.248 | 15.37 | 8.0 | 0.2 | 0.1 |
| FlexaScale-RL | 11 | 1.368 | 0.00619 | 37 | 395 | 1674 | 110 | 0.335 | 15.07 | 25.6 | 0.4 | 0.2 |
| FlexaScale-Auto | 11 | 1.365 | 0.00618 | 37 | 200 | 1936 | 94 | 0.321 | 15.15 | 15.7 | 0.2 | 0.1 |

## Against HPA-tuned

### HPA-default vs HPA-tuned: **Worse** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | +10.6% [+4.2 … +17.1] | +1.05 |
| Estimated cost | +10.8% [+4.3 … +17.4] | +1.05 |
| p50 | -0.0% [-4.3 … +4.3] | -0.00 |
| p95 | +28.1% [-11.5 … +67.7] | +0.45 |
| p99 | +67.7% [-4.7 … +140.0] | +0.59 |
| Mean latency | +15.2% [-10.0 … +40.4] | +0.38 |
| Failures | +0.04 pp [-0.08 … +0.17] | +0.22 |
| Throughput | -1.8% [-4.4 … +0.9] | -0.42 |
| E2E SLO violation (s) | +15.0 s [-4.8 … +34.7] | +0.48 |
| Oscillations | -0.1 [-0.3 … +0.1] | -0.29 |
| Scaling events | +2.8 [+1.2 … +4.3] | +1.10 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): no; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: no; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: no

Environment: shop CPU per request in steady_browsing +0.7% (candidate vs reference); mean CPU clock not recorded.

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: +18.0 / +16.0  |  +0.0 / +5.9
* flash_sale: +31.9 / +26.4  |  +28.1 / +132.5
* gradual_ramp: +1.7 / +2.2  |  +17.9 / -11.8
* payment_degradation: +4.3 / +8.6  |  +0.0 / -5.3
* steady_browsing: +3.6 / +3.6  |  +9.1 / +0.0
* traffic_drop: +4.1 / +7.2  |  -20.2 / +181.2

### FlexaScale-RL vs HPA-tuned: **On par / inconclusive** (11 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | +0.3% [-0.2 … +0.7] | +0.42 |
| Estimated cost | +0.3% [-0.2 … +0.8] | +0.42 |
| p50 | +7.6% [-4.9 … +20.2] | +0.41 |
| p95 | +155.0% [-164.7 … +474.6] | +0.33 |
| p99 | +159.6% [-103.8 … +423.1] | +0.41 |
| Mean latency | +82.8% [-84.3 … +249.9] | +0.33 |
| Failures | +0.10 pp [-0.13 … +0.34] | +0.29 |
| Throughput | -2.4% [-7.5 … +2.7] | -0.32 |
| E2E SLO violation (s) | +16.9 s [-5.3 … +39.0] | +0.51 |
| Oscillations | +0.2 [-0.1 … +0.5] | +0.45 |
| Scaling events | +0.3 [-0.2 … +0.7] | +0.42 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): no; C3 failures not worse (interval not > 0, mean <= +0.10 pp): no; C4 throughput mean >= -2%: no; C5 e2e SLO violation mean <= +5 s: no; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: no

Environment: shop CPU per request in steady_browsing +8.9% (candidate vs reference); mean CPU clock not recorded.

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: +0.0 / +0.0  |  +6.2 / +11.8
* flash_sale: +1.0  |  -17.5
* gradual_ramp: -0.0 / -0.0  |  +28.2 / +82.4
* payment_degradation: +0.0 / +0.0  |  +6.7 / -5.3
* steady_browsing: -0.0 / -0.0  |  +3.6 / +8.9
* traffic_drop: +0.0 / +2.1  |  -8.1 / +1587.5

### FlexaScale-Auto vs HPA-tuned: **On par / inconclusive** (11 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | +0.2% [-0.2 … +0.5] | +0.31 |
| Estimated cost | +0.2% [-0.2 … +0.5] | +0.32 |
| p50 | +7.4% [+3.3 … +11.5] | +1.20 |
| p95 | +41.5% [-22.6 … +105.7] | +0.43 |
| p99 | +153.5% [-109.9 … +416.9] | +0.39 |
| Mean latency | +57.0% [-33.3 … +147.2] | +0.42 |
| Failures | +0.08 pp [-0.11 … +0.28] | +0.29 |
| Throughput | -2.2% [-5.9 … +1.4] | -0.41 |
| E2E SLO violation (s) | +7.5 s [-2.4 … +17.3] | +0.51 |
| Oscillations | +0.0 [+0.0 … +0.0] |  |
| Scaling events | +0.0 [+0.0 … +0.0] |  |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): no; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: no; C5 e2e SLO violation mean <= +5 s: no; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: no

Environment: shop CPU per request in steady_browsing +6.8% (candidate vs reference); mean CPU clock not recorded.

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -0.0 / +0.0  |  +6.2 / +11.8
* flash_sale: +1.7  |  -37.5
* gradual_ramp: -0.0 / +0.5  |  +53.8 / +52.9
* payment_degradation: +0.0 / +0.0  |  +6.7 / -5.3
* steady_browsing: -0.0 / -0.0  |  +7.3 / +10.7
* traffic_drop: +0.0 / -0.3  |  +31.3 / +318.8


## Against HPA-default

### HPA-tuned vs HPA-default: **Beats on cost** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -9.0% [-13.9 … -4.1] | -1.16 |
| Estimated cost | -9.1% [-14.0 … -4.1] | -1.17 |
| p50 | +0.4% [-3.8 … +4.7] | +0.06 |
| p95 | -10.7% [-27.5 … +6.1] | -0.40 |
| p99 | -2.4% [-62.0 … +57.1] | -0.03 |
| Mean latency | -5.6% [-22.4 … +11.1] | -0.21 |
| Failures | -0.04 pp [-0.17 … +0.08] | -0.22 |
| Throughput | +2.0% [-1.0 … +5.0] | +0.42 |
| E2E SLO violation (s) | -15.0 s [-34.7 … +4.8] | -0.48 |
| Oscillations | +0.1 [-0.1 … +0.3] | +0.29 |
| Scaling events | -2.8 [-4.3 … -1.2] | -1.10 |

Checks: C1 replica-h interval < 0: yes; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Environment: shop CPU per request in steady_browsing -0.7% (candidate vs reference); mean CPU clock not recorded.

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -15.3 / -13.8  |  +0.0 / -5.6
* flash_sale: -24.2 / -20.9  |  -22.0 / -57.0
* gradual_ramp: -1.7 / -2.1  |  -15.2 / +13.3
* payment_degradation: -4.2 / -7.9  |  +0.0 / +5.6
* steady_browsing: -3.4 / -3.5  |  -8.3 / +0.0
* traffic_drop: -3.9 / -6.7  |  +25.3 / -64.4

### FlexaScale-RL vs HPA-default: **On par / inconclusive** (11 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -7.3% [-11.5 … -3.2] | -1.18 |
| Estimated cost | -7.4% [-11.7 … -3.2] | -1.18 |
| p50 | +8.2% [-1.4 … +17.9] | +0.57 |
| p95 | +53.5% [-49.4 … +156.4] | +0.35 |
| p99 | +64.2% [-34.7 … +163.2] | +0.44 |
| Mean latency | +37.7% [-29.9 … +105.2] | +0.37 |
| Failures | +0.04 pp [-0.21 … +0.29] | +0.12 |
| Throughput | -0.8% [-5.7 … +4.1] | -0.11 |
| E2E SLO violation (s) | +3.3 s [-25.2 … +31.7] | +0.08 |
| Oscillations | +0.2 [-0.1 … +0.5] | +0.45 |
| Scaling events | -2.2 [-3.7 … -0.7] | -0.98 |

Checks: C1 replica-h interval < 0: yes; C2 p95 not worse (interval not > 0, mean <= +10%): no; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Environment: shop CPU per request in steady_browsing +8.1% (candidate vs reference); mean CPU clock not recorded.

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -15.3 / -13.8  |  +6.2 / +5.6
* flash_sale: -20.1  |  -64.5
* gradual_ramp: -1.7 / -2.1  |  +8.7 / +106.7
* payment_degradation: -4.1 / -7.9  |  +6.7 / +0.0
* steady_browsing: -3.5 / -3.5  |  -5.0 / +8.9
* traffic_drop: -3.9 / -4.7  |  +15.2 / +500.0

### FlexaScale-Auto vs HPA-default: **On par / inconclusive** (11 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -7.7% [-12.3 … -3.2] | -1.14 |
| Estimated cost | -7.9% [-12.5 … -3.2] | -1.14 |
| p50 | +8.3% [+5.5 … +11.0] | +2.03 |
| p95 | +17.6% [-6.0 … +41.2] | +0.50 |
| p99 | +141.0% [-115.3 … +397.3] | +0.37 |
| Mean latency | +41.3% [-26.4 … +109.1] | +0.41 |
| Failures | +0.09 pp [-0.10 … +0.27] | +0.32 |
| Throughput | -1.4% [-4.5 … +1.6] | -0.31 |
| E2E SLO violation (s) | +1.1 s [-10.4 … +12.7] | +0.07 |
| Oscillations | +0.1 [-0.1 … +0.3] | +0.30 |
| Scaling events | -2.2 [-3.3 … -1.1] | -1.36 |

Checks: C1 replica-h interval < 0: yes; C2 p95 not worse (interval not > 0, mean <= +10%): no; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Environment: shop CPU per request in steady_browsing +6.0% (candidate vs reference); mean CPU clock not recorded.

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -15.3 / -13.8  |  +6.2 / +5.6
* flash_sale: -22.9  |  -51.2
* gradual_ramp: -1.7 / -1.6  |  +30.4 / +73.3
* payment_degradation: -4.1 / -7.9  |  +6.7 / +0.0
* steady_browsing: -3.5 / -3.5  |  -1.7 / +10.7
* traffic_drop: -3.9 / -7.0  |  +64.6 / +48.9

## Recovery after load decreases (descriptive, flash_sale and traffic_drop)

Seconds from the phase change that lowers users until total desired replicas are within 1 of the run's minimum.

| Arm | runs | mean s | values |
| :--- | ---: | ---: | :--- |
| HPA-default | 4 | 96 | 105, 4, 108, 165 |
| HPA-tuned | 4 | 4 | 4, 4, 4, 4 |
| FlexaScale-RL | 3 | 4 | 4, 4, 4 |
| FlexaScale-Auto | 3 | 3 | 4, 4, 0 |

## Attribution (replica changes by owner during the runs)

| Arm | changes by owner (sum over runs) | Auto rule decisions |
| :--- | :--- | :--- |
| HPA-default | HPA up: 36 | – |
| HPA-tuned | HPA down: 1, HPA up: 2 | – |
| FlexaScale-RL | FlexaScale down: 2, FlexaScale up: 2 | – |
| FlexaScale-Auto | FlexaScale down: 1, FlexaScale up: 1 | efficiency: 5024 |
