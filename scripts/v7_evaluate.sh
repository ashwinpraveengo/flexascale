#!/usr/bin/env bash
# The pre-registered v7 live evaluation of docs/POLICY_V7.md §3, resumable at every step:
#   1. the evaluation plan (12 blocks x 5 arms; scripts/v7_plan.py from reports/v7/arms.json, written once);
#   2. host-load check, then each invalid run moved aside and rerun once inside its block (§3.4, scripts/rerun_plan.py);
#   3. host-load check of the reruns and the verdict table (scripts/analyze_v7.py, §3.5).
# Training processes are frozen during every load window. Needs scripts/promote_v7.py and a lab restart first.
#   nohup ./scripts/v7_evaluate.sh >> logs/v7_evaluation.out 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
PLAN=reports/v7/evaluation_plan.json
RERUNS=reports/v7/evaluation_plan.reruns.json
TRAIN_PATTERN='^[^ ]*python[^ ]* -u scripts/train_v7\.py'
plan_runs() { $PY -c "import json,sys,os; p=sys.argv[1]; q=p[:-5]+'.progress.json'; print(len(json.load(open(p))), len(json.load(open(q))) if os.path.exists(q) else 0)" "$1"; }
run() { systemd-inhibit --what=sleep:idle:handle-lid-switch --why="FlexaScale v7 evaluation" \
          $PY -u scripts/run_plan.py "$1" --suspend "$TRAIN_PATTERN"; }

[ -f reports/v7/arms.json ] || { echo "reports/v7/arms.json missing: run scripts/promote_v7.py first"; exit 1; }
[ -f $PLAN ] || $PY scripts/v7_plan.py evaluation --arms reports/v7/arms.json || exit 1
while pgrep -f "^[^ ]*python[^ ]* -u scripts/run_plan\.py $PLAN" >/dev/null; do sleep 20; done
read total done_runs < <(plan_runs $PLAN)
if [ "$done_runs" -lt "$total" ]; then run $PLAN || exit 1; fi
if [ ! -f $RERUNS ]; then
  $PY scripts/check_host_load.py && $PY scripts/rerun_plan.py $PLAN || exit 1
fi
read total done_runs < <(plan_runs $RERUNS)
if [ "$total" -gt 0 ] && [ "$done_runs" -lt "$total" ]; then run $RERUNS || exit 1; fi
$PY scripts/check_host_load.py && $PY scripts/analyze_v7.py
echo "$(date +%H:%M:%S) evaluation finished: reports/v7/evaluation.md"
