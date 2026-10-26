"""Auto mode: ordered, explainable FlexaScale/HPA arbitration with hysteresis."""

import pytest

from flexascale.operator.auto_mode import AutoArbiter, AutoConfig, hpa_recommendation


def decide(arb, svc="api", **kw):
    args = dict(model_available=True, telemetry_ok=True, lease_held=True, confidence=0.9, activation=0.5,
                deactivation=0.4, current=2, flexascale_proposal=2, cpu_pct=60.0, latency_ms=50.0, slo_ms=250.0,
                lo=1, hi=10)
    args.update(kw)
    return arb.decide(svc, **args)


@pytest.fixture
def arb():
    return AutoArbiter(AutoConfig(dwell_steps=2), cpu_target_pct=70.0)


def test_hpa_formula():
    assert hpa_recommendation(2, 140.0, 70.0, 0.1, 1, 10) == 4
    assert hpa_recommendation(4, 72.0, 70.0, 0.1, 1, 10) == 4
    assert hpa_recommendation(3, 10.0, 70.0, 0.1, 1, 10) == 1
    assert hpa_recommendation(9, 300.0, 70.0, 0.1, 1, 10) == 10


def test_healthy_service_moves_to_flexascale_after_dwell(arb):
    d1 = decide(arb)
    assert d1.candidate == "flexascale" and d1.owner == "hpa" and "waiting 1/2" in d1.reason
    d2 = decide(arb)
    assert d2.owner == "flexascale" and d2.rule == "efficiency"


@pytest.mark.parametrize("kw,why", [
    ({"model_available": False}, "no trained"),
    ({"telemetry_ok": False}, "telemetry"),
    ({"lease_held": False}, "Lease"),
])
def test_controller_health_hands_back_immediately(arb, kw, why):
    decide(arb), decide(arb)
    assert arb.owner("api") == "flexascale"
    d = decide(arb, **kw)
    assert d.owner == "hpa" and d.rule == "controller_health" and why in d.reason


def test_confidence_uses_hysteresis(arb):
    d = decide(arb, confidence=0.45)                    # below activation 0.5: stays HPA
    assert d.owner == "hpa" and d.rule == "policy_confidence"
    decide(arb), decide(arb)                            # take over
    assert decide(arb, confidence=0.45).owner == "flexascale"   # above deactivation 0.4: keeps it
    d = decide(arb, confidence=0.3)
    assert d.owner == "hpa" and d.rule == "policy_confidence"


def test_sla_risk_gives_capacity_to_the_more_generous_controller(arb):
    decide(arb), decide(arb)
    d = decide(arb, latency_ms=400.0, cpu_pct=140.0, flexascale_proposal=3)   # HPA wants 4 > 3
    assert d.owner == "hpa" and d.rule == "sla_risk" and d.hpa_recommendation == 4
    assert "HPA would scale to 4" in d.reason


def test_sla_risk_keeps_flexascale_when_it_scales_more(arb):
    decide(arb), decide(arb)
    d = decide(arb, latency_ms=400.0, cpu_pct=90.0, flexascale_proposal=5)    # HPA wants 3 < 5
    assert d.owner == "flexascale" and d.rule == "efficiency" and "scales ahead" in d.reason


def test_decision_is_explained(arb):
    d = decide(arb, flexascale_proposal=1, cpu_pct=40.0).to_dict()
    assert set(d) >= {"owner", "rule", "reason", "candidate", "hpa_recommendation", "flexascale_proposal", "inputs"}
    assert d["inputs"]["cpu_pct"] == 40.0


def test_config_validation():
    assert AutoConfig(dwell_steps=0).validate()
    with pytest.raises(ValueError):
        AutoConfig.from_dict({"nonsense": 1})
    assert AutoConfig.from_dict({"cpu_risk_pct": 90}).cpu_risk_pct == 90


# --- operator integration (fake cluster) --------------------------------------------------

from tests.test_policy_and_operator import FakeRuntime, make_operator  # noqa: E402


def _auto_op(tmp_path, **kw):
    op, c = make_operator(tmp_path, mode="live", auto={"dwell_steps": 1}, **kw)
    from flexascale.operator.auto_mode import AutoArbiter, AutoConfig
    op.arbiter = AutoArbiter(AutoConfig(dwell_steps=1), op.policy.cpu_target_pct)
    return op, c


def test_auto_operator_records_rule_and_freezes_only_flexascale_services(tmp_path):
    op, c = _auto_op(tmp_path)
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["auto"]["rule"] in ("efficiency", "sla_risk")
    if api["auto"]["owner"] == "flexascale":
        assert (c.hpas["api-hpa"]["spec"]["minReplicas"], c.hpas["api-hpa"]["spec"]["maxReplicas"]) == (3, 3)
    assert op.status()["auto"] is True and "api" in op.status()["auto_state"]
    op.shutdown()
    assert (c.hpas["api-hpa"]["spec"]["minReplicas"], c.hpas["api-hpa"]["spec"]["maxReplicas"]) == (1, 6)


def test_auto_operator_hands_to_hpa_under_sla_risk(tmp_path):
    # api at 140% CPU: HPA wants ceil(2*140/70)=4, FlexaScale proposes 2 (hold) -> HPA owns it, HPA not frozen
    op, c = _auto_op(tmp_path, action=1, metrics={"api": {"cpu_pct": 140.0, "memory_pct": 40.0},
                                                  "worker": {"cpu_pct": 50.0, "memory_pct": 40.0}})
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["auto"]["owner"] == "hpa" and api["auto"]["rule"] == "sla_risk" and api["controller"] == "hpa"
    assert "auto_sla_risk" in api["safety_reasons"]
    assert c.hpas["api-hpa"]["spec"]["minReplicas"] == 1 and c.hpas["api-hpa"]["spec"]["maxReplicas"] == 6
    op.shutdown()


def test_auto_operator_missing_telemetry_goes_to_hpa(tmp_path):
    op, c = _auto_op(tmp_path, metrics={"worker": {"cpu_pct": 50.0, "memory_pct": 40.0}})
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["auto"]["rule"] == "controller_health" and api["controller"] == "hpa"
    op.shutdown()
