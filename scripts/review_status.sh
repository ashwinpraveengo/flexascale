#!/usr/bin/env bash
# FlexaScale review status: cluster, pods, app, monitoring, ownership, model, dashboard, port-forwards, URLs.
# Read-only: changes nothing.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/review_common.sh"

echo "${C_B}FlexaScale review status${C_0}  $(date '+%Y-%m-%d %H:%M:%S')"

step "Minikube"
st="$(minikube status -p "$PROFILE" --format 'host={{.Host}} kubelet={{.Kubelet}} apiserver={{.APIServer}}' 2>/dev/null || echo 'profile not running')"
case "$st" in *apiserver=Running*) ok "profile $PROFILE: $st";; *) err "profile $PROFILE: $st"; echo "         Recovery: ./scripts/start_review.sh"; exit 1;; esac
echo "  kubectl context: $(kubectl config current-context 2>/dev/null)"

step "Pods"
for ns in "$APP_NS" "$MON_NS" flexascale-bookstore flexascale-system; do
  kubectl get ns "$ns" >/dev/null 2>&1 || continue
  total=$(kubectl -n "$ns" get pods --no-headers 2>/dev/null | grep -vc Completed)
  ready=$(kubectl -n "$ns" get pods --no-headers 2>/dev/null | grep -v Completed | awk '{split($2,a,"/"); if (a[1]==a[2] && $3=="Running") n++} END {print n+0}')
  if [ "$ready" = "$total" ]; then ok "$ns: $ready/$total pods ready"; else warn "$ns: $ready/$total pods ready"
    kubectl -n "$ns" get pods --no-headers | grep -v Completed | awk '{split($2,a,"/"); if (!(a[1]==a[2] && $3=="Running")) print "         " $1 " " $2 " " $3}'
  fi
done

step "Shopping application"
IP="$(minikube_ip)"
http_ok "http://${IP}/" 5 && ok "storefront http://${IP}/" || err "storefront http://${IP}/ unreachable"
http_ok "http://${IP}/api/products?limit=1" 8 && ok "API via ingress" || err "API via ingress unreachable"
kubectl -n "$APP_NS" get deploy postgres >/dev/null 2>&1 && \
  ok "PostgreSQL: $(kubectl -n "$APP_NS" get deploy postgres -o jsonpath='{.status.readyReplicas}/{.spec.replicas}') ready"

step "Monitoring"
http_ok "http://localhost:${PROM_PORT}/-/ready" 3 && ok "Prometheus http://localhost:${PROM_PORT}/" || warn "Prometheus port-forward not up (start_review.sh starts it)"
http_ok "http://localhost:${GRAFANA_PORT}/api/health" 3 && ok "Grafana http://localhost:${GRAFANA_PORT}/" || warn "Grafana port-forward not up"

step "Controller ownership and HPAs"
"${PROCCTL[@]}" ownership | sed 's/^/  /'
kubectl -n "$APP_NS" get hpa 2>/dev/null | sed 's/^/  /'

step "FlexaScale model, operator and dashboard"
"$PY" - <<'PYEOF'
import json, pathlib
from flexascale.config.app_policy import AppPolicy
p = AppPolicy.load("config/apps/shopping.yaml")
path = pathlib.Path(p.model_path)
card = path.parent.parent / "model_card.json"
if path.is_file():
    c = json.loads(card.read_text()) if card.is_file() else {}
    print(f"  [ OK ] model {path} ({c.get('total_timesteps','?')} timesteps, {c.get('num_services','?')}-service topology, reward {c.get('environment',{}).get('reward_weights')})")
else:
    print(f"  [FAIL] model {path} missing")
print(f"  policy mode (shopping): {p.mode}")
PYEOF
if [ -f "$RUNTIME/operator_status.json" ] && managed_running operator; then
  echo "  operator: $("$PY" -c 'import json;d=json.load(open(".runtime/operator_status.json"));print(d["effective_mode"],"mode, step",d["step"])')"
else
  echo "  operator: not running (started by the dashboard for FlexaScale or shadow runs)"
fi
http_ok "http://127.0.0.1:${LAB_PORT}/api/lab/health" 3 && ok "dashboard http://127.0.0.1:${LAB_PORT}/" || warn "dashboard not running (./scripts/start_review.sh)"

step "Managed processes"
"${PROCCTL[@]}" status | sed 's/^/  /'

step "URLs"
echo "  Dashboard : http://127.0.0.1:${LAB_PORT}/"
echo "  Shop      : http://${IP}/"
echo "  Prometheus: http://localhost:${PROM_PORT}/"
echo "  Grafana   : http://localhost:${GRAFANA_PORT}/"
