# v7 clock-controlled replication (docs/POLICY_V7.md §3.7)

48 valid runs in 12 blocks; 0 excluded. Pairs are within block; Δ = candidate − reference; 95% t-intervals over pairs; d_z = mean / SD of the paired differences.

## Arms (means over valid runs)

| Arm | runs | replica-h | cost USD | p50 ms | p95 ms | p99 ms | mean ms | failures % | req/s | e2e SLO s | events | osc |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HPA-tuned | 12 | 1.361 | 0.00616 | 36 | 282 | 872 | 82 | 0.196 | 15.09 | 12.9 | 0.2 | 0.1 |
| FlexaScale-RL | 12 | 1.362 | 0.00617 | 36 | 295 | 829 | 82 | 0.209 | 15.05 | 11.2 | 0.3 | 0.2 |
| FlexaScale-Auto | 12 | 1.362 | 0.00617 | 35 | 274 | 831 | 80 | 0.219 | 15.10 | 7.1 | 0.3 | 0.2 |
| FlexaScale-heuristic | 12 | 1.361 | 0.00616 | 34 | 277 | 839 | 80 | 0.221 | 15.10 | 10.0 | 0.3 | 0.2 |

## Against HPA-tuned

### FlexaScale-RL vs HPA-tuned: **On par / inconclusive** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | +0.1% [-0.1 … +0.2] | +0.42 |
| Estimated cost | +0.1% [-0.1 … +0.3] | +0.43 |
| p50 | +0.3% [-8.1 … +8.8] | +0.02 |
| p95 | +7.2% [-8.1 … +22.4] | +0.30 |
| p99 | +7.4% [-21.0 … +35.9] | +0.17 |
| Mean latency | +2.0% [-6.9 … +10.9] | +0.14 |
| Failures | +0.01 pp [-0.07 … +0.09] | +0.10 |
| Throughput | -0.3% [-2.1 … +1.5] | -0.11 |
| E2E SLO violation (s) | -1.7 s [-12.1 … +8.7] | -0.10 |
| Oscillations | +0.1 [-0.1 … +0.3] | +0.29 |
| Scaling events | +0.1 [-0.1 … +0.3] | +0.29 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: no

Environment: shop CPU per request in steady_browsing +4.6% (candidate vs reference); mean CPU clock 2447 vs 2342 MHz (Δ +4.5%, mostly busy cores).

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -0.0 / +0.0  |  -16.7 / +1.4
* flash_sale: +0.5 / +0.7  |  +62.9 / -1.9
* gradual_ramp: +0.0 / +0.0  |  -7.7 / +8.3
* payment_degradation: +0.0 / +0.0  |  -8.7 / +45.0
* steady_browsing: +0.0 / -0.0  |  +16.7 / +0.0
* traffic_drop: +0.0 / +0.0  |  +0.0 / -13.3

### FlexaScale-Auto vs HPA-tuned: **On par / inconclusive** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | +0.1% [-0.1 … +0.2] | +0.38 |
| Estimated cost | +0.1% [-0.1 … +0.2] | +0.39 |
| p50 | -1.8% [-9.0 … +5.4] | -0.16 |
| p95 | +0.1% [-9.3 … +9.5] | +0.01 |
| p99 | +8.3% [-19.6 … +36.2] | +0.19 |
| Mean latency | +1.5% [-6.8 … +9.7] | +0.11 |
| Failures | +0.02 pp [-0.04 … +0.09] | +0.23 |
| Throughput | +0.0% [-1.2 … +1.2] | +0.00 |
| E2E SLO violation (s) | -5.9 s [-13.8 … +2.1] | -0.47 |
| Oscillations | +0.1 [-0.1 … +0.3] | +0.29 |
| Scaling events | +0.1 [-0.1 … +0.3] | +0.29 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: no

Environment: shop CPU per request in steady_browsing +5.6% (candidate vs reference); mean CPU clock 2505 vs 2342 MHz (Δ +7.0%, mostly busy cores).

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -0.0 / +0.0  |  -12.5 / -10.8
* flash_sale: +0.3 / +0.7  |  +34.3 / -9.6
* gradual_ramp: +0.0 / -0.0  |  +7.7 / +8.3
* payment_degradation: -0.0 / +0.0  |  -13.0 / +15.0
* steady_browsing: +0.0 / -0.0  |  -2.4 / -10.4
* traffic_drop: +0.0 / -0.0  |  +7.7 / -13.3

### FlexaScale-heuristic vs HPA-tuned: **On par / inconclusive** (12 pairs)

| Metric | Mean Δ [95% CI] | d_z |
| :--- | :--- | ---: |
| Replica-hours | -0.0% [-0.1 … +0.0] | -0.20 |
| Estimated cost | -0.0% [-0.1 … +0.0] | -0.19 |
| p50 | -0.4% [-7.0 … +6.1] | -0.04 |
| p95 | +4.5% [-6.6 … +15.6] | +0.26 |
| p99 | +6.4% [-18.5 … +31.3] | +0.16 |
| Mean latency | +1.5% [-7.6 … +10.5] | +0.10 |
| Failures | +0.02 pp [-0.01 … +0.06] | +0.43 |
| Throughput | +0.0% [-1.1 … +1.2] | +0.01 |
| E2E SLO violation (s) | -2.9 s [-7.4 … +1.5] | -0.42 |
| Oscillations | +0.1 [-0.1 … +0.3] | +0.29 |
| Scaling events | +0.1 [-0.1 … +0.3] | +0.29 |

Checks: C1 replica-h interval < 0: no; C2 p95 not worse (interval not > 0, mean <= +10%): yes; C3 failures not worse (interval not > 0, mean <= +0.10 pp): yes; C4 throughput mean >= -2%: yes; C5 e2e SLO violation mean <= +5 s: yes; C6 oscillations mean <= +5: yes; C7 replica-h lower in >= 4 of 6 scenarios: yes

Environment: shop CPU per request in steady_browsing +4.4% (candidate vs reference); mean CPU clock 2453 vs 2342 MHz (Δ +4.8%, mostly busy cores).

Per scenario (replica-h Δ% per pair; p95 Δ% per pair):

* checkout_heavy: -0.0 / +0.0  |  -12.5 / -12.2
* flash_sale: -0.3 / +0.1  |  +28.6 / -9.6
* gradual_ramp: +0.0 / +0.0  |  +7.7 / +8.3
* payment_degradation: -0.0 / -0.0  |  +0.0 / +35.0
* steady_browsing: +0.0 / +0.0  |  +28.6 / -6.2
* traffic_drop: -0.0 / -0.0  |  +0.0 / -13.3

## Recovery after load decreases (descriptive, flash_sale and traffic_drop)

Seconds from the phase change that lowers users until total desired replicas are within 1 of the run's minimum.

| Arm | runs | mean s | values |
| :--- | ---: | ---: | :--- |
| HPA-tuned | 4 | 5 | 5, 5, 5, 5 |
| FlexaScale-RL | 4 | 5 | 5, 5, 5, 5 |
| FlexaScale-Auto | 4 | 5 | 5, 5, 5, 5 |
| FlexaScale-heuristic | 4 | 5 | 5, 5, 5, 5 |

## Attribution (replica changes by owner during the runs)

| Arm | changes by owner (sum over runs) | Auto rule decisions |
| :--- | :--- | :--- |
| HPA-tuned | HPA down: 1, HPA up: 2 | – |
| FlexaScale-RL | FlexaScale down: 2, FlexaScale up: 2 | – |
| FlexaScale-Auto | FlexaScale down: 2, FlexaScale up: 2 | efficiency: 5952 |
| FlexaScale-heuristic | FlexaScale down: 2, FlexaScale up: 2 | – |
