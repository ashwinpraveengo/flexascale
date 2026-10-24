"""
Tests for the application-agnostic product core: policy validation, workload
discovery, HPA ownership (freeze/restore of original bounds), the controller
Lease, telemetry attribution and resource-cost accounting.
"""

import dataclasses

import pytest

from flexascale.config.app_policy import AppPolicy, CostProfile
from flexascale.config.safety_config import SafetyConfig
from flexascale.discovery.workloads import WorkloadDiscovery
from flexascale.evaluation.cost import percent_change, scaling_stability, summarize_resources
from flexascale.k8s.kube import parse_cpu, parse_memory
from flexascale.metrics.workload_metrics import deployment_of, histogram_quantile
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lease import ControllerLease
from tests.fakes import FakeCluster, deployment, hpa


def policy(**kw):
    base = dict(name="demo", namespace="demo")
    base.update(kw)
    return AppPolicy(**base)


# ---------------------------------------------------------------- policy


@pytest.mark.parametrize("path", ["config/apps/shopping.yaml", "config/apps/bookstore.yaml"])
def test_example_policies_are_valid(path):
    p = AppPolicy.load(path)
    assert p.validate() == []
    assert p.mode == "observe", "examples must default to observation-only"


def test_policy_validation_catches_errors():
    p = policy(mode="yolo", min_replicas=0, max_replicas=0, confidence_threshold=0.5,
               deactivation_threshold=0.9, include=["a"], exclude=["a"],
               cost=CostProfile(cpu_per_vcpu_hour=0.1))
    errors = " | ".join(p.validate())
    for fragment in ("mode", "min_replicas", "deactivation_threshold", "both included and excluded", "cost"):
        assert fragment in errors


def test_policy_rejects_unknown_keys():
    with pytest.raises(ValueError, match="Unknown policy keys"):
        AppPolicy.from_dict({"name": "x", "namespace": "y", "scale_everything": True})


def test_per_service_bounds_override():
    p = AppPolicy.load("config/apps/bookstore.yaml")
    assert p.bounds_for("storefront") == (1, 4)
    assert p.bounds_for("search") == (1, 6)


def test_quantity_parsing():
    assert parse_cpu("250m") == pytest.approx(0.25)
    assert parse_cpu("2") == 2.0
    assert parse_memory("128Mi") == 128 * 1024 ** 2
    assert parse_memory("1G") == 1e9


# ---------------------------------------------------------------- discovery


def cluster():
    c = FakeCluster("demo")
    c.add(
        deployment("gateway"), deployment("orders"), deployment("orders-db", image="postgres:16"),
        deployment("cache", image="redis:7"), deployment("flexascale-operator"),
        deployment("batch", labels={"app": "batch", "flexascale.io/exclude": "true"}),
    )
    c.add(hpa("gw-autoscaler", "gateway", 2, 8), kind="hpa")
    return c


def test_discovery_eligibility_rules():
    d = WorkloadDiscovery(policy(), kube=cluster().kube())
    info = {w.name: w for w in d.list_all()}
    assert d.names() == ["gateway", "orders"]
    assert "datastore" in info["orders-db"].reason and "datastore" in info["cache"].reason
    assert "exclude pattern" in info["flexascale-operator"].reason
    assert "flexascale.io/exclude" in info["batch"].reason


def test_discovery_finds_hpa_by_scale_target_not_name():
    d = WorkloadDiscovery(policy(), kube=cluster().kube())
    gw = d.get("gateway")
    assert gw.hpa is not None and gw.hpa.name == "gw-autoscaler"
    assert (gw.hpa.min_replicas, gw.hpa.max_replicas) == (2, 8)
    assert d.get("orders").hpa is None
    assert gw.cpu_request_cores == pytest.approx(0.1)


def test_discovery_allowlist_and_denylist():
    d = WorkloadDiscovery(policy(include=["orders", "cache"]), kube=cluster().kube())
    assert d.names() == ["cache", "orders"]  # explicit include overrides datastore exclusion
    d = WorkloadDiscovery(policy(exclude=["orders"]), kube=cluster().kube())
    assert d.names() == ["gateway"]


def test_discovery_never_lists_other_namespaces():
    c = cluster()
    seen = []
    orig = c.run

    def spy(args, stdin, timeout):
        seen.append(list(args))
        return orig(args, stdin, timeout)

    c.run = spy
    WorkloadDiscovery(policy(label_selector="tier=web"), kube=c.kube()).list_all()
    gets = [a for a in seen if a[0] == "get"]
    assert gets and all("-n" in a and a[a.index("-n") + 1] == "demo" for a in gets)
    assert all("--all-namespaces" not in a and "-A" not in a for a in gets)
    assert ["-l", "tier=web"] == gets[0][-2:]


# ---------------------------------------------------------------- HPA ownership


def hpa_manager(c):
    return HPAManager(SafetyConfig(namespace="demo", dry_run=False), kube=c.kube(), holder="flexascale-demo")


def test_freeze_records_original_bounds_and_restore_uses_them():
    c = cluster()
    m = hpa_manager(c)
    assert m.freeze_hpa("gateway", 5)
    spec = c.hpas["gw-autoscaler"]["spec"]
    ann = c.hpas["gw-autoscaler"]["metadata"]["annotations"]
    assert (spec["minReplicas"], spec["maxReplicas"]) == (5, 5)
    assert ann["flexascale.io/original-min-replicas"] == "2"
    assert ann["flexascale.io/original-max-replicas"] == "8"
    # A second freeze must not overwrite the recorded originals with frozen values.
    assert m.freeze_hpa("gateway", 6)
    assert c.hpas["gw-autoscaler"]["metadata"]["annotations"]["flexascale.io/original-min-replicas"] == "2"
    assert m.ensure_hpa_active("gateway")
    spec = c.hpas["gw-autoscaler"]["spec"]
    assert (spec["minReplicas"], spec["maxReplicas"]) == (2, 8)
    assert "flexascale.io/original-min-replicas" not in c.hpas["gw-autoscaler"]["metadata"]["annotations"]


def test_unfrozen_hpa_is_not_touched_on_fallback():
    c = cluster()
    assert hpa_manager(c).ensure_hpa_active("gateway")
    assert c.mutations == []


def test_freeze_without_hpa_only_records_original_replicas():
    c = cluster()
    m = hpa_manager(c)
    start = c.deployments["orders"]["spec"]["replicas"]
    assert m.freeze_hpa("orders", 3) and m.last_note == "no_hpa"
    assert [a[:2] for a in c.mutations] == [["patch", "deployment"]]
    assert c.deployments["orders"]["metadata"]["annotations"]["flexascale.io/original-replicas"] == str(start)
    # Later freezes keep the first recorded count.
    m.scale_deployment("orders", 3)
    assert m.freeze_hpa("orders", 4)
    assert c.deployments["orders"]["metadata"]["annotations"]["flexascale.io/original-replicas"] == str(start)


def test_restore_unmanaged_replicas_scales_back_and_clears_marker():
    c = cluster()
    m = hpa_manager(c)
    start = c.deployments["orders"]["spec"]["replicas"]
    m.freeze_hpa("orders", start + 3)
    m.scale_deployment("orders", start + 3)
    assert m.restore_unmanaged_replicas() == ["orders"]
    assert c.deployments["orders"]["spec"]["replicas"] == start
    assert "flexascale.io/original-replicas" not in c.deployments["orders"]["metadata"].get("annotations", {})
    # Deployments FlexaScale never scaled, and HPA-backed ones, are untouched.
    c.mutations.clear()
    assert m.restore_unmanaged_replicas() == [] and c.mutations == []


def test_restore_all_frozen():
    c = cluster()
    c.add(hpa("o-hpa", "orders", 1, 4, {"flexascale.io/original-min-replicas": "1",
                                         "flexascale.io/original-max-replicas": "4"}), kind="hpa")
    c.hpas["o-hpa"]["spec"].update(minReplicas=3, maxReplicas=3)
    assert hpa_manager(c).restore_all_frozen() == ["o-hpa"]
    assert (c.hpas["o-hpa"]["spec"]["minReplicas"], c.hpas["o-hpa"]["spec"]["maxReplicas"]) == (1, 4)


# ---------------------------------------------------------------- lease


def test_lease_mutual_exclusion_and_takeover(monkeypatch):
    c = FakeCluster("demo")
    a = ControllerLease("demo", "app", identity="A", duration_seconds=10, kube=c.kube())
    b = ControllerLease("demo", "app", identity="B", duration_seconds=10, kube=c.kube())
    assert a.acquire()
    assert not b.acquire() and "held by 'A'" in b.last_error
    assert a.renew()
    # Simulate A dying: its renewTime ages past the lease duration.
    import flexascale.safety.lease as lease_mod
    real_time = lease_mod.time.time
    monkeypatch.setattr(lease_mod.time, "time", lambda: real_time() + 60)
    assert b.acquire()
    monkeypatch.undo()  # back to the real clock: B's fresh lease is live
    assert not a.renew()
    assert b.release() and b.status().holder is None


def test_lease_replace_conflict_is_refused():
    c = FakeCluster("demo")
    a = ControllerLease("demo", "app", identity="A", kube=c.kube())
    assert a.acquire()
    stale = dict(c.leases["flexascale-app"])
    stale["metadata"] = dict(stale["metadata"], resourceVersion="0")
    assert not c.kube().replace(stale).ok


# ---------------------------------------------------------------- telemetry helpers


def test_pod_to_deployment_attribution_is_exact():
    deps = ["order", "order-db"]
    assert deployment_of("order-5d9c79469-x8j2l", deps) == "order"
    assert deployment_of("order-db-6c8f9b7d4-abcde", deps) == "order-db"
    assert deployment_of("order-db-0", deps) is None  # statefulset pod, not a deployment
    assert deployment_of("payment-5d9c79469-x8j2l", deps) is None


def test_histogram_quantile():
    buckets = [(0.1, 50.0), (0.5, 90.0), (1.0, 100.0), (float("inf"), 100.0)]
    assert histogram_quantile(0.5, buckets) == pytest.approx(0.1)
    assert histogram_quantile(0.95, buckets) == pytest.approx(0.75)
    assert histogram_quantile(0.5, []) is None


# ---------------------------------------------------------------- cost accounting


def samples(replicas_by_t):
    return [{"t": t, "services": {"a": {"ready": r, "cpu_request_cores": 0.5, "memory_request_bytes": 2 * 1024 ** 3,
                                         "cpu_cores": 0.25 * r, "memory_bytes": 1024 ** 3 * r}}}
            for t, r in replicas_by_t]


def test_resource_summary_proxy():
    s = summarize_resources(samples([(0, 2), (1800, 4), (3600, 4)]))
    # 2 replicas for 0.5 h + 4 replicas for 0.5 h = 3 replica-hours
    assert s.replica_hours == pytest.approx(3.0)
    assert s.allocated_vcpu_hours == pytest.approx(1.5)
    assert s.allocated_gib_hours == pytest.approx(6.0)
    assert s.used_vcpu_hours == pytest.approx(0.75)
    assert s.cpu_allocation_efficiency_pct == pytest.approx(50.0)
    assert s.cost_model == "proxy" and s.estimated_cost is None
    assert s.resource_cost_proxy == pytest.approx(1.5 + 0.125 * 6.0)
    assert s.peak_ready_replicas == 4


def test_resource_summary_priced():
    s = summarize_resources(samples([(0, 2), (3600, 2)]), CostProfile(cpu_per_vcpu_hour=0.04, memory_per_gib_hour=0.005))
    assert s.cost_model == "priced"
    assert s.estimated_cost == pytest.approx(1.0 * 0.04 + 4.0 * 0.005)
    assert "not a bill" in s.cost_label


def test_percent_change_requires_positive_baseline():
    assert percent_change(10.0, 8.0) == pytest.approx(-20.0)
    assert percent_change(0.0, 5.0) is None
    assert percent_change(None, 5.0) is None


def test_scaling_stability_counts_reversals():
    assert scaling_stability({"a": [1, 2, 3, 2, 2, 3], "b": [1, 1]}) == {"scaling_events": 4, "oscillations": 2}


def test_unknown_used_cpu_is_not_invented():
    data = samples([(0, 1), (60, 1)])
    data[0]["services"]["a"]["cpu_cores"] = None
    s = summarize_resources(data)
    assert s.used_vcpu_hours is None and s.cpu_allocation_efficiency_pct is None


def test_policy_dataclass_replace_keeps_validity():
    p = AppPolicy.load("config/apps/shopping.yaml")
    assert dataclasses.replace(p, mode="live").validate() == []
