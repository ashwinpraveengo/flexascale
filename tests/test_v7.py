"""FlexaScale v7 (docs/POLICY_V7.md §4): features, graph policy, runtime, operator wiring, twin and its environment."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
import torch

from tests.fakes import FakeCluster, deployment, hpa

from flexascale.config.app_policy import AppPolicy
from flexascale.metrics.workload_metrics import WorkloadMetrics
from flexascale.operator.app_operator import AppOperator
from flexascale.rl import features_v3 as fv
from flexascale.simulator.twin import AppSpec, ServiceSpec, TwinSim, Workload
from flexascale.simulator.twin_control import V7_GUARDS, NativeHPA, OperatorLoop, limit_target_policy, simulate
from flexascale.simulator.twin_env import ACTION_DELTAS, HOLD_INDEX, N_MAX, RewardConfig, TwinEnv, episode_reward, load_shop
from flexascale.simulator.twin_workloads import EVALUATION_SCENARIOS, build, random_app, random_workload

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- features (shared by twin and operator)


def test_features_use_the_cpu_limit_and_track_history():
    tr = fv.FeatureTracker(["a"], max_replicas=10)
    x = tr.update(0.0, "a", cpu_cores=0.6, ready=2, desired=2, cpu_limit=0.5, rps=10.0, latency_ms=20.0)
    assert x[0] == pytest.approx(0.6)            # 0.3 cores per pod of a 0.5 limit, not 3x the request
    assert x[2] == 1.0                            # no rate 60 s ago yet
    assert x[3] == 0.0                            # latency equals its own baseline
    assert x[6] == pytest.approx(math.log10(60.0) / 3)  # 60 CPU-ms per request
    for t in (10, 20, 30, 40, 50):
        tr.update(float(t), "a", cpu_cores=0.6, ready=2, desired=2, cpu_limit=0.5, rps=10.0, latency_ms=20.0)
    x = tr.update(60.0, "a", cpu_cores=1.2, ready=2, desired=2, cpu_limit=0.5, rps=30.0, latency_ms=80.0)
    assert x[0] == pytest.approx(1.2) and x[1] == pytest.approx(0.6)
    assert x[2] == pytest.approx(3.0)             # 30 req/s against 10 a minute ago
    assert x[3] == pytest.approx(2.0)             # 4x its low-load latency -> log2 = 2
    assert x[7] > 0                               # burst: peak above mean
    tr.note_scale("a", 1, 60.0)
    x = tr.update(90.0, "a", cpu_cores=3.0, ready=2, desired=4, cpu_limit=0.5, rps=30.0, latency_ms=None)
    assert x[0] == fv.HIGH[0] and x[5] == pytest.approx(0.5) and x[8] == pytest.approx(0.5) and x[9] == 1.0


def test_pack_and_unpack_round_trip_with_graph_and_mask():
    feats = {s: np.full(fv.F, i / 10, dtype=np.float32) for i, s in enumerate(["gw", "orders", "pay"])}
    obs = fv.pack(feats, ["gw", "orders", "pay"], [("gw", "orders"), ("orders", "pay"), ("pay", "unknown")], n_max=5)
    assert obs.shape == (fv.obs_dim(5),)
    x, adj, mask = fv.unpack(obs, 5)
    assert mask.tolist() == [1, 1, 1, 0, 0]
    assert adj[0, 1] == 1 and adj[1, 2] == 1 and adj.sum() == 2  # edges to unknown services are dropped
    assert x[1, 0] == pytest.approx(0.1)
    with pytest.raises(ValueError):
        fv.pack(feats, ["gw", "orders", "pay"], [], n_max=2)


# ---------------------------------------------------------------- graph policy


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory):
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    from flexascale.rl.graph_policy import GraphPolicy

    torch.manual_seed(0)
    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    venv = DummyVecEnv([lambda: TwinEnv(app, cal, seed=3)])
    model = PPO(GraphPolicy, venv, n_steps=64, batch_size=64, n_epochs=1, seed=0, device="cpu",
                policy_kwargs={"n_max": N_MAX, "hidden": 16, "rounds": 2, "use_graph": True, "hold_index": HOLD_INDEX})
    model.learn(64)
    d = tmp_path_factory.mktemp("v7") / "best_model"
    d.mkdir()
    model.save(d / "best_model")
    (d / "model_card.json").write_text(json.dumps({
        "observation": {"version": 3, "n_max": N_MAX, "per_service_fields": list(fv.FEATURES), "max_replicas": 10},
        "action": {"deltas": list(ACTION_DELTAS)}}))
    return d / "best_model.zip", model


def test_padded_services_always_hold_and_add_no_entropy(tiny_model):
    _, model = tiny_model
    feats = {f"s{i}": np.random.default_rng(i).uniform(0, 1, fv.F).astype(np.float32) for i in range(6)}
    obs = fv.pack(feats, sorted(feats), [("s0", "s1"), ("s1", "s2")], N_MAX)
    dist = model.policy.get_distribution(torch.as_tensor(obs[None]))
    ent = [d.entropy().item() for d in dist.distribution]
    assert max(ent[6:]) < 1e-6 and min(ent[:6]) > 0.1
    a, _ = model.predict(obs, deterministic=True)
    assert set(a[6:].tolist()) == {HOLD_INDEX}


def test_no_graph_ablation_ignores_the_call_graph():
    from gymnasium import spaces

    from flexascale.rl.graph_policy import GraphExtractor

    space = spaces.Box(-1, 4, shape=(fv.obs_dim(6),), dtype=np.float32)
    torch.manual_seed(1)
    with_g, without_g = GraphExtractor(space, 6, 8, use_graph=True), GraphExtractor(space, 6, 8, use_graph=False)
    without_g.load_state_dict(with_g.state_dict())
    feats = {f"s{i}": np.random.default_rng(i).uniform(0, 1, fv.F).astype(np.float32) for i in range(4)}
    names = sorted(feats)
    a = torch.as_tensor(fv.pack(feats, names, [("s0", "s1"), ("s1", "s2"), ("s2", "s3")], 6)[None])
    b = torch.as_tensor(fv.pack(feats, names, [], 6)[None])
    assert not torch.allclose(with_g(a), with_g(b))          # messages change the embedding
    assert torch.allclose(without_g(a), without_g(b))        # the ablation cannot see edges


def test_runtime_loads_a_version_3_model_and_decides_for_every_service(tiny_model):
    from flexascale.rl.policy_runtime import PolicyRuntime

    path, model = tiny_model
    rt = PolicyRuntime(path)
    assert rt.graph and rt.observation_version == 3 and rt.action_deltas == list(ACTION_DELTAS)
    feats = {s: np.zeros(fv.F, dtype=np.float32) for s in ("b", "a", "c")}
    out = rt.predict_graph(feats, [("a", "b"), ("b", "c")])
    assert out.mode == "ppo_graph" and len(out.actions) == 3
    assert out.windows[1] == ["b", "a", "c"]
    expected, _ = model.predict(fv.pack(feats, ["a", "b", "c"], [("a", "b"), ("b", "c")], N_MAX), deterministic=True)
    assert out.actions == [int(x) for x in expected[:3]]
    assert all(0 < c <= 1 for c in out.confidences)
    assert rt.info()["observation_dim"] == fv.obs_dim(N_MAX)


# ---------------------------------------------------------------- operator wiring


class _Metrics:
    def __init__(self, values):
        self.values = values

    def collect(self, namespace, deployments, cpu_req=None, mem_cap=None):
        return {d: WorkloadMetrics(deployment=d, **self.values[d]) for d in deployments}


def _operator(tmp_path, runtime=None, **pol):
    c = FakeCluster("demo")
    c.add(deployment("api", replicas=1, cpu_lim="500m"), deployment("worker", replicas=3, cpu_lim="500m"))
    c.add(hpa("api-hpa", "api", 1, 6), kind="hpa")
    p = AppPolicy(name="demo", namespace="demo", mode="live", cooldown_seconds=0, scale_down_cooldown_seconds=0,
                  poll_interval_seconds=1, lease_seconds=10, max_step=3, topology=[("api", "worker")], **pol)
    m = _Metrics({"api": {"cpu_pct": 900.0, "cpu_cores": 0.9, "memory_pct": 30.0, "request_rate": 20.0, "latency_mean_ms": 50.0},
                  "worker": {"cpu_pct": 10.0, "cpu_cores": 0.03, "memory_pct": 30.0, "request_rate": 5.0, "latency_mean_ms": 5.0}})
    op = AppOperator(p, kube=c.kube(), metrics=m, runtime=runtime, decision_log=str(tmp_path / "d.jsonl"),
                     status_file=str(tmp_path / "s.json"), identity="me", load_model=runtime is not None)
    return op, c


def test_rule_arm_runs_live_without_a_model_and_matches_the_twin_rule(tmp_path):
    op, c = _operator(tmp_path, controller_rule={"type": "limit_target", "target": 0.6, "down": 0.3})
    assert op.runtime is None and op.start()["result"] == "lease_acquired"
    res = op.step()
    by = {d["service"]: d for d in res.decisions}
    # api: 0.9 cores / (0.6 x 0.5) = 3 replicas -> +2; worker: 0.03 cores on 2 pods stays < 0.3 of limit -> -1
    assert by["api"]["policy"]["mode"] == "rule_limit_target" and by["api"]["proposed_replicas"] == 3
    assert by["worker"]["proposed_replicas"] == 2 and by["worker"]["applied"]
    assert c.deployments["api"]["spec"]["replicas"] == 3
    op.shutdown()
    assert c.hpas["api-hpa"]["spec"]["minReplicas"] == 1


def test_operator_feeds_version_3_features_to_a_graph_runtime(tmp_path, tiny_model):
    from flexascale.rl.policy_runtime import PolicyRuntime

    path, _ = tiny_model
    op, _ = _operator(tmp_path, runtime=PolicyRuntime(path), confidence_threshold=0.0, deactivation_threshold=0.0)
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["policy"]["mode"] == "ppo_graph"
    assert api["policy_input"][0] == pytest.approx(1.8, abs=1e-3)   # 0.9 cores on 1 pod / 0.5 limit
    assert len(api["policy_input"]) == fv.F
    op.shutdown()


def test_invalid_controller_rule_is_rejected():
    p = AppPolicy(name="demo", namespace="demo", controller_rule={"type": "limit_target", "target": 0.3, "down": 0.5})
    assert any("controller_rule" in e for e in p.validate())


# ---------------------------------------------------------------- twin


def _tiny_app(serial=False):
    s = [ServiceSpec("gw", 0.002, 0.005, 20.0), ServiceSpec("work", 0.02, 0.005, 50.0, serial=serial)]
    return AppSpec("tiny", s, [("gw", "work")], fanout={"gw->work": 1.0}, entry="gw")


def _flat(rate_gw, rate_work, ticks=40):
    return Workload("flat", rates=np.tile([rate_gw, rate_work], (ticks, 1)).astype(float), e2e_rps=np.full(ticks, rate_gw),
                    users=np.full(ticks, 10.0))


def test_twin_is_deterministic_and_queues_only_above_the_limit():
    app = _tiny_app()
    light = simulate(app, _flat(10, 10), NativeHPA(10_000, 60), seed=1)      # 0.2 cores of work: below the 0.5 limit
    again = simulate(app, _flat(10, 10), NativeHPA(10_000, 60), seed=1)
    assert light["p95_ms"] == again["p95_ms"] and light["replica_hours"] == again["replica_hours"]
    heavy = simulate(app, _flat(10, 40), NativeHPA(10_000, 60), seed=1)      # 0.8 cores on one 0.5-core pod
    lat_w = np.array(heavy["sim"].log["lat"])[:, 1]
    assert lat_w[-1] > 5 * lat_w[0] and np.array(light["sim"].log["lat"])[-1, 1] < 1.5 * 50 + 50


def test_hpa_scales_on_cpu_relative_to_the_request_with_a_lagged_metric():
    app = _tiny_app()
    out = simulate(app, _flat(10, 40, ticks=60), NativeHPA(70, 300), seed=0)
    d = np.array(out["sim"].log["desired"])[:, 1]
    assert d[0] == 1 and d.max() >= 5             # 0.8 cores against 70m per pod
    assert np.argmax(d > 1) >= 3                   # metrics-server needs time to see the load


def test_twin_reproduces_live_native_hpa_replica_hours():
    """Regression on the fitted twin (scripts/analysis/validate_twin.py): within 10% of the live means."""
    live = {"steady_browsing": 1.462, "checkout_heavy": 1.904, "payment_degradation": 1.575, "flash_sale": 1.933,
            "gradual_ramp": 1.405, "traffic_drop": 1.572}       # HPA-default means, 2026-10-26 (reports/experiments)
    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    for sc in EVALUATION_SCENARIOS:
        rh = np.mean([simulate(app, build(app, cal, sc), NativeHPA(70, 300), seed=k)["replica_hours"] for k in range(3)])
        assert abs(rh - live[sc]) / live[sc] < 0.10, (sc, rh)


def test_random_apps_are_valid_dags_with_spawn_driven_serial_services():
    for k in range(5):
        rng = np.random.default_rng(k)
        app, cal = random_app(rng)
        wl = random_workload(app, cal, rng)
        names = app.names
        assert all(names.index(u) < names.index(v) for u, v in app.edges)
        assert wl.rates.shape == (wl.ticks, len(names)) and np.isfinite(wl.rates).all()
        out = simulate(app, wl, NativeHPA(70, 60), seed=k)
        assert np.isfinite(out["p95_ms"])


# ---------------------------------------------------------------- environment


def test_env_reward_matches_post_hoc_accounting_and_guards_apply():
    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    wl = build(app, cal, "flash_sale")
    env = TwinEnv(app, cal, workloads=[wl], seed=0)
    env.reset(seed=0)
    total, done, comps = 0.0, False, []
    up = np.full(N_MAX, ACTION_DELTAS.index(3))
    while not done:
        _, r, done, _, info = env.step(up)          # always ask for +3: guards must limit it
        total += r
        comps.append(info["reward_components"])
    d = np.array(env.sim.log["desired"])
    assert d.max() <= 10 and (np.diff(d, axis=0) <= 3).all()      # max_step 3, bounds 1..10
    assert total == pytest.approx(episode_reward(env.sim, RewardConfig()), rel=1e-6)
    assert comps[-1]["replicas_above_min"] > 0 and all(c["scaling_events"] >= 0 for c in comps)


def test_limit_target_rule_in_the_twin_is_lean_at_low_load():
    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    out = simulate(app, build(app, cal, "steady_browsing"), OperatorLoop(limit_target_policy(0.6, 0.3), V7_GUARDS), seed=0)
    assert out["avg_replicas"] < 16.5
