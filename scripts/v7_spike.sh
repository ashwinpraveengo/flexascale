#!/usr/bin/env bash
# The confirmatory flash-sale study of docs/POLICY_V7.md §3.6, after the §3 batch; resumable at every step:
#   1. waits for scripts/v7_evaluate.sh (the 12-block batch and its reruns) to finish;
#   2. the spike plan (10 flash_sale blocks x 3 arms; scripts/v7_plan.py spike, written once);
#   3. host-load check, each invalid run moved aside and rerun once (§3.4), then the verdict (analyze_v7.py --study spike).
#   nohup ./scripts/v7_spike.sh >> logs/v7_spike.out 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
PLAN=reports/v7/spike_plan.json
RERUNS=reports/v7/spike_plan.reruns.json
TRAIN_PATTERN='^[^ ]*python[^ ]* -u scripts/train_v7\.py'
plan_runs() { $PY -c "import json,sys,os; p=sys.argv[1]; q=p[:-5]+'.progress.json'; print(len(json.load(open(p))), len(json.load(open(q))) if os.path.exists(q) else 0)" "$1"; }
run() { systemd-inhibit --what=sleep:idle:handle-lid-switch --why="FlexaScale v7 flash-sale study" \
          $PY -u scripts/run_plan.py "$1" --suspend "$TRAIN_PATTERN"; }

while pgrep -f 'scripts/v7_evaluate\.sh' >/dev/null || [ ! -f reports/v7/evaluation.json ]; do sleep 30; done
[ -f $PLAN ] || $PY scripts/v7_plan.py spike --arms reports/v7/arms.json || exit 1
while pgrep -f "^[^ ]*python[^ ]* -u scripts/run_plan\.py $PLAN" >/dev/null; do sleep 20; done
read total done_runs < <(plan_runs $PLAN)
if [ "$done_runs" -lt "$total" ]; then run $PLAN || exit 1; fi
if [ ! -f $RERUNS ]; then
  $PY scripts/check_host_load.py && $PY scripts/rerun_plan.py $PLAN || exit 1
fi
read total done_runs < <(plan_runs $RERUNS)
if [ "$total" -gt 0 ] && [ "$done_runs" -lt "$total" ]; then run $RERUNS || exit 1; fi
$PY scripts/check_host_load.py && $PY scripts/analyze_v7.py --study spike
echo "$(date +%H:%M:%S) flash-sale study finished: reports/v7/spike.md"
