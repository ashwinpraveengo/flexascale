#!/usr/bin/env bash
# The clock-controlled replication of docs/POLICY_V7.md §3.7, resumable at every step:
#   1. the power profile `performance`, so the CPU clock does not follow host load (set here if needed);
#   2. the replication plan (12 blocks x 4 arms; scripts/v7_plan.py replication, written once);
#   3. host-load check (with each run's mean CPU clock), each invalid run moved aside and rerun once (§3.4),
#      then the verdict with the clock-balance condition (analyze_v7.py --study replication).
#   nohup ./scripts/v7_replicate.sh >> logs/v7_replication.out 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
PLAN=reports/v7/replication_plan.json
RERUNS=reports/v7/replication_plan.reruns.json
TRAIN_PATTERN='^[^ ]*python[^ ]* -u scripts/train_v7\.py'
profile() { busctl call org.freedesktop.UPower.PowerProfiles /org/freedesktop/UPower/PowerProfiles \
              org.freedesktop.DBus.Properties Get ss org.freedesktop.UPower.PowerProfiles ActiveProfile 2>/dev/null | awk '{print $3}' | tr -d '"'; }
plan_runs() { $PY -c "import json,sys,os; p=sys.argv[1]; q=p[:-5]+'.progress.json'; print(len(json.load(open(p))), len(json.load(open(q))) if os.path.exists(q) else 0)" "$1"; }
run() { systemd-inhibit --what=sleep:idle:handle-lid-switch --why="FlexaScale v7 replication" \
          $PY -u scripts/run_plan.py "$1" --suspend "$TRAIN_PATTERN"; }

if [ "$(profile)" != performance ]; then
  echo "$(date +%H:%M:%S) power profile '$(profile)' -> 'performance' (POLICY_V7 §3.7)"
  busctl call org.freedesktop.UPower.PowerProfiles /org/freedesktop/UPower/PowerProfiles org.freedesktop.DBus.Properties \
    Set ssv org.freedesktop.UPower.PowerProfiles ActiveProfile s performance >/dev/null 2>&1
  sleep 2
  [ "$(profile)" = performance ] || { echo "$(date +%H:%M:%S) cannot set the performance profile; not starting"; exit 1; }
fi
[ -f $PLAN ] || $PY scripts/v7_plan.py replication --arms reports/v7/arms.json || exit 1
while pgrep -f "^[^ ]*python[^ ]* -u scripts/run_plan\.py $PLAN" >/dev/null; do sleep 20; done
read total done_runs < <(plan_runs $PLAN)
if [ "$done_runs" -lt "$total" ]; then run $PLAN || exit 1; fi
if [ ! -f $RERUNS ]; then
  $PY scripts/check_host_load.py && $PY scripts/rerun_plan.py $PLAN || exit 1
fi
read total done_runs < <(plan_runs $RERUNS)
if [ "$total" -gt 0 ] && [ "$done_runs" -lt "$total" ]; then run $RERUNS || exit 1; fi
$PY scripts/check_host_load.py && $PY scripts/analyze_v7.py --study replication
echo "$(date +%H:%M:%S) replication finished: reports/v7/replication.md"
