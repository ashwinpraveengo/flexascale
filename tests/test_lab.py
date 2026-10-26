"""
Tests for the Live Autoscaling Lab: managed processes, Locust result parsing,
run comparison rules, the HTTP API, workload scenarios, review scripts and the
simulator extensions used for training.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flexascale.lab import experiments as exp_mod
from flexascale.lab.experiments import ExperimentRequest, Lab, LabConfig, read_locust_final, read_locust_history
from flexascale.lab.processes import ProcessManager, ProcessRecord
from flexascale.lab.server import create_lab_app
from tests.fakes import FakeCluster, deployment

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- processes


def test_process_lifecycle_and_duplicate_refusal(tmp_path):
    pm = ProcessManager(tmp_path)
    pm.start("sleeper", ["sleep", "30"], marker="sleep 30")
    assert pm.is_running("sleeper")
    with pytest.raises(RuntimeError):
        pm.start("sleeper", ["sleep", "30"])
    other = ProcessManager(tmp_path)  # e.g. the stop script, a different process
    time.sleep(0.3)
    assert other.is_running("sleeper")
    assert other.stop("sleeper", timeout=15) == "stopped"
    assert not pm.is_running("sleeper")
    assert pm.stop("sleeper") == "not_managed"


def test_stale_record_never_kills_unrelated_process(tmp_path):
    """A PID file pointing at a live but unrelated process must not be signalled."""
    pm = ProcessManager(tmp_path)
    victim = subprocess.Popen(["sleep", "30"])
    try:
        rec = ProcessRecord(name="locust", pid=victim.pid, pgid=os.getpgid(victim.pid), cmd=["locust"],
                            marker="locust -f", start_ticks=None, started_at=0, log="")
        (tmp_path / "pids" / "locust.json").write_text(json.dumps(rec.__dict__))
        assert not pm.is_running("locust")
        assert pm.stop("locust") == "already_stopped"
        assert victim.poll() is None, "unrelated process was killed"
    finally:
        victim.kill()


# ---------------------------------------------------------------- locust parsing

HISTORY = """Timestamp,User Count,Type,Name,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%,Total Request Count,Total Failure Count
1,5,,Aggregated,1.0,0.0,20,25,30,35,40,50,60,70,80,90,100,10,0
2,10,,Aggregated,4.5,0.5,30,35,40,45,60,120,150,300,400,500,600,55,3
"""
FINAL = """Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%
GET,/x,40,1,30,35,5,500,10,2,0,30,35,40,45,60,120,150,300,400,500,500
,Aggregated,55,3,30,41.2,5,600,10,4.5,0.2,30,35,40,45,60,120,150,300,400,500,600
"""


def test_read_locust_csvs(tmp_path):
    (tmp_path / "h.csv").write_text(HISTORY)
    (tmp_path / "f.csv").write_text(FINAL)
    h = read_locust_history(tmp_path / "h.csv")
    assert h["users"] == 10 and h["p95_ms"] == 120 and h["total_failures"] == 3
    f = read_locust_final(tmp_path / "f.csv")
    assert f["total_requests"] == 55 and f["p99_ms"] == 300
    assert f["failure_rate_pct"] == pytest.approx(100 * 3 / 55)
    assert read_locust_history(tmp_path / "missing.csv") is None


# ---------------------------------------------------------------- lab + API


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
""")
    c = FakeCluster("flexascale-apps").add(deployment("api-gateway"), deployment("postgres", image="postgres:16"))
    return Lab(config_path=cfg, runtime_dir=tmp_path / "rt", kube=c.kube())


def write_run(lab, run_id, controller, scenario="flash_sale", users=40, duration=300, complete=True, p95=500.0, rh=0.5,
              settled=True):
    d = Path(lab.cfg.results_dir) / run_id
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({
        "id": run_id, "state": "completed" if complete else "stopped", "started_at": 1,
        "request": {"app": "shopping", "controller": controller, "scenario": scenario, "users": users,
                    "spawn_rate": 5, "duration": duration},
        "summary": {"complete": complete, "preliminary": False, "actual_duration_s": duration, "settled_start": settled,
                    "workload": {"p95_ms": p95, "throughput_rps": 10.0},
                    "resources": {"replica_hours": rh, "resource_cost_proxy": rh / 10, "cost_label": "proxy"}},
    }))


def test_compare_comparable_runs(lab):
    write_run(lab, "a", "hpa", p95=500, rh=0.5)
    write_run(lab, "b", "flexascale", p95=400, rh=0.6)
    out = lab.compare("a", "b")
    assert out["comparable"] and out["issues"] == []
    rows = {r["metric"]: r for r in out["rows"]}
    assert rows["p95 latency (ms)"]["pct_change"] == pytest.approx(-20.0)
    assert rows["Replica-hours"]["pct_change"] == pytest.approx(20.0)


def test_compare_hides_percentages_for_incomparable_runs(lab):
    write_run(lab, "a", "hpa", scenario="flash_sale")
    write_run(lab, "b", "flexascale", scenario="steady_browsing", complete=False)
    out = lab.compare("a", "b")
    assert not out["comparable"]
    assert any("scenario" in i for i in out["issues"]) and any("incomplete" in i for i in out["issues"])
    assert all(r["pct_change"] is None for r in out["rows"])


def test_run_ids_cannot_escape_results_dir(lab):
    with pytest.raises(KeyError):
        lab.run("../../etc")


def test_request_validation(lab):
    assert ExperimentRequest("shopping", "hpa", "flash_sale").validate(lab.cfg) == []
    errs = ExperimentRequest("nope", "kubectl delete", "x", users=0, duration=5).validate(lab.cfg)
    assert len(errs) == 5


def test_api_endpoints(lab):
    with TestClient(create_lab_app(lab)) as client:
        assert client.get("/api/lab/health").json()["status"] == "ok"
        sc = client.get("/api/lab/scenarios").json()
        assert len(sc["scenarios"]) == 7 and "calibration_steady" in sc["scenarios"]
        assert sc["controllers"] == ["hpa", "flexascale", "auto", "hpa_fast", "hpa_tuned"]
        assert client.get("/api/lab/apps/unknown/live").status_code == 404
        r = client.post("/api/lab/experiments", json={"app": "shopping", "controller": "hpa", "scenario": "flash_sale", "users": 10_000})
        assert r.status_code == 422
        r = client.post("/api/lab/experiments", json={"app": "shopping", "controller": "rm -rf", "scenario": "flash_sale"})
        assert r.status_code == 422
        assert client.get("/api/lab/experiments/active").json() == {"active": None}
        assert client.post("/api/lab/experiments/stop").status_code == 404
        live = client.get("/api/lab/apps/shopping/live").json()
        owners = {s["name"]: s["owner"] for s in live["services"]}
        assert owners == {"api-gateway": "none", "postgres": "excluded"}
        assert "access-control-allow-origin" not in client.options("/api/lab/experiments", headers={"Origin": "http://evil"}).headers


def test_failed_preflight_leaves_safe_state(lab):
    """Prometheus is unreachable in this fixture: the run must fail cleanly and clean up."""
    exp = lab.start(ExperimentRequest("shopping", "flexascale", "flash_sale", users=5, duration=30))
    exp.thread.join(timeout=60)
    assert exp.state == "failed" and "Prometheus" in exp.error
    assert exp.cleanup["safe"] is True
    assert (exp.dir / "run.json").is_file()
    assert not lab.pm.is_running("operator") and not lab.pm.is_running("locust")


# ---------------------------------------------------------------- scenarios & scripts


@pytest.mark.parametrize("scenario", ["steady_browsing", "gradual_ramp", "flash_sale", "checkout_heavy",
                                      "traffic_drop", "payment_degradation"])
def test_scenario_shapes(scenario):
    code = (
        "import sys; sys.path.insert(0, 'load-testing'); import scenarios as s; "
        "print(len(s.ScenarioShape.stages), max(u for _, u, _, _ in s.ScenarioShape.stages), s.ScenarioShape.stages[-1][0])"
    )
    env = dict(os.environ, FLEXASCALE_SCENARIO=scenario, FLEXASCALE_USERS="50", FLEXASCALE_DURATION="300")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    n, peak, end = out.stdout.split()
    assert int(peak) == 50 and float(end) == 1.0


def test_unknown_scenario_is_rejected():
    env = dict(os.environ, FLEXASCALE_SCENARIO="drop_tables")
    out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0,'load-testing'); import scenarios"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode != 0


@pytest.mark.parametrize("script", ["start_review.sh", "start_demo.sh", "stop_review.sh", "review_status.sh", "run_live_batch.sh",
                                    "lib/review_common.sh", "lib/keep_port_forward.sh", "teardown_cluster.sh"])
def test_scripts_parse(script):
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / script)]).returncode == 0


def test_stop_script_never_kills_by_port_or_stops_cluster():
    text = (ROOT / "scripts" / "stop_review.sh").read_text() + (ROOT / "scripts" / "lib" / "review_common.sh").read_text()
    for forbidden in ("fuser -k", "kill -9 $(lsof", "minikube stop", "minikube delete", "helm uninstall", "kubectl delete"):
        assert forbidden not in text


def test_teardown_delete_requires_confirmation():
    out = subprocess.run(["bash", str(ROOT / "scripts" / "teardown_cluster.sh"), "no-such-profile", "--delete"],
                         input="wrong\n", capture_output=True, text=True, timeout=30)
    assert out.returncode == 1 and "Aborted" in out.stdout


# ---------------------------------------------------------------- simulator extensions


def test_random_sampling_and_normalized_demand():
    from flexascale.config.env_config import EnvConfig
    from flexascale.simulator.flexascale_env import FlexaScaleEnv

    env = FlexaScaleEnv(EnvConfig(split="val", service_sampling="random", demand_model="normalized",
                                  max_replicas=10, randomize_initial_replicas=True))
    env.reset(seed=1)
    first = list(env._all_service_ids)
    env.reset(seed=2)
    assert env._all_service_ids != first
    obs, _ = env.reset(seed=3)
    o = obs.reshape(4, 5)
    assert ((o[:, 2] >= 1) & (o[:, 2] <= 10)).all()
    assert ((o[:, 0] >= 0) & (o[:, 0] <= 100)).all()


def test_cost_weight_changes_reward_only_when_enabled():
    from flexascale.config.env_config import EnvConfig
    from flexascale.simulator.flexascale_env import FlexaScaleEnv

    base = dict(split="val", service_sampling="random", demand_model="normalized", max_replicas=10)
    r0 = FlexaScaleEnv(EnvConfig(**base)); r0.reset(seed=5)
    w = {"slo": 1.0, "efficiency": 0.3, "stability": 0.1, "cost": 0.5}
    r1 = FlexaScaleEnv(EnvConfig(reward_weights=w, **base)); r1.reset(seed=5)
    _, a, _, _, info0 = r0.step([1, 1, 1, 1])
    _, b, _, _, info1 = r1.step([1, 1, 1, 1])
    assert info0["reward_components"]["cost"] == pytest.approx(info1["reward_components"]["cost"])
    assert b < a


def test_processed_dataset_is_in_percent_units():
    import pandas as pd

    df = pd.read_csv(ROOT / "data/processed/alibaba_service_state_test.csv", usecols=["cpu_utilization", "memory_utilization"])
    assert df["cpu_utilization"].max() > 1.0 and df["memory_utilization"].max() <= 100.0
    prov = json.loads((ROOT / "data/processed/PROVENANCE.json").read_text())
    assert prov["units"]["cpu_utilization"].startswith("percent")


def test_start_settled_uses_first_sample():
    from flexascale.lab.experiments import start_settled
    at_min = {"samples": [{"services": {"a": {"desired": 1, "hpa_min": 1}, "b": {"desired": 2, "hpa_min": 2}}}]}
    above = {"samples": [{"services": {"a": {"desired": 3, "hpa_min": 1}}}], "summary": {"settled_start": True}}
    frozen_high = {"samples": [{"services": {"a": {"desired": 8, "hpa_min": 8, "frozen": True}}}], "policy": {"min_replicas": 1}}
    assert start_settled(at_min) is True and start_settled(above) is False and start_settled(frozen_high) is False
    # FlexaScale acting right after handoff must not count against the start condition
    fs = {"request": {"controller": "flexascale"}, "start_replicas": {"a": 1},
          "samples": [{"services": {"a": {"desired": 2, "hpa_min": 2, "frozen": True}}}]}
    assert start_settled(fs) is True


def test_unsettled_start_is_not_comparable(lab):
    write_run(lab, "a", "hpa")
    write_run(lab, "b", "flexascale", settled=False)
    out = lab.compare("a", "b")
    assert not out["comparable"] and any("settled" in i for i in out["issues"])
