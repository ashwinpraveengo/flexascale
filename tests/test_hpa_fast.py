"""Tuned-HPA reference controller ("hpa_fast"): HPA behaviour set/restore and benchmark pairing."""

import json

from tests.fakes import FakeCluster, deployment, hpa

from flexascale.config.safety_config import SafetyConfig
from flexascale.lab.benchmark import benchmark
from flexascale.safety.hpa_manager import HPAManager

ANN = "flexascale.io/original-behavior"


def _cluster():
    tuned = hpa("orders-hpa", "orders")
    tuned["spec"]["behavior"] = {"scaleUp": {"stabilizationWindowSeconds": 30}}
    return FakeCluster("demo").add(deployment("gateway"), deployment("orders")).add(
        hpa("gateway-hpa", "gateway"), tuned, kind="hpa")


def _manager(c):
    return HPAManager(SafetyConfig(namespace="demo", dry_run=False), kube=c.kube(), holder="lab")


def test_scale_down_window_is_set_and_original_behaviour_recorded():
    c = _cluster()
    assert sorted(_manager(c).set_scale_down_window(60)) == ["gateway-hpa", "orders-hpa"]
    gw, orders = c.hpas["gateway-hpa"], c.hpas["orders-hpa"]
    assert gw["spec"]["behavior"]["scaleDown"]["stabilizationWindowSeconds"] == 60
    assert json.loads(gw["metadata"]["annotations"][ANN]) is None
    assert orders["spec"]["behavior"]["scaleUp"] == {"stabilizationWindowSeconds": 30}
    assert json.loads(orders["metadata"]["annotations"][ANN]) == {"scaleUp": {"stabilizationWindowSeconds": 30}}


def test_second_set_keeps_the_first_recorded_original():
    c = _cluster()
    m = _manager(c)
    m.set_scale_down_window(60)
    m.set_scale_down_window(30)
    assert json.loads(c.hpas["gateway-hpa"]["metadata"]["annotations"][ANN]) is None


def test_restore_puts_back_exactly_the_original_behaviour():
    c = _cluster()
    m = _manager(c)
    m.set_scale_down_window(60)
    assert sorted(m.restore_all_behavior()) == ["gateway-hpa", "orders-hpa"]
    assert "behavior" not in c.hpas["gateway-hpa"]["spec"]
    assert c.hpas["orders-hpa"]["spec"]["behavior"] == {"scaleUp": {"stabilizationWindowSeconds": 30}}
    for h in c.hpas.values():
        assert ANN not in h["metadata"]["annotations"]
    assert m.restore_all_behavior() == []  # idempotent: nothing left to restore


def _run(run_id, controller, started_at, scenario="traffic_drop"):
    return {"id": run_id, "started_at": started_at, "model": {"model_path": "models/flexascale_v5/model.zip"},
            "request": {"app": "shop", "controller": controller, "scenario": scenario, "users": 25, "duration": 300},
            "summary": {"complete": True}}


def _compare(a, b):
    return {"comparable": True, "rows": [{"metric": "Replica-hours", "pct_change": -1.0}]}


def test_hpa_fast_is_a_candidate_and_never_a_baseline():
    runs = [_run("hpa1", "hpa", 1), _run("fast1", "hpa_fast", 2), _run("auto1", "auto", 3)]
    models = {m["model"]: m for m in benchmark(runs, _compare)["models"]}
    assert set(models) == {"Native HPA, 60 s scale-down", "v5 (Auto mode)"}
    assert models["Native HPA, 60 s scale-down"]["pairs"][0]["baseline"] == "hpa1"
    # The Auto run that follows the tuned-HPA run is still paired with the default-HPA run.
    assert models["v5 (Auto mode)"]["pairs"][0]["baseline"] == "hpa1"


def test_lab_hpa_fast_run_sets_and_restores_the_window(tmp_path, monkeypatch):
    """Lab prepare/teardown for 'hpa_fast' against a fake cluster: window applied, then restored and verified."""
    from pathlib import Path

    from flexascale.lab import experiments as exp_mod
    from flexascale.lab.experiments import Experiment, ExperimentRequest, Lab

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(exp_mod, "ROOT", root)
    monkeypatch.setattr(exp_mod, "resolve_app_url", lambda app, profile: "http://127.0.0.1:1")
    cfg = tmp_path / "lab.yaml"
    cfg.write_text(f"""
prometheus_url: http://127.0.0.1:9
results_dir: {tmp_path / 'runs'}
apps:
  shopping:
    title: Shop
    policy: config/apps/shopping.yaml
    url: http://127.0.0.1:1
""")
    c = FakeCluster("flexascale-apps").add(deployment("api-gateway")).add(hpa("api-gateway-hpa", "api-gateway"), kind="hpa")
    lab = Lab(config_path=cfg, runtime_dir=tmp_path / "rt", kube=c.kube())
    monkeypatch.setattr(lab.metrics, "healthy", lambda: True)

    exp = Experiment(lab, ExperimentRequest("shopping", "hpa_fast", "flash_sale", users=5, duration=30,
                                            reset_replicas=False, shadow=False))
    exp._prepare()
    h = c.hpas["api-gateway-hpa"]
    assert h["spec"]["behavior"]["scaleDown"]["stabilizationWindowSeconds"] == exp_mod.HPA_FAST_SCALE_DOWN_S
    assert ANN in h["metadata"]["annotations"]
    assert any("scale-down stabilisation window set to" in e["message"] for e in exp.events)
    assert not lab.pm.is_running("operator")  # native HPA stays the only controller

    exp._teardown()
    assert "behavior" not in h["spec"] and ANN not in h["metadata"]["annotations"]
    assert exp.cleanup["safe"] is True and exp.cleanup["frozen_hpas_after"] == []
