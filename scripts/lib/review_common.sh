# Shared settings for the bash entry points (start_review.sh, stop_review.sh, review_status.sh).
# The logic itself lives in src/flexascale/lab/launcher.py, which also runs on Windows (fsctl.cmd).
# shellcheck shell=bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/.venv/Scripts/python.exe"   # Git Bash on Windows
RUNTIME="$ROOT/.runtime"
PROFILE="${FLEXASCALE_MINIKUBE_PROFILE:-flexascale}"
APP_NS="flexascale-apps"
MON_NS="${FLEXASCALE_MONITORING_NS:-flexascale-monitoring}"
LAB_PORT="${FLEXASCALE_LAB_PORT:-8090}"
PROM_PORT="${FLEXASCALE_PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${FLEXASCALE_GRAFANA_PORT:-3000}"
PROCCTL=("$PY" -m flexascale.lab.procctl --runtime-dir "$RUNTIME" --config "$ROOT/config/lab.yaml")
launcher() { cd "$ROOT" && exec "$PY" -m flexascale.lab.launcher "$@"; }
