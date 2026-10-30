# HPA-tuned calibration (docs/POLICY_V7.md §2.1)

Rule, fixed before any calibration run: HPA-tuned's CPU target is the highest grid value T for which T and every lower value meet, on the mean of their valid runs, p95 ≤ 1.10 × p95(70%), mean latency ≤ 1.10 × mean(70%) and failure rate ≤ failure(70%) + 0.10 pp. Scale-down window 60 s for every value.

| CPU target (% of request) | valid runs | p95 ms | mean ms | failures % | replica-h | throughput req/s | meets rule |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| 70 | 2 | 135 | 36.3 | 0.047 | 1.423 | 17.76 | yes |
| 150 | 2 | 115 | 33.7 | 0.057 | 1.360 | 17.44 | yes |
| 250 | 2 | 120 | 33.9 | 0.105 | 1.360 | 17.51 | yes |
| 350 | 2 | 135 | 37.4 | 0.047 | 1.360 | 17.71 | yes |

**Selected HPA-tuned CPU target: 350% of request** (scale-down window 60 s).

Runs used:

* `20261028-234234-shopping-hpa_tuned-calibration_steady` (70%)
* `20261029-101022-shopping-hpa_tuned-calibration_steady` (70%)
* `20261029-103315-shopping-hpa_tuned-calibration_steady` (150%)
* `20261029-124341-shopping-hpa_tuned-calibration_steady` (150%)
* `20261029-102134-shopping-hpa_tuned-calibration_steady` (250%)
* `20261029-104937-shopping-hpa_tuned-calibration_steady` (250%)
* `20261028-232543-shopping-hpa_tuned-calibration_steady` (350%)
* `20261029-110108-shopping-hpa_tuned-calibration_steady` (350%)
