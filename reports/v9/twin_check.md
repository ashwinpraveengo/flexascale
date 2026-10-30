# Twin check against this laptop's calibration runs (docs/POLICY_V9.md §5)

HPA with a 60 s scale-down window, workload calibration_steady (25 users, 300 s); twin = mean of 5 seeds, live = mean of the valid runs (2 per target). Reported only; no threshold.

| CPU target | live replica-h | v9 twin | v7 twin | live p95 ms | v9 twin | v7 twin | live mean ms | v9 twin | v7 twin |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 70% | 1.423 | 1.393 | 1.446 | 135 | 114 | 151 | 36 | 34 | 41 |
| 150% | 1.360 | 1.333 | 1.333 | 115 | 114 | 151 | 34 | 34 | 42 |
| 250% | 1.360 | 1.333 | 1.333 | 120 | 114 | 151 | 34 | 34 | 42 |
| 350% | 1.360 | 1.333 | 1.333 | 135 | 114 | 151 | 37 | 34 | 42 |

Mean absolute error over the four targets:

* v9 twin: replica-hours 2.0%, p95 8.9%, mean latency 4.4%
* v7 twin: replica-hours 1.9%, p95 20.5%, mean latency 17.7%
