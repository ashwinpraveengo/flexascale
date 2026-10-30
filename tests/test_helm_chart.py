"""Helm charts: least-privilege operator RBAC (write verbs only in live mode) and the shop's HPAs matching its chart."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def render(chart, namespace, *sets):
    args = ["helm", "template", "t", str(ROOT / chart), "-n", namespace]
    for s in sets:
        args += ["--set", s]
    out = subprocess.run(args, capture_output=True, text=True, timeout=60, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def operator_role(docs):
    return next(d for d in docs if d["kind"] == "Role" and d["metadata"]["name"].endswith("-operator"))


def verbs(docs):
    out = {}
    for rule in operator_role(docs)["rules"]:
        for group in rule["apiGroups"]:
            for res in rule["resources"]:
                out.setdefault((group, res), set()).update(rule["verbs"])
    return out


def test_operator_default_is_observe_read_only_and_namespaced():
    docs = render("helm/flexascale", "flexascale-system")
    kinds = {d["kind"] for d in docs}
    assert not kinds & {"ClusterRole", "ClusterRoleBinding"}
    assert operator_role(docs)["metadata"]["namespace"] == "flexascale-apps"
    for key, v in verbs(docs).items():
        assert v <= {"get", "list", "watch"}, key
    policy = next(d for d in docs if d["kind"] == "ConfigMap")["data"]
    assert any(yaml.safe_load(text).get("mode") == "observe" for text in policy.values())


def test_live_mode_adds_only_the_write_verbs_it_needs():
    v = verbs(render("helm/flexascale", "flexascale-system", "policy.mode=live"))
    assert "patch" in v[("autoscaling", "horizontalpodautoscalers")]
    assert {"update", "patch"} <= v[("apps", "deployments/scale")]
    assert {"create", "update"} <= v[("coordination.k8s.io", "leases")]
    assert "delete" not in set().union(*v.values())
    assert ("", "secrets") not in v and ("", "pods") not in v


def test_role_follows_the_target_application_namespace():
    docs = render("helm/flexascale", "ops", "policy.namespace=shop-prod", "policy.name=shop")
    assert operator_role(docs)["metadata"]["namespace"] == "shop-prod"
    binding = next(d for d in docs if d["kind"] == "RoleBinding")
    assert binding["metadata"]["namespace"] == "shop-prod"
    assert binding["subjects"][0]["namespace"] == "ops"


def test_every_shop_hpa_targets_a_chart_deployment_with_cpu_requests():
    deployments = {d["metadata"]["name"]: d for d in render("charts/shopping-app", "flexascale-apps") if d["kind"] == "Deployment"}
    hpas = [d for d in yaml.safe_load_all((ROOT / "deploy" / "kubernetes" / "hpa.yaml").read_text())
            if d and d["kind"] == "HorizontalPodAutoscaler"]
    assert len(hpas) >= 1
    for h in hpas:
        target = h["spec"]["scaleTargetRef"]["name"]
        assert target in deployments, target
        for c in deployments[target]["spec"]["template"]["spec"]["containers"]:
            assert c.get("resources", {}).get("requests", {}).get("cpu"), (target, c["name"])


def test_handback_hook_runs_before_upgrade_rollback_and_uninstall():
    # Found in-cluster: Helm changes the Role while it replaces the pod, so a live operator lost its write
    # permissions before it could restore frozen HPAs. The hook scales the operator to 0 first.
    docs = render("helm/flexascale", "ops", "policy.mode=live")
    hooks = [d for d in docs if (d["metadata"].get("annotations") or {}).get("helm.sh/hook")]
    assert {d["kind"] for d in hooks} == {"ServiceAccount", "Role", "RoleBinding", "Job"}
    for d in hooks:
        assert set(d["metadata"]["annotations"]["helm.sh/hook"].split(",")) == {"pre-upgrade", "pre-rollback", "pre-delete"}
        assert d["metadata"]["namespace"] == "ops"
    weights = {d["kind"]: int(d["metadata"]["annotations"]["helm.sh/hook-weight"]) for d in hooks}
    assert weights["Role"] < weights["Job"] and weights["RoleBinding"] < weights["Job"]
    job = next(d for d in hooks if d["kind"] == "Job")
    script = job["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert "scale deployment" in script and "--replicas=0" in script and "wait --for=delete" in script


def test_handback_hook_only_touches_the_operator_deployment():
    docs = render("helm/flexascale", "ops")
    role = next(d for d in docs if d["kind"] == "Role" and d["metadata"]["name"].endswith("-handback"))
    for rule in role["rules"]:
        if rule["apiGroups"] == ["apps"]:
            assert rule["resourceNames"] == ["t-operator"]
        assert "delete" not in rule["verbs"]
    assert not any(d["kind"] == "Job" for d in render("helm/flexascale", "ops", "operator.handbackHook=false"))


def test_null_latency_slo_reaches_the_operator_as_null():
    """Helm drops keys set to null; the template must keep 'no SLO' instead of the operator's 100 ms default."""
    for args in (["policy.slo_latency_ms=null"], []):
        docs = render("helm/flexascale", "ops", *args)
        policy = yaml.safe_load(next(d for d in docs if d["kind"] == "ConfigMap")["data"]["policy.yaml"])
        assert ("slo_latency_ms" in policy) and (policy["slo_latency_ms"] is None) == bool(args)
    v7 = ROOT / "helm" / "flexascale" / "values-v7.yaml"
    if v7.exists():
        out = subprocess.run(["helm", "template", "t", str(ROOT / "helm/flexascale"), "-n", "ops", "-f", str(v7)],
                             capture_output=True, text=True, timeout=60, check=True).stdout
        cm = next(d for d in yaml.safe_load_all(out) if d and d["kind"] == "ConfigMap")
        policy = yaml.safe_load(cm["data"]["policy.yaml"])
        assert policy["slo_latency_ms"] is None and policy["max_step"] == 3


def test_operator_selector_is_release_specific_for_new_installs():
    """Two releases in one namespace must not select each other's pods (found in-cluster 2026-10-31)."""
    for release in ("a", "b"):
        args = ["helm", "template", release, str(ROOT / "helm/flexascale"), "-n", "flexascale-system"]
        out = subprocess.run(args, capture_output=True, text=True, timeout=60, check=True).stdout
        dep = next(d for d in yaml.safe_load_all(out) if d and d["kind"] == "Deployment" and d["metadata"]["name"].endswith("-operator"))
        sel = dep["spec"]["selector"]["matchLabels"]
        assert sel["app.kubernetes.io/instance"] == release
        assert sel.items() <= dep["spec"]["template"]["metadata"]["labels"].items()
