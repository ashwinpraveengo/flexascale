"""Calibrated tuned-HPA controller ("hpa_tuned", docs/POLICY_V7.md §2): CPU target set/restore, validation, pairing."""

import json
from pathlib import Path

from tests.fakes import FakeCluster, deployment, hpa

from flexascale.config.safety_config import SafetyConfig
from flexascale.lab.benchmark import benchmark
from flexascale.safety.hpa_manager import HPAManager

ANN_M = "flexascale.io/original-metrics"
ANN_B = "flexascale.io/original-behavior"
CPU70 = [{"type": "Resource", "resource": {"name": "cpu", "target": {"type": "Utilization", "averageUtilization": 70}}}]


def _hpa(name, target, metrics=CPU70):
    h = hpa(name, target)
    h["spec"]["metrics"] = json.loads(json.dumps(metrics))
    return h


def _cluster():
    mem_only = [{"type": "Resource", "resource": {"name": "memory", "target": {"type": "Utilization", "averageUtilization": 80}}}]
    return FakeCluster("demo").add(deployment("gateway"), deployment("orders"), deployment("cache")).add(
        _hpa("gateway-hpa", "gateway"), _hpa("orders-hpa", "orders", CPU70 + mem_only), _hpa("cache-hpa", "cache", mem_only),
        kind="hpa")


def _manager(c):
    return HPAManager(SafetyConfig(namespace="demo", dry_run=False), kube=c.kube(), holder="lab")


def test_cpu_target_is_set_only_on_cpu_metrics_and_the_original_recorded():
    c = _cluster()
    assert sorted(_manager(c).set_cpu_target(250)) == ["gateway-hpa", "orders-hpa"]
    gw, orders, cache = c.hpas["gateway-hpa"], c.hpas["orders-hpa"], c.hpas["cache-hpa"]
    assert gw["spec"]["metrics"][0]["resource"]["target"] == {"type": "Utilization", "averageUtilization": 250}
    assert json.loads(gw["metadata"]["annotations"][ANN_M]) == CPU70
    assert orders["spec"]["metrics"][1]["resource"]["name"] == "memory"  # other metrics untouched
    assert orders["spec"]["metrics"][1]["resource"]["target"]["averageUtilization"] == 80
    assert ANN_M not in cache["metadata"]["annotations"]  # no CPU metric: left alone


def test_restore_puts_back_the_original_metrics_once():
    c = _cluster()
    m = _manager(c)
    m.set_cpu_target(250)
    m.set_cpu_target(350)  # a second override keeps the first recorded original
    assert sorted(m.restore_all_metrics()) == ["gateway-hpa", "orders-hpa"]
    assert c.hpas["gateway-hpa"]["spec"]["metrics"] == CPU70
    assert c.hpas["orders-hpa"]["spec"]["metrics"][0] == CPU70[0]
    for h in c.hpas.values():
        assert ANN_M not in h["metadata"]["annotations"]
    assert m.restore_all_metrics() == []


def test_unreadable_original_is_left_for_manual_repair():
    c = _cluster()
    c.hpas["gateway-hpa"]["metadata"]["annotations"][ANN_M] = "not json"
    assert _manager(c).restore_all_metrics() == []
    assert c.hpas["gateway-hpa"]["metadata"]["annotations"][ANN_M] == "not json"


def _lab(tmp_path, monkeypatch, extra=""):
    from flexascale.lab import experiments as exp_mod
    from flexascale.lab.experiments import Lab

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(exp_mod, "ROOT", root)
    monkeypatch.setattr(exp_mod, "resolve_app_url", lambda app, profile: "http://127.0.0.1:1")
    cfg = tmp_path / "lab.yaml"
    cfg.write_text(f"""
prometheus_url: http://127.0.0.1:9
results_dir: {tmp_path / 'runs'}
{extra}
apps:
  shopping:
    title: Shop
    policy: config/apps/shopping.yaml
    url: http://127.0.0.1:1
    variants:
      alt: config/apps/shopping.yaml
""")
    c = FakeCluster("flexascale-apps").add(deployment("api-gateway")).add(_hpa("api-gateway-hpa", "api-gateway"), kind="hpa")
    lab = Lab(config_path=cfg, runtime_dir=tmp_path / "rt", kube=c.kube())
    monkeypatch.setattr(lab.metrics, "healthy", lambda: True)
    return lab, c


def test_request_validation(tmp_path, monkeypatch):
    from flexascale.lab.experiments import ExperimentRequest

    lab, _ = _lab(tmp_path, monkeypatch)
    ok = ExperimentRequest("shopping", "hpa_tuned", "calibration_steady", hpa_cpu_target_pct=250, hpa_scale_down_window_s=60)
    assert ok.validate(lab.cfg) == []
    assert any("CPU target" in e for e in ExperimentRequest("shopping", "hpa_tuned", "flash_sale").validate(lab.cfg))
    assert any("only to the hpa_tuned" in e for e in
               ExperimentRequest("shopping", "hpa", "flash_sale", hpa_cpu_target_pct=150).validate(lab.cfg))
    assert any("variant" in e for e in ExperimentRequest("shopping", "auto", "flash_sale", policy_variant="nope").validate(lab.cfg))
    assert ExperimentRequest("shopping", "auto", "flash_sale", policy_variant="alt").validate(lab.cfg) == []


def test_config_defaults_are_recorded_in_the_request(tmp_path, monkeypatch):
    from flexascale.lab.experiments import ExperimentRequest

    lab, _ = _lab(tmp_path, monkeypatch, "hpa_tuned: {cpu_target_pct: 150, scale_down_window_s: 60}")
    req = ExperimentRequest("shopping", "hpa_tuned", "flash_sale")
    assert req.validate(lab.cfg) == []
    assert req.hpa_tuned_settings(lab.cfg) == (150, 60)


def test_lab_hpa_tuned_run_sets_and_restores_target_and_window(tmp_path, monkeypatch):
    from flexascale.lab.experiments import Experiment, ExperimentRequest

    lab, c = _lab(tmp_path, monkeypatch)
    exp = Experiment(lab, ExperimentRequest("shopping", "hpa_tuned", "calibration_steady", users=5, duration=30,
                                            reset_replicas=False, shadow=False, hpa_cpu_target_pct=250,
                                            hpa_scale_down_window_s=60))
    exp._prepare()
    h = c.hpas["api-gateway-hpa"]
    assert h["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"] == 250
    assert h["spec"]["behavior"]["scaleDown"]["stabilizationWindowSeconds"] == 60
    assert any("Tuned native HPA: CPU target 250%" in e["message"] for e in exp.events)
    assert not lab.pm.is_running("operator")

    exp._teardown()
    assert h["spec"]["metrics"] == CPU70 and "behavior" not in h["spec"]
    assert not ({ANN_M, ANN_B} & set(h["metadata"]["annotations"]))
    assert exp.cleanup["safe"] is True and exp.cleanup["frozen_hpas_after"] == []


def _run(run_id, controller, started_at, block=None, **req):
    return {"id": run_id, "started_at": started_at, "model": {"model_path": "models/flexascale_v7/model.zip"},
            "request": {"app": "shop", "controller": controller, "scenario": "flash_sale", "users": 25, "duration": 300,
                        "block": block, **req},
            "summary": {"complete": True}}


def _compare(a, b):
    return {"comparable": True, "rows": [{"metric": "Replica-hours", "pct_change": -1.0}]}


def test_block_runs_pair_inside_their_block_whatever_the_order():
    runs = [_run("hpa-old", "hpa", 1),
            _run("tuned1", "hpa_tuned", 2, "b1", hpa_cpu_target_pct=150, hpa_scale_down_window_s=60),
            _run("auto1", "auto", 3, "b1"), _run("hpa1", "hpa", 4, "b1"),
            _run("fs-unblocked", "flexascale", 5)]
    models = {m["model"]: m for m in benchmark(runs, _compare)["models"]}
    assert models["Native HPA, tuned (150% CPU, 60 s scale-down)"]["pairs"][0]["baseline"] == "hpa1"
    assert models["v7 (Auto mode)"]["pairs"][0]["baseline"] == "hpa1"   # same block, even though it ran later
    assert models["v7"]["pairs"][0]["baseline"] == "hpa-old"            # unlabelled runs keep the old rule
