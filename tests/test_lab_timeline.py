"""
Backend of the dashboard's Live Autoscaling Timeline: incremental experiment snapshots, the live
history buffer, and proposal fields that go stale instead of being carried forward.
"""

from __future__ import annotations

import time

import pytest

from flexascale.lab import experiments as exp_mod
from flexascale.lab.experiments import Experiment, ExperimentRequest, Lab
from tests.fakes import FakeCluster, deployment
from tests.test_lab import ROOT


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(exp_mod, "ROOT", ROOT)
    cfg = tmp_path / "lab.yaml"
    cfg.write_text(f"""
prometheus_url: http://127.0.0.1:9
results_dir: {tmp_path / 'runs'}
apps:
  shopping:
    title: Shop
    policy: config/apps/shopping.yaml
    url: http://127.0.0.1:1
    locustfile: load-testing/scenarios.py
""", encoding="utf-8")
    c = FakeCluster("flexascale-apps").add(deployment("api-gateway"))
    return Lab(config_path=cfg, runtime_dir=tmp_path / "rt", kube=c.kube())


def test_incremental_snapshot_never_skips_or_repeats(lab):
    exp = Experiment(lab, ExperimentRequest("shopping", "hpa", "flash_sale", users=5, duration=30))
    exp.samples = [{"t": float(i), "services": {}} for i in range(5)]
    # an event stamped *before* the last sample but appended after it: a time cursor would lose it
    exp.events = [{"t": 0.5, "kind": "a", "message": "a"}, {"t": 3.5, "kind": "b", "message": "b"}]
    full = exp.snapshot()
    assert not full["delta"] and len(full["samples"]) == 5 and full["samples_total"] == 5 and full["events_total"] == 2
    exp.samples.append({"t": 5.0, "services": {}})
    exp.events.append({"t": 2.0, "kind": "late", "message": "late"})
    d = exp.snapshot(samples_from=5, events_from=2)
    assert d["delta"] and [s["t"] for s in d["samples"]] == [5.0] and [e["kind"] for e in d["events"]] == ["late"]
    assert exp.snapshot(samples_from=6, events_from=3)["samples"] == []


def test_run_json_has_no_polling_metadata(lab):
    exp = Experiment(lab, ExperimentRequest("shopping", "hpa", "flash_sale", users=5, duration=30))
    exp._write_files("completed")
    import json

    data = json.loads((exp.dir / "run.json").read_text(encoding="utf-8"))
    assert not {"delta", "samples_offset", "samples_total", "events_total"} & set(data)
    assert data["sample_interval_s"] == lab.cfg.sample_interval_seconds


def test_live_history_is_recorded_at_the_sample_interval_and_filtered_by_time(lab):
    def live(t):
        return {"timestamp": t, "lease": {"holder": None}, "services": [
            {"name": "api-gateway", "owner": "hpa", "desired_replicas": 2, "ready_replicas": 1, "hpa": {"desired_replicas": 2, "frozen": False},
             "metrics": {"cpu_pct": 40.0, "request_rate": 0.0, "no_traffic": True, "missing": []}},
            {"name": "postgres", "owner": "excluded"}]}

    for t in (100.0, 101.0, 105.0, 110.0):  # 101 is closer than 0.8 x 5 s to 100: not recorded
        lab._record_history("shopping", live(t))
    pts = lab.history("shopping")["points"]
    assert [p["t"] for p in pts] == [100.0, 105.0, 110.0]
    assert set(pts[0]["services"]) == {"api-gateway"} and pts[0]["services"]["api-gateway"]["no_traffic"] is True
    assert [p["t"] for p in lab.history("shopping", since=105.0)["points"]] == [110.0]


def test_proposals_are_shown_only_while_fresh(lab):
    exp = Experiment(lab, ExperimentRequest("shopping", "flexascale", "flash_sale", users=5, duration=30))
    now = time.time()
    exp._decision_events([{"type": "decision", "service": "api-gateway", "ts": now, "current_replicas": 1, "policy_replicas": 3, "proposed_replicas": 2,
                           "controller": "flexascale", "applied": True, "hpa_recommendation": 4, "policy": {}}])
    f = exp._proposal_fields("api-gateway", now + 1)
    assert f == {"fs_policy": 3, "fs_proposed": 2, "fs_controller": "flexascale", "fs_applied": True, "hpa_rule": 4}
    stale = exp._proposal_fields("api-gateway", now + 10 * lab.policy("shopping").poll_interval_seconds)
    assert all(v is None for v in stale.values())
    assert all(v is None for v in exp._proposal_fields("cart-service", now).values())
