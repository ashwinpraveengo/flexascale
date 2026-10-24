#!/usr/bin/env bash
# FlexaScale safe review shutdown.
#
#   ./scripts/stop_review.sh                       stop managed processes, restore HPA ownership, verify
#   ./scripts/stop_review.sh --force-release-lease also clear a controller lease left by a dead controller
#
# Stops ONLY processes recorded by the review scripts (.runtime/pids), never by
# port number. Does not stop Minikube, delete deployments, uninstall charts or
# touch volumes/database data. Idempotent: safe to run any number of times.
# Full teardown is separate: ./scripts/teardown_cluster.sh (asks for confirmation).
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/review_common.sh"

FORCE=""
for arg in "$@"; do
  case "$arg" in
    --force-release-lease) FORCE="--force-release-lease" ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
mkdir -p "$RUNTIME/logs"
echo "${C_B}FlexaScale review shutdown${C_0}"

step "1/4 Active experiment"
if managed_running lab && http_ok "http://127.0.0.1:${LAB_PORT}/api/lab/health" 3; then
  curl -fsS -m 5 -X POST "http://127.0.0.1:${LAB_PORT}/api/lab/experiments/stop" >/dev/null 2>&1 \
    && ok "stop requested for the running experiment" || ok "no experiment running"
  for i in $(seq 1 60); do
    state="$(curl -fsS -m 3 "http://127.0.0.1:${LAB_PORT}/api/lab/experiments/active" 2>/dev/null \
      | "$PY" -c 'import json,sys; a=json.load(sys.stdin).get("active"); print(a["state"] if a else "none")' 2>/dev/null || echo unknown)"
    case "$state" in none|completed|stopped|failed|interrupted|unknown) break ;; esac
    sleep 2
  done
  ok "experiment state: ${state:-none}"
else
  ok "dashboard not running (nothing to stop)"
fi

step "2/4 Managed processes (Locust, operator, dashboard, port-forwards)"
"${PROCCTL[@]}" stop-all | sed 's/^/  /'

step "3/4 Restore native HPA ownership"
# safe-state needs the Kubernetes API, not Prometheus.
if kubectl get --raw /readyz >/dev/null 2>&1; then
  if "${PROCCTL[@]}" safe-state $FORCE | sed 's/^/  /'; then
    ok "native HPA owns every managed Deployment; FlexaScale holds no lease"
    rc=0
  else
    err "ownership not fully restored (see above)"
    echo "         Recovery: a live lease means another controller is running (e.g. the in-cluster operator):"
    echo "           kubectl -n flexascale-system scale deploy/flexascale-operator --replicas=0"
    echo "         or, if that controller is dead: ./scripts/stop_review.sh --force-release-lease"
    rc=1
  fi
else
  warn "Kubernetes API not reachable; HPA state not verified (Minikube stopped?)"
  rc=1
fi

step "4/4 Summary"
"${PROCCTL[@]}" status | sed 's/^/  /'
ok "Minikube, deployments, Helm releases, volumes and database data were left untouched"
exit $rc
