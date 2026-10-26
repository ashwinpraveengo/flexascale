# HPA-tuned calibration (docs/POLICY_V7.md §2.1)

Rule, fixed before any calibration run: HPA-tuned's CPU target is the highest grid value T for which T and every lower value meet, on the mean of their valid runs, p95 ≤ 1.10 × p95(70%), mean latency ≤ 1.10 × mean(70%) and failure rate ≤ failure(70%) + 0.10 pp. Scale-down window 60 s for every value.

| CPU target (% of request) | valid runs | p95 ms | mean ms | failures % | replica-h | throughput req/s | meets rule |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| 70 | 2 | 205 | 60.2 | 0.336 | 1.569 | 17.36 | yes |
| 150 | 2 | 210 | 62.2 | 0.259 | 1.381 | 17.35 | yes |
| 250 | 2 | 210 | 61.5 | 0.299 | 1.356 | 17.26 | yes |
| 350 | 2 | 230 | 68.0 | 0.340 | 1.357 | 17.10 | no |

**Selected HPA-tuned CPU target: 250% of request** (scale-down window 60 s).

Runs used:

* `20261027-014406-shopping-hpa_tuned-calibration_steady` (70%)
* `20261027-020623-shopping-hpa_tuned-calibration_steady` (70%)
* `20261027-015005-shopping-hpa_tuned-calibration_steady` (150%)
* `20261027-022925-shopping-hpa_tuned-calibration_steady` (150%)
* `20261027-021746-shopping-hpa_tuned-calibration_steady` (250%)
* `20261027-024524-shopping-hpa_tuned-calibration_steady` (250%)
* `20261027-004540-shopping-hpa_tuned-calibration_steady` (350%)
* `20261027-005147-shopping-hpa_tuned-calibration_steady` (350%)
