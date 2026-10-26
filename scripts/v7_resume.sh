#!/usr/bin/env bash
# Resume the v7 pipeline (docs/POLICY_V7.md) after a reboot, a dead battery or an interrupted session:
#   1. bring the review environment back (Minikube, port-forwards, lab) with the normal start script;
#   2. resume the HPA calibration (scripts/v7_calibrate.sh: plan, reruns of invalid runs, analysis) unless it is complete;
#   3. resume the live evaluation once promoted (scripts/v7_evaluate.sh), then the flash-sale study (scripts/v7_spike.sh);
#   4. resume training until a model is selected: runs already in reports/v7/training_v7.json are skipped.
# Safe to run twice: it starts nothing that is already running.
#   ./scripts/v7_resume.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
TRAIN_PATTERN='^[^ ]*python[^ ]* -u scripts/train_v7\.py'
mkdir -p logs
./scripts/start_review.sh || { echo "start_review.sh failed; fix the environment first"; exit 1; }
if ! pgrep -f 'scripts/v7_calibrate\.sh' >/dev/null; then
  if [ -f reports/v7/calibration.json ]; then
    echo "calibration complete: reports/v7/calibration.md"
  else
    nohup ./scripts/v7_calibrate.sh >> logs/v7_calibration.out 2>&1 &
    echo "calibration resumed (plan, one rerun of each invalid run, analysis): logs/v7_calibration.out"
  fi
fi
if [ -f reports/v7/arms.json ] && [ ! -f reports/v7/evaluation.json ] && ! pgrep -f 'scripts/v7_evaluate\.sh' >/dev/null; then
  nohup ./scripts/v7_evaluate.sh >> logs/v7_evaluation.out 2>&1 &
  echo "evaluation resumed (plan, one rerun of each invalid run, verdict): logs/v7_evaluation.out"
fi
if [ -f reports/v7/arms.json ] && [ ! -f reports/v7/spike.json ] && ! pgrep -f 'scripts/v7_spike\.sh' >/dev/null; then
  nohup ./scripts/v7_spike.sh >> logs/v7_spike.out 2>&1 &   # waits for the evaluation, then the flash-sale study (§3.6)
  echo "flash-sale study queued after the evaluation: logs/v7_spike.out"
fi
if [ ! -f reports/v7/training_v7.json ] || ! grep -q '"selected"' reports/v7/training_v7.json; then
 if ! pgrep -f "$TRAIN_PATTERN" >/dev/null; then
  nohup nice -n 5 $PY -u scripts/train_v7.py >> logs/train_v7.out 2>&1 &
  echo "training resumed (finished runs are skipped): logs/train_v7.out"
 fi
fi
