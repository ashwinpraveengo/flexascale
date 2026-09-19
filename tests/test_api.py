"""
Integration tests for FlexaScale REST API (Phase 5).
"""

import pytest
from fastapi.testclient import TestClient

from flexascale.api.app import create_app
from flexascale.api.state_store import APIStateStore


@pytest.fixture
def client():
    store = APIStateStore(mock=True)
    app = create_app(mock=True, state_store=store)
    return TestClient(app)


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"


def test_system_status(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "modes" in data
    assert "replicas" in data
    assert len(data["modes"]) == 4


def test_metrics_endpoint(client):
    res = client.get("/api/metrics")
    assert res.status_code == 200
    metrics = res.json()
    assert len(metrics) == 4
    for m in metrics:
        assert "cpu_utilization" in m
        assert "latency_ms" in m
        assert "replica_count" in m
        assert "slo_satisfied" in m


def test_history_endpoint(client):
    res = client.get("/api/history")
    assert res.status_code == 200
    history = res.json()
    assert len(history) > 0
    assert "cpu_utilization" in history[0]
    assert "latency_ms" in history[0]


def test_graph_endpoint(client):
    res = client.get("/api/graph")
    assert res.status_code == 200
    graph = res.json()
    assert graph["num_nodes"] == 4
    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) >= 3


def test_config_get_and_update(client):
    # GET config
    res = client.get("/api/config")
    assert res.status_code == 200
    cfg = res.json()
    assert cfg["target_cpu_utilization"] == 70.0

    # POST update config
    update_payload = {
        "slo_latency_target_ms": 150.0,
        "confidence_threshold": 0.82,
    }
    res = client.post("/api/config", json=update_payload)
    assert res.status_code == 200
    updated = res.json()
    assert updated["slo_latency_target_ms"] == 150.0
    assert updated["confidence_threshold"] == 0.82


def test_emergency_fallback(client):
    res = client.post("/api/fallback")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "fallback_executed"
    for mode in data["modes"].values():
        assert mode == "HPA"


def test_step_trigger(client):
    res = client.post("/api/step")
    assert res.status_code == 200
    decisions = res.json()
    assert len(decisions) == 4
