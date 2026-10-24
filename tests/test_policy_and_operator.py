"""
Tests for trained-policy inference (fixed 4-service model applied to N services)
and for the policy-driven AppOperator safety behaviour on a fake cluster.
"""

from __future__ import annotations

import json

import gymnasium as gym
import numpy as np
import pytest
import torch
from gymnasium import spaces

from flexascale.config.app_policy import AppPolicy
from flexascale.metrics.workload_metrics import WorkloadMetrics
from flexascale.operator.app_operator import AppOperator
from flexascale.rl.policy_runtime import PolicyOutput, PolicyRuntime, neighborhood_order
from tests.fakes import FakeCluster, deployment, hpa


class _Env(gym.Env):
    def __init__(self, k=4):
        self.observation_space = spaces.Box(
            low=np.array([0, 0, 1, 0, 0] * k, dtype=np.float32),
            high=np.array([100, 100, 10, 10000, 10000] * k, dtype=np.float32),
        )
        self.action_space = spaces.MultiDiscrete([3] * k)

    def reset(self, *, seed=None, options=None):
        return self.observation_space.sample(), {}

    def step(self, action):
        return self.observation_space.sample(), 0.0, True, False, {}


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    from stable_baselines3 import PPO
    from flexascale.rl.gnn_encoder import GNNExtractor

    m = PPO("MlpPolicy", _Env(), n_steps=8, batch_size=8,
            policy_kwargs=dict(features_extractor_class=GNNExtractor, features_extractor_kwargs=dict(features_dim=16, hidden_dim=16)))
    path = tmp_path_factory.mktemp("model") / "m.zip"
    m.save(str(path))
    return path


def feats(names, cpu=50.0):
    return {n: np.array([cpu, 30.0, 2.0, 10.0, 20.0], dtype=np.float32) for n in names}


def test_neighborhood_order_is_deterministic_bfs():
    edges = [("gw", "a"), ("gw", "b"), ("a", "c")]
    assert neighborhood_order("c", ["gw", "a", "b", "c"], edges) == ["c", "a", "gw", "b"]
    assert neighborhood_order("gw", ["gw", "a", "b", "c"], edges) == ["gw", "a", "b", "c"]


def test_runtime_reports_topology(model_path):
    rt = PolicyRuntime(model_path)
    info = rt.info()
    assert info["trained_services"] == 4 and info["observation_dim"] == 20
    assert len(info["sha256"]) == 64


@pytest.mark.parametrize("n", [1, 3, 4, 5, 7, 9])
def test_runtime_handles_any_service_count(model_path, n):
    rt = PolicyRuntime(model_path)
    names = [f"svc-{i}" for i in range(n)]
    out = rt.predict(feats(names), edges=[(names[0], x) for x in names[1:]])
    assert out.mode == ("ppo_direct" if n == 4 else "ppo_neighborhood")
    assert len(out.actions) == len(out.confidences) == n
    assert all(a in (0, 1, 2) for a in out.actions)
    assert all(0.0 <= c <= 1.0 for c in out.confidences)
    for probs in out.probabilities:
        assert sum(probs) == pytest.approx(1.0, abs=1e-3)
    if n != 4:
        assert all(w[0] == names[i] for i, w in enumerate(sorted(out.windows, key=lambda w: w[0])))


def test_runtime_never_uses_untrained_node_head(model_path):
    rt = PolicyRuntime(model_path)
    names = [f"s{i}" for i in range(7)]
    before = rt.predict(feats(names))
    head = rt.model.policy.features_extractor.encoder.node_policy_head
    with torch.no_grad():
        for p in head.parameters():
            p.fill_(float("nan"))
    after = rt.predict(feats(names))
    assert after.actions == before.actions
    assert after.confidences == pytest.approx(before.confidences)


def test_runtime_output_is_order_independent(model_path):
    rt = PolicyRuntime(model_path)
    f = feats(["b", "a", "c", "d", "e"])
    out1 = rt.predict(f)
    out2 = rt.predict(dict(reversed(list(f.items()))))
    assert out1.actions == out2.actions


def test_runtime_clips_out_of_range_features(model_path):
    rt = PolicyRuntime(model_path)
    f = {f"s{i}": np.array([150.0, 30.0, 40.0, 5.0, 5.0], dtype=np.float32) for i in range(4)}
    out = rt.predict(f)
    assert set(out.clipped[0]) == {"cpu_utilization", "replica_count"}


# ---------------------------------------------------------------- AppOperator


class FakeMetrics:
    def __init__(self, values):
        self.values = values  # name -> dict of WorkloadMetrics fields

    def collect(self, namespace, deployments, cpu_req=None, mem_cap=None):
        return {d: WorkloadMetrics(deployment=d, **self.values.get(d, {"cpu_pct": None, "stale": True, "missing": ["cpu"]}))
                for d in deployments}


class FakeRuntime:
    def __init__(self, action=2, confidence=0.9):
        self.action, self.confidence = action, confidence

    def predict(self, features, edges=()):
        names = sorted(features)
        a = self.action if isinstance(self.action, dict) else {n: self.action for n in names}
        c = self.confidence if isinstance(self.confidence, dict) else {n: self.confidence for n in names}
        return PolicyOutput([a[n] for n in names], [c[n] for n in names], mode="ppo_neighborhood",
                            windows=[[n] for n in names], probabilities=[[0.1, 0.1, 0.8]] * len(names))

    def info(self):
        return {"model_path": "fake"}


def make_operator(tmp_path, mode="observe", action=2, confidence=0.9, metrics=None, **pol):
    c = FakeCluster("demo")
    c.add(deployment("api", replicas=2), deployment("worker", replicas=1), deployment("db", image="postgres:16"))
    c.add(hpa("api-hpa", "api", 1, 6), kind="hpa")
    p = AppPolicy(name="demo", namespace="demo", mode=mode, cooldown_seconds=0, scale_down_cooldown_seconds=0,
                  poll_interval_seconds=1, lease_seconds=10, **pol)
    m = FakeMetrics(metrics or {"api": {"cpu_pct": 80.0, "memory_pct": 40.0}, "worker": {"cpu_pct": 50.0, "memory_pct": 40.0}})
    op = AppOperator(p, kube=c.kube(), metrics=m, runtime=FakeRuntime(action, confidence),
                     decision_log=str(tmp_path / "d.jsonl"), status_file=str(tmp_path / "s.json"), identity="me")
    op._edges = lambda names: []
    return op, c


def test_observe_mode_never_modifies_cluster(tmp_path):
    op, c = make_operator(tmp_path, mode="observe")
    op.start()
    res = op.step()
    assert c.mutations == []
    assert {d["service"] for d in res.decisions} == {"api", "worker"}  # db excluded as a datastore
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["proposed_replicas"] == 3 and api["applied"] is False and api["mode"] == "observe"
    lines = [json.loads(l) for l in (tmp_path / "d.jsonl").read_text().splitlines()]
    assert lines[0]["event"] == "operator_start" and lines[0]["result"] == "observe_only"


def test_live_mode_takes_lease_freezes_then_scales(tmp_path):
    op, c = make_operator(tmp_path, mode="live")
    assert op.start()["result"] == "lease_acquired"
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["applied"] and api["controller"] == "flexascale"
    assert c.deployments["api"]["spec"]["replicas"] == 3
    spec = c.hpas["api-hpa"]["spec"]
    assert (spec["minReplicas"], spec["maxReplicas"]) == (3, 3)
    verbs = [m[0] for m in c.mutations if m[0] in ("patch", "scale") and "api" in " ".join(m)]
    assert verbs.index("patch") < verbs.index("scale"), "HPA must be frozen before the Deployment is scaled"
    assert c.deployments["worker"]["spec"]["replicas"] == 2  # no HPA: scaled directly
    op.shutdown()
    spec = c.hpas["api-hpa"]["spec"]
    assert (spec["minReplicas"], spec["maxReplicas"]) == (1, 6)
    assert c.deployments["worker"]["spec"]["replicas"] == 1, "HPA-less Deployment restored on shutdown"
    assert c.leases["flexascale-demo"]["spec"]["holderIdentity"] == ""


def test_second_operator_cannot_go_live(tmp_path):
    op, c = make_operator(tmp_path, mode="live")
    op.start()
    other = AppOperator(op.policy, kube=c.kube(), metrics=op.metrics, runtime=FakeRuntime(), identity="intruder")
    assert other.start()["result"].startswith("lease_unavailable")
    assert other.effective_mode == "observe"


def test_live_refused_without_model(tmp_path):
    op, _ = make_operator(tmp_path, mode="live")
    op.runtime = None
    assert op.start()["result"] == "refused_live_without_model"


def test_low_confidence_returns_to_hpa(tmp_path):
    op, c = make_operator(tmp_path, mode="live", confidence=0.9)
    op.start()
    op.step()
    op.runtime.confidence = 0.3
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["controller"] == "hpa" and "confidence_below_deactivation" in api["safety_reasons"]
    spec = c.hpas["api-hpa"]["spec"]
    assert (spec["minReplicas"], spec["maxReplicas"]) == (1, 6)


def test_missing_telemetry_holds_and_never_scales(tmp_path):
    op, c = make_operator(tmp_path, mode="live", metrics={"api": {"cpu_pct": None, "stale": True}, "worker": {"cpu_pct": 50.0}})
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert "telemetry_unavailable" in api["safety_reasons"] and not api["applied"]
    assert c.deployments["api"]["spec"]["replicas"] == 2


def test_scale_down_blocked_under_cpu_pressure(tmp_path):
    op, c = make_operator(tmp_path, mode="live", action=0,
                          metrics={"api": {"cpu_pct": 95.0, "memory_pct": 10.0}, "worker": {"cpu_pct": 50.0}})
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert "scale_down_blocked_cpu" in api["safety_reasons"]
    assert c.deployments["api"]["spec"]["replicas"] == 2


def test_replica_bounds_respected(tmp_path):
    op, c = make_operator(tmp_path, mode="live", action=2, max_replicas=2)
    op.start()
    op.step()
    assert c.deployments["api"]["spec"]["replicas"] == 2


def test_lease_loss_falls_back_to_hpa_and_observe(tmp_path):
    op, c = make_operator(tmp_path, mode="live")
    op.start()
    op.step()
    c.leases["flexascale-demo"]["spec"]["holderIdentity"] = "someone-else"
    res = op.step()
    assert res.mode == "observe" and any(e["event"] == "lease_lost" for e in res.events)
    spec = c.hpas["api-hpa"]["spec"]
    assert (spec["minReplicas"], spec["maxReplicas"]) == (1, 6)
    assert not any(d["applied"] for d in res.decisions)


def test_deployment_without_hpa_is_scaled_without_conflict(tmp_path):
    op, c = make_operator(tmp_path, mode="live")
    op.start()
    res = op.step()
    worker = next(d for d in res.decisions if d["service"] == "worker")
    assert worker["applied"] and c.deployments["worker"]["spec"]["replicas"] == 2


def test_scale_up_waits_for_pending_replicas(tmp_path):
    op, c = make_operator(tmp_path, mode="live")
    c.deployments["api"]["status"]["readyReplicas"] = 1  # 2 desired, 1 ready
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert "scale_up_waiting_for_readiness" in api["safety_reasons"]
    assert c.deployments["api"]["spec"]["replicas"] == 2


def test_app_wide_replica_budget_blocks_scale_up(tmp_path):
    op, c = make_operator(tmp_path, mode="live", max_total_replicas=4)  # api=2, worker=1 -> room for 1 more
    op.start()
    res = op.step()
    applied = [d for d in res.decisions if d["applied"]]
    blocked = [d for d in res.decisions if "scale_up_blocked_replica_budget" in d["safety_reasons"]]
    assert len(applied) == 1 and len(blocked) == 1
    assert sum(dep["spec"]["replicas"] for n, dep in c.deployments.items() if n != "db") == 4
