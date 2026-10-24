#!/usr/bin/env bash
# FlexaScale fast review startup.
#
#   ./scripts/start_review.sh            preflight + port-forwards + Live Lab dashboard
#   ./scripts/start_review.sh --demo     same, plus demo checks (model, ownership) and the demo script
#   ./scripts/start_review.sh --check    preflight only: start nothing, change nothing
#
# Works with the already installed cluster. It never rebuilds images, reinstalls
# charts, retrains models, downloads data or runs the test suite. It starts the
# existing Minikube profile only if it is stopped, and never creates a new one.
# Safe to run repeatedly: healthy processes it started earlier are reused.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/review_common.sh"

MODE="review"
for arg in "$@"; do
  case "$arg" in
    --demo) MODE="demo" ;;
    --check) MODE="check" ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
mkdir -p "$RUNTIME/logs"
START=$(date +%s)

echo "${C_B}FlexaScale review startup (${MODE})${C_0}  profile=${PROFILE}  repo=${ROOT}"

step "1/8 Tools"
for t in docker minikube kubectl curl ss; do
  have "$t" && ok "$t" || die "$t not found on PATH" "install it (see RUNNING.md section A/C)"
done
have helm && ok "helm" || warn "helm not found (only needed for installation, not for the review)"
[ -x "$PY" ] || die "Python virtualenv missing at .venv" "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e ."
"$PY" -c "import flexascale.lab.server" 2>/dev/null && "$PY" -c "import locust" 2>/dev/null && ok "Python environment (.venv) with flexascale + locust" \
  || die "flexascale package or locust not importable from .venv" ".venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e ."

step "2/8 Docker and Minikube"
docker info >/dev/null 2>&1 && ok "Docker daemon reachable" || die "Docker is not running" "start Docker (e.g. sudo systemctl start docker) and re-run"
if ! minikube profile list -o json 2>/dev/null | grep -q "\"Name\":\"${PROFILE}\""; then
  die "Minikube profile '${PROFILE}' does not exist" "full installation is separate: ./scripts/setup_cluster.sh (RUNNING.md section C-E)"
fi
host_state="$(minikube status -p "$PROFILE" --format '{{.Host}}/{{.APIServer}}' 2>/dev/null || true)"
if [ "$host_state" != "Running/Running" ]; then
  if [ "$MODE" = "check" ]; then
    die "Minikube profile '${PROFILE}' is not running (${host_state:-stopped})" "./scripts/start_review.sh (without --check) starts it"
  fi
  warn "Minikube profile '${PROFILE}' is ${host_state:-stopped}; starting the existing profile (2-4 min)..."
  minikube start -p "$PROFILE" >"$RUNTIME/logs/minikube-start.log" 2>&1 \
    || die "minikube start failed" "see .runtime/logs/minikube-start.log; try: minikube start -p ${PROFILE}"
fi
ok "Minikube profile '${PROFILE}' running"
ctx="$(kubectl config current-context 2>/dev/null || true)"
if [ "$ctx" != "$PROFILE" ]; then
  if [ "$MODE" = "check" ]; then
    warn "kubectl context is '${ctx}', not '${PROFILE}' (run without --check to switch)"
  else
    kubectl config use-context "$PROFILE" >/dev/null && warn "switched kubectl context from '${ctx}' to '${PROFILE}'"
  fi
fi
kubectl get --raw /readyz >/dev/null 2>&1 && ok "Kubernetes API ready" || die "Kubernetes API not reachable" "minikube status -p ${PROFILE}; minikube start -p ${PROFILE}"

step "3/8 Namespaces and workloads"
for ns in "$APP_NS" "$MON_NS"; do
  kubectl get ns "$ns" >/dev/null 2>&1 && ok "namespace $ns" || die "namespace $ns missing" "install the stack first (RUNNING.md sections D-F)"
done
wait_ready() { # ns kind/name timeout
  kubectl -n "$1" rollout status "$2" --timeout="$3" >/dev/null 2>&1
}
failed=0
for d in $(kubectl -n "$APP_NS" get deploy -o jsonpath='{.items[*].metadata.name}'); do
  if wait_ready "$APP_NS" "deploy/$d" 180s; then ok "$APP_NS/$d ready"; else err "$APP_NS/$d not ready after 180s"; failed=1; fi
done
for w in "deploy/${GRAFANA_SVC}" deploy/monitoring-kube-state-metrics "statefulset/prometheus-${PROM_SVC}"; do
  if wait_ready "$MON_NS" "$w" 180s; then ok "$MON_NS/${w#*/} ready"; else err "$MON_NS/${w#*/} not ready after 180s"; failed=1; fi
done
[ "$failed" = 0 ] || die "some pods are not ready" "kubectl get pods -A | grep -v Running; kubectl -n <ns> describe pod <pod>; kubectl -n <ns> rollout restart deploy/<name>"
if kubectl get ns flexascale-bookstore >/dev/null 2>&1; then
  for d in $(kubectl -n flexascale-bookstore get deploy -o jsonpath='{.items[*].metadata.name}'); do
    wait_ready flexascale-bookstore "deploy/$d" 120s && ok "flexascale-bookstore/$d ready" || warn "flexascale-bookstore/$d not ready (second app is optional)"
  done
fi

step "4/8 Shopping application"
IP="$(minikube_ip)"
[ -n "$IP" ] || die "cannot read the Minikube IP" "minikube ip -p ${PROFILE}"
SHOP_URL="http://${IP}/"
for i in $(seq 1 20); do http_ok "$SHOP_URL" 3 && break; sleep 3; done
http_ok "$SHOP_URL" 5 && ok "storefront $SHOP_URL" || die "storefront not reachable at $SHOP_URL" "kubectl -n ingress-nginx get pods; kubectl -n $APP_NS get ingress"
http_ok "${SHOP_URL}api/products?limit=1" 8 && ok "API gateway -> catalog via ingress" || die "API not reachable at ${SHOP_URL}api/products" "kubectl -n $APP_NS logs deploy/api-gateway --tail=50"

if [ "$MODE" = "check" ]; then
  step "5/8 Monitoring (check only)"
  kubectl -n "$MON_NS" get svc "$PROM_SVC" >/dev/null 2>&1 && ok "Prometheus service present" || err "Prometheus service missing"
  step "Model"
  [ -f models/flexascale_v4/best_model/best_model.zip ] || [ -f models/flexascale_v3/best_model/best_model.zip ] || [ -f models/flexascale_v2/best_model/best_model.zip ] && ok "trained model present" || err "trained model missing"
  echo; echo "${C_OK}Preflight passed${C_0} in $(( $(date +%s) - START ))s. Nothing was started or changed."
  exit 0
fi

step "5/8 Port-forwards (Prometheus, Grafana)"
start_managed pf-prometheus "$PROM_PORT" "http://localhost:${PROM_PORT}/-/ready" keep_port_forward.sh -- \
  $(port_forward_cmd "$MON_NS" "svc/${PROM_SVC}" "${PROM_PORT}:9090")
start_managed pf-grafana "$GRAFANA_PORT" "http://localhost:${GRAFANA_PORT}/api/health" keep_port_forward.sh -- \
  $(port_forward_cmd "$MON_NS" "svc/${GRAFANA_SVC}" "${GRAFANA_PORT}:80")
if kubectl get ns flexascale-bookstore >/dev/null 2>&1; then
  start_managed pf-bookstore "$BOOKSTORE_PORT" "http://localhost:${BOOKSTORE_PORT}/healthz" keep_port_forward.sh -- \
    $(port_forward_cmd flexascale-bookstore "svc/storefront" "${BOOKSTORE_PORT}:8080")
fi

step "6/8 Prometheus targets and metrics"
up="$(curl -fsS --get "http://localhost:${PROM_PORT}/api/v1/query" --data-urlencode "query=count(up{namespace=\"${APP_NS}\"} == 1)" 2>/dev/null \
      | "$PY" -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else 0)' 2>/dev/null || echo 0)"
[ "${up:-0}" -ge 7 ] && ok "$up shopping scrape targets up" || warn "only ${up:-0} shopping scrape targets up (expected >= 7); metrics may lag after a restart"
ksm="$(curl -fsS --get "http://localhost:${PROM_PORT}/api/v1/query" --data-urlencode "query=count(kube_deployment_spec_replicas{namespace=\"${APP_NS}\"})" 2>/dev/null \
      | "$PY" -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else 0)' 2>/dev/null || echo 0)"
[ "${ksm:-0}" -ge 1 ] && ok "kube-state-metrics series present" || warn "kube-state-metrics series missing"

step "7/8 FlexaScale prerequisites and controller ownership"
MODEL=""
for m in models/flexascale_v4/best_model/best_model.zip models/flexascale_v3/best_model/best_model.zip models/flexascale_v2/best_model/best_model.zip; do
  [ -f "$m" ] && { MODEL="$m"; break; }
done
policy_model="$("$PY" -c 'from flexascale.config.app_policy import AppPolicy; print(AppPolicy.load("config/apps/shopping.yaml").model_path)')"
[ -f "$policy_model" ] && ok "trained PPO+GNN model: $policy_model" || err "policy model missing: $policy_model (FlexaScale live runs will be refused)"
"$PY" scripts/run_operator.py --policy config/apps/shopping.yaml --validate-only >/dev/null 2>&1 && ok "shopping policy valid (mode: observe by default)" || err "config/apps/shopping.yaml invalid"
if "${PROCCTL[@]}" safe-state >"$RUNTIME/logs/ownership.log" 2>&1; then
  ok "native HPA owns all managed Deployments; no FlexaScale lease held"
else
  err "ownership not safe; see .runtime/logs/ownership.log"
  sed 's/^/         /' "$RUNTIME/logs/ownership.log"
  die "controller-ownership problem" "./scripts/stop_review.sh  (restores HPAs; add --force-release-lease if a dead controller still holds the lease)"
fi
incluster="$(kubectl -n flexascale-system get deploy flexascale-operator -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)"
if [ -n "$incluster" ] && [ "$incluster" != "0" ]; then
  warn "an in-cluster FlexaScale operator is running in flexascale-system; make sure its policy mode is 'observe'"
fi

step "8/8 Live Autoscaling Lab dashboard"
start_managed lab "$LAB_PORT" "http://127.0.0.1:${LAB_PORT}/api/lab/health" run_lab.py -- \
  "$PY" "$ROOT/scripts/run_lab.py" --host 127.0.0.1 --port "$LAB_PORT" --config "$ROOT/config/lab.yaml" --runtime-dir "$RUNTIME"
http_ok "http://127.0.0.1:${LAB_PORT}/" 5 && ok "dashboard UI served" || warn "dashboard API is up but the UI bundle is missing (cd dashboard && npm ci && npm run build)"

cat > "$RUNTIME/urls.env" <<URLS
DASHBOARD_URL=http://127.0.0.1:${LAB_PORT}/
SHOP_URL=${SHOP_URL}
PROMETHEUS_URL=http://localhost:${PROM_PORT}/
GRAFANA_URL=http://localhost:${GRAFANA_PORT}/
URLS

echo
echo "${C_B}${C_OK}READY${C_0}${C_B} in $(( $(date +%s) - START ))s${C_0}"
echo "  Presentation dashboard : ${C_B}http://127.0.0.1:${LAB_PORT}/${C_0}"
echo "  Shopping application   : ${C_B}${SHOP_URL}${C_0}   (demo login: demo@flexascale.io / CustomerPass123!)"
echo "  Prometheus             : http://localhost:${PROM_PORT}/"
echo "  Grafana                : http://localhost:${GRAFANA_PORT}/   (password: kubectl -n ${MON_NS} get secret ${GRAFANA_SVC} -o jsonpath='{.data.admin-password}' | base64 -d)"
kubectl get ns flexascale-bookstore >/dev/null 2>&1 && echo "  Bookstore (2nd app)    : http://localhost:${BOOKSTORE_PORT}/"
echo "  Status                 : ./scripts/review_status.sh"
echo "  Stop safely            : ./scripts/stop_review.sh"

if [ "$MODE" = "demo" ]; then
  cat <<DEMO

${C_B}Demo sequence${C_0} (details: docs/FINAL_DEMO_RUNBOOK.md)
  1. Open the dashboard and the shop side by side.
  2. Native HPA, scenario "Flash-sale spike", 40 users, 300 s, shadow mode on -> Start.
     Browse the shop and place an order while the load runs.
  3. When it completes, select FlexaScale, same scenario and settings -> Start.
     Point out: lease acquired, HPA frozen per service, proposal vs scale request vs ready.
  4. "Results & comparison": pick the HPA run as baseline and the FlexaScale run as candidate.
  5. ./scripts/stop_review.sh when finished.
DEMO
fi
