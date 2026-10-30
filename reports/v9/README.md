# reports/v9: the second laptop (docs/POLICY_V9.md)

| File | Written by | Content |
| :--- | :--- | :--- |
| `training_profile.jsonl` | `scripts/profile_training.py` | Time split of PPO training (rollout vs update) per device and thread count: the GPU assessment (§2) |
| `host_baseline.json` | `scripts/measure_host_baseline.py` | Idle whole-machine CPU minus Kubernetes CPU, and the host-load limit derived from it (§4), measured before the first run |
| `calibration_plan.json` (+ `.progress.json`) | `scripts/v9_plan.py calibration`, `scripts/run_plan.py` | The 8 HPA calibration runs in their pre-registered order (§3) |
| `host_load_calibration.csv` | `scripts/check_host_load.py --since 20261028-23` | Host validity (§4) of every calibration run |
| `calibration_plan.reruns.json` (+ `.progress.json`) | `scripts/rerun_plan.py` | The one rerun of the host-affected calibration run 1 (the `.stopped-1121` progress file is a rerun stopped before its load) |
| `calibration.{md,json}` | `scripts/analyze_v7_calibration.py --prefix v9cal-` | The calibration rule applied: HPA-tuned's CPU target on this laptop (**350%**) |
| `twin_check.{md,json}` | `scripts/analysis/validate_twin_v9.py` | The v9 twin (`config/twin/shopping_v9.json`) and v7's twin against this laptop's calibration runs (§5) |
| `gate.json` | `scripts/v9_gate.py` | v9 against v7 on the v9 twin's validation workloads: the RL arm (§5; passed, v9) |
| `arms.json`, `evaluation_plan.json` | `scripts/v9_plan.py evaluation` | The 4 evaluation arms and the 48-run block design (§6) |
| `training_v7.json` | `scripts/train_v7.py --report-dir reports/v9 --device cuda` | v9 training runs (GPU), selection on validation; the twin test sets are added once, after the live evaluation (§5) |
| `evaluation_plan.progress.json` | `scripts/run_plan.py` | Run ids of the 48 evaluation runs (run 20 is the restart after the 18:25 lid-close; the stopped attempt is in `reports/experiments_invalid/`) |
| `host_load_evaluation.csv` | `scripts/check_host_load.py --results reports/experiments reports/experiments_invalid --since 20261029-142` | Host validity (§4) of the 48 evaluation runs and the 5 reruns (7 host-affected, all FlexaScale or Auto) |
| `evaluation_plan.reruns.json` (+ `.progress.json`) | `scripts/rerun_plan.py` | The one rerun of each of the 5 host-affected evaluation runs (2 of them host-affected again, not rerun) |
| `evaluation.{md,json}` | `scripts/analyze_v7.py --study v9 --host-load reports/v9/host_load_evaluation.csv` | **The pre-registered live verdict** against HPA-tuned and HPA-default (§6): RL and Auto on par / inconclusive against both |
| `evaluation_sensitivity.{md,json}` | `scripts/analysis/v9_sensitivity.py` | Descriptive only, added after the verdict: the comparison without the pairs that contain a late rerun |
| `ablation.{md,json}` | `scripts/analysis/v9_ablation.py` | The twin test sets T1–T3 (run once, after the live evaluation, into `training_v7.json`) for every controller, and the graph ablation (seed 1, graph − no graph, paired by episode) |
| `v9_vs_v7.{md,json}` | `scripts/analysis/v9_vs_v7.py` | Descriptive, added after the evaluation: v9 against v7 on the held-out test sets of both laptops' twins, paired by episode (no difference) |

Raw run data stays in `reports/experiments/<run>/` (labels `v9cal-*`, `v9-bNN-*`); demo and smoke runs are in `reports/experiments_demo/` and are never used in a result. Host validity of every run: `reports/host_load_by_run.csv` (`scripts/check_host_load.py`).
