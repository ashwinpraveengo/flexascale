# Invalid runs (kept for transparency, excluded from all reports)

| Run | Reason |
| :--- | :--- |
| 20261024-154539-shopping-hpa-checkout_heavy | Host laptop suspended (systemd-logind) at 15:52:34, ~50 s into the workload, and resumed at 16:51. Load, metrics and controller were frozen for ~58 min. Rerun under `systemd-inhibit`. |
