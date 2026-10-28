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
    assert np.array(light["sim"].log["lat"])[-1, 1] < 1.5 * 50 + 50
    # queueing, but bounded by the closed loop: at most 10 users' requests (10 x 20 ms of CPU) wait on one 0.5-core pod
    assert lat_w[-1] > 5 * 50 and lat_w.max() <= 50 + 1000 * 10 * 0.02 / 0.5 + 1000 * 0.02 * 19 + 1


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


def test_latency_penalty_is_capped_per_step():
    """POLICY_V7 §4.2 amendment: rare overload episodes must not dominate the gradient."""
    app = _tiny_app()
    env = TwinEnv(app, {}, workloads=[_flat(10, 200, ticks=40)], seed=0)   # far beyond what 10 replicas can serve
    env.reset(seed=0)
    done, seen = False, []
    while not done:
        _, _, done, _, info = env.step(np.full(N_MAX, HOLD_INDEX))
        seen.append(info["reward_components"]["p95_inflation"])
    assert max(seen) <= RewardConfig().p95_inflation_cap + 1e-9


def test_hold_bias_starts_exploration_near_hold():
    from gymnasium import spaces

    from flexascale.rl.graph_policy import PerNodeHead

    head = PerNodeHead(n_max=3, hidden=4, n_actions=len(ACTION_DELTAS), hold_index=HOLD_INDEX, hold_bias=1.5)
    latent = torch.cat([torch.zeros(1, 12), torch.ones(1, 3)], dim=1)
    p = torch.softmax(head(latent).reshape(3, -1), dim=-1)
    assert torch.all(p[:, HOLD_INDEX] > 0.5)


# ---------------------------------------------------------------- focal (per-service credit) design


def test_per_service_rewards_sum_to_the_global_reward_and_blame_the_queueing_service():
    from flexascale.simulator.twin_env import components_from_log, per_service_rewards, reward_v7

    app = _tiny_app()
    env = TwinEnv(app, {}, workloads=[_flat(10, 60, ticks=30)], seed=0)   # "work" overloaded at one replica
    env.reset(seed=0)
    for _ in range(6):
        env.step(np.full(N_MAX, HOLD_INDEX))
    sim, cfg = env.sim, RewardConfig()
    T = len(sim.log["desired"])
    r = per_service_rewards(sim, T - 2, T, env.floor, cfg)
    g = reward_v7(components_from_log(sim, T - 2, T, env.floor), cfg)
    assert r.sum() == pytest.approx(g, rel=1e-9)
    assert r[1] < r[0] <= 0     # the overloaded service carries most of the latency penalty


def test_focal_vec_env_and_runtime_decide_per_service(tmp_path):
    from stable_baselines3 import PPO
    from stable_baselines3.common.policies import ActorCriticPolicy

    from flexascale.rl.graph_policy import GraphFocalExtractor
    from flexascale.rl.policy_runtime import PolicyRuntime
    from flexascale.simulator.twin_env import TwinAgentsVecEnv

    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    venv = TwinAgentsVecEnv(app, cal, n_sims=1, seed=2)
    obs = venv.reset()
    assert obs.shape == (N_MAX, fv.obs_dim(N_MAX) + N_MAX)
    _, rew, done, infos = venv.step(np.full(N_MAX, HOLD_INDEX))
    assert rew.shape == (N_MAX,) and (rew[16:] == 0).all() and not done.any()
    model = PPO(ActorCriticPolicy, venv, n_steps=16, batch_size=64, n_epochs=1, seed=0, device="cpu",
                policy_kwargs={"features_extractor_class": GraphFocalExtractor,
                               "features_extractor_kwargs": {"n_max": N_MAX, "hidden": 16}, "net_arch": {"pi": [16], "vf": [16]}})
    model.learn(32)
    d = tmp_path / "best_model"
    d.mkdir()
    model.save(d / "best_model")
    (d / "model_card.json").write_text(json.dumps({
        "observation": {"version": 3, "n_max": N_MAX, "per_service_fields": list(fv.FEATURES)},
        "action": {"deltas": list(ACTION_DELTAS)}}))
    rt = PolicyRuntime(d / "best_model.zip")
    assert rt.focal and rt.info()["decision"] == "focal"
    feats = {s: np.full(fv.F, 0.1 * i, dtype=np.float32) for i, s in enumerate(["a", "b", "c"])}
    out = rt.predict_graph(feats, [("a", "b")])
    assert len(out.actions) == 3 and all(len(p) == len(ACTION_DELTAS) for p in out.probabilities)
    x = fv.pack(feats, ["a", "b", "c"], [("a", "b")], N_MAX)
    row_b = np.concatenate([x, np.eye(N_MAX, dtype=np.float32)[1]])
    a_b, _ = model.predict(row_b, deterministic=True)
    assert out.actions[1] == int(a_b)


def test_focal_warm_start_imitates_the_rule():
    from stable_baselines3 import PPO
    from stable_baselines3.common.policies import ActorCriticPolicy

    from flexascale.rl.graph_policy import GraphFocalExtractor
    from flexascale.rl.imitation_v7 import collect_focal, warm_start_focal
    from flexascale.simulator.twin_env import TwinAgentsVecEnv

    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    rule = limit_target_policy(0.6, 0.3)
    data = collect_focal(lambda s: TwinEnv(app, cal, seed=s), rule, episodes=2, epsilon=0.0, gamma=0.97, seed=3)
    assert data["obs"].shape[1] == fv.obs_dim(N_MAX) + N_MAX and len(data["labels"]) == len(data["returns"]) == len(data["obs"])
    torch.manual_seed(0)
    model = PPO(ActorCriticPolicy, TwinAgentsVecEnv(app, cal, n_sims=1, seed=4), n_steps=16, batch_size=320, seed=0, device="cpu",
                policy_kwargs={"features_extractor_class": GraphFocalExtractor, "features_extractor_kwargs": {"n_max": N_MAX, "hidden": 64},
                               "net_arch": {"pi": [64], "vf": [64]}})
    info = warm_start_focal(model, lambda s: TwinEnv(app, cal, seed=s), rule, episodes=15, epochs=8, batch_size=512, seed=3)
    assert info["agreement_heldout"] > 0.75 and info["samples"] > 5000


def test_feature_relabelling_matches_the_rule_itself():
    """imitation_v7.limit_target_label (used to augment scale-up examples) must equal limit_target_policy."""
    from flexascale.rl.imitation_v7 import limit_target_label

    rule = limit_target_policy(0.6, 0.3)
    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    checked = 0
    for k in range(3):
        env = TwinEnv(app, cal, seed=k)
        obs, _ = env.reset(seed=k)
        done = False
        while not done:
            want = rule(env.sim, env._last_obs, env.loop)
            x, _, _ = fv.unpack(obs, N_MAX)
            lab = limit_target_label(x[: len(env.app.services)], 0.6, 0.3)
            # same decision wherever the features are not clipped (cpu feature < 2) and readiness is complete
            ok = (x[: len(want), 0] < fv.HIGH[0]) & (x[: len(want), 5] == 1.0)
            assert (np.array(ACTION_DELTAS)[lab][ok] == np.clip(want, -1, 3)[ok]).all()
            checked += int(ok.sum())
            idx = np.abs(np.clip(want, -1, 3)[:, None] - np.array(ACTION_DELTAS)[None, :]).argmin(axis=1)
            obs, _, done, _, _ = env.step(np.concatenate([idx, np.full(N_MAX - len(idx), HOLD_INDEX)]))  # follow the rule
    assert checked > 500


def test_focal_rows_find_the_focal_services_own_features():
    from flexascale.rl.imitation_v7 import _focal_rows, collect_focal

    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    data = collect_focal(lambda s: TwinEnv(app, cal, seed=s), limit_target_policy(0.6, 0.3), episodes=1, epsilon=0.0, gamma=0.97, seed=5)
    cpu_col, rows = _focal_rows(data["obs"])
    for i in range(0, len(data["obs"]), 97):
        x, _, _ = fv.unpack(data["obs"][i, : fv.obs_dim(N_MAX)], N_MAX)
        k = int(data["obs"][i, -N_MAX:].argmax())
        assert cpu_col[i] == k * fv.F and np.array_equal(rows[i], x[k])


def test_augmented_warm_start_learns_the_rules_scale_ups():
    """The rule's own data has almost no +1 labels; rescaled, relabelled copies must teach them."""
    from stable_baselines3 import PPO
    from stable_baselines3.common.policies import ActorCriticPolicy

    from flexascale.rl.graph_policy import GraphFocalExtractor
    from flexascale.rl.imitation_v7 import warm_start_focal
    from flexascale.simulator.twin_env import TwinAgentsVecEnv

    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    torch.manual_seed(0)
    model = PPO(ActorCriticPolicy, TwinAgentsVecEnv(app, cal, n_sims=1, seed=4), n_steps=16, batch_size=320, seed=0, device="cpu",
                policy_kwargs={"features_extractor_class": GraphFocalExtractor, "features_extractor_kwargs": {"n_max": N_MAX, "hidden": 64},
                               "net_arch": {"pi": [64], "vf": [64]}})
    info = warm_start_focal(model, lambda s: TwinEnv(app, cal, seed=s), limit_target_policy(0.6, 0.3), episodes=10, epochs=6,
                            batch_size=512, seed=3, target=0.6, down=0.3)
    print(info)
    rec = info["recall_per_action_augmented_heldout"]
    assert rec.get("1", 0.0) > 0.5 and info["agreement_heldout"] > 0.75


def test_latency_rule_scales_a_low_cpu_service_whose_latency_inflates(tmp_path):
    """POLICY_V8 §2: an event-loop-bound service (low CPU, rising latency) is scaled on latency; CPU rules never would."""
    op, c = _operator(tmp_path, controller_rule={"type": "latency_target", "target": 0.6, "down": 0.3})
    c.add(deployment("cart", replicas=1, cpu_lim="500m"))
    vals = op.metrics.values
    vals["cart"] = {"cpu_pct": 15.0, "cpu_cores": 0.015, "memory_pct": 30.0, "request_rate": 3.0, "latency_mean_ms": 40.0}
    vals["worker"]["latency_mean_ms"] = 5.0
    assert op.start()["result"] == "lease_acquired"
    op.step()                                   # baseline latencies: cart 40 ms, worker 5 ms
    vals["cart"]["latency_mean_ms"] = 200.0     # 5x its own baseline (log2 = 2.3) at 3% of its CPU limit
    by = {d["service"]: d for d in op.step().decisions}
    assert by["cart"]["policy"]["mode"] == "rule_latency_target"
    assert by["cart"]["proposed_replicas"] == 3                      # +2 (4x <= inflation < 8x)
    assert by["worker"]["proposed_replicas"] <= 3                    # worker's latency is at its baseline
    vals["cart"]["latency_mean_ms"] = 41.0                           # back at baseline: CPU and latency allow a scale-down
    c.deployments["cart"]["spec"]["replicas"] = 3
    by = {d["service"]: d for d in op.step().decisions}
    assert by["cart"]["proposed_replicas"] == 2


def test_limit_target_rule_ignores_latency(tmp_path):
    op, c = _operator(tmp_path, controller_rule={"type": "limit_target", "target": 0.6, "down": 0.3})
    c.add(deployment("cart", replicas=1, cpu_lim="500m"))
    op.metrics.values["cart"] = {"cpu_pct": 15.0, "cpu_cores": 0.015, "memory_pct": 30.0, "request_rate": 3.0, "latency_mean_ms": 40.0}
    op.start()
    op.step()
    op.metrics.values["cart"]["latency_mean_ms"] = 200.0
    by = {d["service"]: d for d in op.step().decisions}
    assert by["cart"]["proposed_replicas"] == 1
