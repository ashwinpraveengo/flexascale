#!/usr/bin/env bash
# The whole HPA-tuned calibration of docs/POLICY_V7.md §2.1, resumable at every step:
#   1. the 8-run plan (scripts/run_plan.py keeps per-run progress; waits for an instance already running);
#   2. host-load check, then each invalid run moved aside and rerun once (§3.4, scripts/rerun_plan.py);
#   3. host-load check of the reruns and the calibration rule (scripts/analyze_v7_calibration.py).
# Training processes are frozen during every load window.
#   nohup ./scripts/v7_calibrate.sh >> logs/v7_calibration.out 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
PLAN=reports/v7/calibration_plan.json
RERUNS=reports/v7/calibration_plan.reruns.json
TRAIN_PATTERN='^[^ ]*python[^ ]* -u scripts/train_v7\.py'
plan_runs() { $PY -c "import json,sys,os; p=sys.argv[1]; q=p[:-5]+'.progress.json'; print(len(json.load(open(p))), len(json.load(open(q))) if os.path.exists(q) else 0)" "$1"; }
run() { systemd-inhibit --what=sleep:idle:handle-lid-switch --why="FlexaScale v7 HPA calibration" \
          $PY -u scripts/run_plan.py "$1" --suspend "$TRAIN_PATTERN"; }

while pgrep -f "^[^ ]*python[^ ]* -u scripts/run_plan\.py $PLAN" >/dev/null; do sleep 20; done
read total done_runs < <(plan_runs $PLAN)
if [ "$done_runs" -lt "$total" ]; then run $PLAN || exit 1; fi
if [ ! -f $RERUNS ]; then
  $PY scripts/check_host_load.py && $PY scripts/rerun_plan.py $PLAN || exit 1
fi
read total done_runs < <(plan_runs $RERUNS)
if [ "$total" -gt 0 ] && [ "$done_runs" -lt "$total" ]; then run $RERUNS || exit 1; fi
$PY scripts/check_host_load.py && $PY scripts/analyze_v7_calibration.py
echo "$(date +%H:%M:%S) calibration finished: reports/v7/calibration.md"
