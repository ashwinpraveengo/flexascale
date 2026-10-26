#!/usr/bin/env bash
# Repeated live benchmark: REPEATS x (six scenarios x {native HPA, FlexaScale}), alternating per
# scenario, through the dashboard's own API. Keeps the laptop awake for the whole batch.
#
#   ./scripts/run_live_batch.sh [repeats] [log]      (default 3, logs/live_batch.out; ~12-17 min per run)
set -uo pipefail
cd "$(dirname "$0")/.."
REPEATS="${1:-3}"
LOG="${2:-logs/live_batch.out}"
SCENARIOS="${FLEXASCALE_SCENARIOS:-steady_browsing,checkout_heavy,payment_degradation,flash_sale,gradual_ramp,traffic_drop}"
mkdir -p "$(dirname "$LOG")"
exec systemd-inhibit --what=sleep:idle:handle-lid-switch --why="FlexaScale live benchmark" bash -c '
  for r in $(seq 1 '"$REPEATS"'); do
    echo "=== repeat $r ($(date +%H:%M))"
    .venv/bin/python -u scripts/run_lab_experiments.py --scenarios '"$SCENARIOS"' --controllers ${FLEXASCALE_CONTROLLERS:-hpa,flexascale} --users 25 --spawn-rate 5 --duration 300
  done' >> "$LOG" 2>&1
