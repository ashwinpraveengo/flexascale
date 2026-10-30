#!/usr/bin/env bash
# In-cluster Helm lifecycle of the operator chart on the second application (the bookstore):
# install (observe) -> upgrade (live, v9 model) -> rollback (observe) -> uninstall, with the hand-back
# checked after every step (HPA bounds and markers, Lease, RBAC). Same checks as the 2026-10-26 test
# (reports/final_readiness_report.md §9, logs/helm_verify.out), now scripted. Needs the operator image
# inside Minikube (eval $(minikube -p flexascale docker-env); docker build -f deploy/flexascale/Dockerfile -t flexascale:0.6.0 .).
#
#   bash scripts/helm_lifecycle_test.sh 2>&1 | tee logs/helm_lifecycle_0.6.0.out
set -u
export MSYS_NO_PATHCONV=1  # Git Bash on Windows would rewrite /app/... and /var/... arguments for helm.exe and kubectl.exe
cd "$(dirname "$0")/.."
REL=fs-bookstore NS=flexascale-system APP=flexascale-bookstore
CHART=helm/flexascale VALUES=helm/flexascale/values-bookstore.yaml
V9=/app/models/flexascale_v9/best_model/best_model.zip
SA=system:serviceaccount:$NS:$REL-operator
PASS=0 FAIL=0

step() { echo; echo "=== $(date +%H:%M:%S) $*"; }
check() {  # check <description> <command...>: passes when the command succeeds
  local d=$1; shift
  if "$@"; then PASS=$((PASS + 1)); echo "  PASS $d"; else FAIL=$((FAIL + 1)); echo "  FAIL $d"; fi
}
hpas() { kubectl -n $APP get hpa -o custom-columns='NAME:.metadata.name,MIN:.spec.minReplicas,MAX:.spec.maxReplicas,FROZEN_BY:.metadata.annotations.flexascale\.io/frozen-by'; }
frozen() { kubectl -n $APP get hpa,deploy -o jsonpath='{range .items[*]}{.metadata.annotations.flexascale\.io/frozen-by}{.metadata.annotations.flexascale\.io/original-replicas}{"\n"}{end}' | grep -c .; }
bounds_original() { [ "$(kubectl -n $APP get hpa -o jsonpath='{range .items[*]}{.spec.minReplicas}-{.spec.maxReplicas} {end}')" = "1-5 1-5 1-5 " ]; }
holder() { kubectl -n $APP get lease flexascale-bookstore -o jsonpath='{.spec.holderIdentity}' 2>/dev/null; }
released() { [ -z "$(holder)" ]; }
held() { for _ in $(seq 1 30); do [ -n "$(holder)" ] && return 0; sleep 2; done; return 1; }
no_markers() { [ "$(frozen)" = 0 ]; }
can() { [ "$(kubectl auth can-i "$@" -n $APP --as=$SA 2>/dev/null)" = yes ]; }
cannot() { ! can "$@"; }
mode_is() { kubectl -n $NS get configmap $REL-policy -o jsonpath='{.data}' | grep -q "mode: $1"; }
operator_ready() { kubectl -n $NS rollout status deploy/$REL-operator --timeout=300s >/dev/null; }
show() { hpas; echo "  lease holder: '$(holder)'  markers: $(frozen)"; }
# The operator pod of THIS release (another release in the namespace must never be read by mistake).
opod() { kubectl -n $NS get pod -l app.kubernetes.io/instance=$REL,app.kubernetes.io/component=operator --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}'; }

step "0. baseline"
show
check "no release $REL yet" bash -c "! helm status $REL -n $NS >/dev/null 2>&1"
check "HPAs at their original bounds (1-5)" bounds_original
check "no FlexaScale markers on HPAs or Deployments" no_markers
check "Lease not held" released
helm lint $CHART -f $VALUES | tail -1

step "1. helm install (observe, revision 1)"
helm upgrade --install $REL $CHART -n $NS --create-namespace -f $VALUES --wait --timeout 10m | head -8
check "operator ready" operator_ready
check "policy mode observe" mode_is observe
sleep 30
kubectl -n $NS logs "$(opod)" --tail=15
kubectl -n $NS exec "$(opod)" -- tail -n 2 /var/log/flexascale/decisions.jsonl | cut -c1-400
show
check "HPAs unchanged in observe" bounds_original
check "no markers in observe" no_markers
check "Lease not taken in observe" released
check "RBAC observe: list deployments" can list deployments
check "RBAC observe: no patch on HPAs" cannot patch horizontalpodautoscalers
check "RBAC observe: no scale update" cannot update deployments --subresource=scale

step "2. helm upgrade (live, v9 model, revision 2)"
helm upgrade $REL $CHART -n $NS --reuse-values --set policy.mode=live --set policy.model_path=$V9 --wait --timeout 10m | head -8
check "operator ready" operator_ready
check "policy mode live" mode_is live
check "Lease taken within 60 s" held
sleep 20
kubectl -n $NS logs "$(opod)" --tail=15
kubectl -n $NS exec "$(opod)" -- tail -n 2 /var/log/flexascale/decisions.jsonl | cut -c1-400
check "v9 model loaded without error (operator_start event)" bash -c "kubectl -n $NS exec "$(opod)" -- grep -m1 operator_start /var/log/flexascale/decisions.jsonl | grep flexascale_v9 | grep -q '\"model_error\": null'"
show
check "3 HPAs and 2 HPA-less Deployments marked (5 markers)" bash -c "[ \"\$(kubectl -n $APP get hpa,deploy -o jsonpath='{range .items[*]}{.metadata.annotations.flexascale\.io/frozen-by}{.metadata.annotations.flexascale\.io/original-replicas}{\"\n\"}{end}' | grep -c .)\" -ge 5 ]"
check "RBAC live: patch HPAs" can patch horizontalpodautoscalers
check "RBAC live: update deployments/scale" can update deployments --subresource=scale
check "RBAC live: no delete deployments" cannot delete deployments
check "RBAC live: no secrets" cannot get secrets

step "3. helm rollback to revision 1 (observe)"
helm rollback $REL 1 -n $NS --wait --timeout 10m
check "operator ready" operator_ready
check "policy mode observe again" mode_is observe
sleep 10
show
check "HPAs restored to 1-5" bounds_original
check "every marker cleared" no_markers
check "Lease released" released
check "RBAC observe again: no patch on HPAs" cannot patch horizontalpodautoscalers

step "4. helm uninstall"
helm uninstall $REL -n $NS --wait --timeout 10m
sleep 5
show
check "release gone" bash -c "! helm status $REL -n $NS >/dev/null 2>&1"
check "no operator left" bash -c "[ -z \"\$(kubectl -n $NS get deploy -l app.kubernetes.io/instance=$REL -o name)\" ]"
check "no Role or RoleBinding left in $APP" bash -c "[ -z \"\$(kubectl -n $APP get role,rolebinding -l app.kubernetes.io/instance=$REL -o name)\" ]"
check "HPAs at 1-5" bounds_original
check "no markers" no_markers
check "Lease released" released
kubectl -n $APP get deploy

step "result: $PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
