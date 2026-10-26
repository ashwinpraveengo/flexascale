#!/usr/bin/env bash
# Resume the v7 pipeline (docs/POLICY_V7.md) after a reboot, a dead battery or an interrupted session:
#   1. bring the review environment back (Minikube, port-forwards, lab) with the normal start script;
#   2. resume the HPA calibration plan (scripts/run_plan.py keeps per-run progress) unless it is complete;
#   3. resume training: runs already in reports/v7/training_v7.json are skipped.
# Safe to run twice: it starts nothing that is already running.
#   ./scripts/v7_resume.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
TRAIN_PATTERN='^[^ ]*python[^ ]* -u scripts/train_v7\.py'
mkdir -p logs
./scripts/start_review.sh || { echo "start_review.sh failed; fix the environment first"; exit 1; }
if ! pgrep -f '^[^ ]*python[^ ]* -u scripts/run_plan\.py reports/v7/calibration_plan\.json' >/dev/null; then
  done_runs=$($PY -c "import json,os; p='reports/v7/calibration_plan.progress.json'; print(len(json.load(open(p))) if os.path.exists(p) else 0)")
  if [ "$done_runs" -lt 8 ]; then
    nohup systemd-inhibit --what=sleep:idle:handle-lid-switch --why="FlexaScale v7 HPA calibration" \
      $PY -u scripts/run_plan.py reports/v7/calibration_plan.json --suspend "$TRAIN_PATTERN" >> logs/v7_calibration.out 2>&1 &
    echo "calibration resumed ($done_runs/8 runs done): logs/v7_calibration.out"
  else
    echo "calibration complete: python scripts/check_host_load.py && python scripts/analyze_v7_calibration.py"
  fi
fi
if ! pgrep -f "$TRAIN_PATTERN" >/dev/null; then
  nohup nice -n 5 $PY -u scripts/train_v7.py >> logs/train_v7.out 2>&1 &
  echo "training resumed (finished runs are skipped): logs/train_v7.out"
fi
