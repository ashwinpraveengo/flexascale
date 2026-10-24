"""v4 policy pipeline: dependency-aware simulator, unit-free features, live input construction."""

import json

import numpy as np
import pytest

from flexascale.config.app_policy import AppPolicy, ServiceBounds
from flexascale.config.env_config import EnvConfig
from flexascale.rl.policy_runtime import PolicyOutput, neighborhood_order
from flexascale.rl.policy_runtime import V2_FIELDS
from flexascale.simulator.dependency_env import FEATURE_HIGH, FEATURE_NAMES, FlexaScaleEnvV2, v2_features

from tests.test_policy_and_operator import FakeRuntime, make_operator


def env(split="train", **kw):
    cfg = dict(dataset_path="data/processed/alibaba_service_state.csv", split=split, split_method="service",
               service_sampling="random", demand_model="normalized", randomize_initial_replicas=True,
               max_replicas=10, peak_replicas_low=1, peak_replicas_high=4,
               reward_weights={"slo": 1.0, "efficiency": 0.3, "stability": 0.1, "cost": 1.0})
    cfg.update(kw)
    return FlexaScaleEnvV2(EnvConfig(**cfg))


def rollout(e, policy, seeds):
    total = []
    for s in seeds:
        obs, info = e.reset(seed=s)
        rs = []
        while True:
            obs, r, term, _, info = e.step(policy(obs, info))
            if term:
                break
            assert e.observation_space.contains(obs)
            rs.append(r)
        total.append(np.mean(rs))
    return float(np.mean(total))


def test_v2_features_are_unit_free_and_clipped():
    f = v2_features(cpu_pct=250.0, memory_pct=40.0, replicas=4, max_replicas=10, rps_trend=9.0,
                    latency_ms=500.0, slo_ms=250.0)
    assert f.tolist() == pytest.approx([1.0, 0.4, 0.4, 3.0, 2.0])
    idle = v2_features(0.0, 20.0, 1, 10, 1.0, 0.0, 250.0)
    assert idle[4] == 0.0 and idle[3] == 1.0
    assert v2_features(10.0, 10.0, 1, 10, float("nan"), 50.0, 0.0)[3:].tolist() == [0.0, 0.0]


def test_env_v2_shapes_bounds_and_determinism():
    e = env()
    o1, i1 = e.reset(seed=7)
    o2, i2 = e.reset(seed=7)
    assert o1.shape == (20,) and np.array_equal(o1, o2)
    assert i1["service_ids"] == i2["service_ids"]
    assert e.episode_length == 30  # service split keeps the full 30-minute trace
    assert (o1.reshape(4, 5) <= FEATURE_HIGH + 1e-6).all()


def test_env_v2_splits_use_disjoint_services():
    pools = [set(env(s)._sampling_pool) for s in ("train", "val", "test")]
    assert not (pools[0] & pools[1]) and not (pools[0] & pools[2]) and not (pools[1] & pools[2])


def test_env_v2_reward_does_not_favour_blanket_scale_up():
    """The defect that made v2/v3 always scale up: here an HPA-like rule beats it."""
    e = env()
    hpa = lambda o, i: [2 if c > 77 else (0 if c < 63 else 1) for c in i["raw"]["cpu_pct"]]
    up = lambda o, i: [2] * 4
    seeds = range(30)
    assert rollout(e, hpa, seeds) > rollout(e, up, seeds)


def test_env_v2_replicas_cannot_fix_external_latency():
    e = env(bottleneck_probability=1.0, traffic_events=False)
    e.reset(seed=3)
    e._external[:] = 5.0
    e._coupling[:] = 0.0
    for sid in e._all_service_ids:
        e._simulated_replicas[sid] = 10
    raw = e._simulate()
    floor = e._external * e._s0[e._step_idx] * raw["bottleneck_factor"]
    assert (raw["latency_ms"] >= floor).all()


def test_neighborhood_order_callees_first():
    edges = [("gw", "orders"), ("orders", "db-api"), ("cart", "orders")]
    svcs = ["cart", "db-api", "gw", "orders"]
    assert neighborhood_order("orders", svcs, edges, callees_first=True) == ["orders", "db-api", "cart", "gw"]
    assert neighborhood_order("orders", svcs, edges) == ["orders", "cart", "db-api", "gw"]


class V2Runtime(FakeRuntime):
    observation_version = 2
    max_replicas = 10

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seen = []

    def predict(self, features, edges=()):
        self.seen.append({k: v.copy() for k, v in features.items()})
        return super().predict(features, edges)


def test_operator_builds_v2_inputs_with_per_service_slo(tmp_path):
    op, _ = make_operator(
        tmp_path,
        metrics={"api": {"cpu_pct": 80.0, "memory_pct": 40.0, "latency_mean_ms": 300.0, "request_rate": 5.0},
                 "worker": {"cpu_pct": 50.0, "memory_pct": 20.0, "latency_mean_ms": 50.0, "request_rate": 2.0}},
        slo_latency_ms=200.0, services={"worker": ServiceBounds(slo_latency_ms=100.0)},
    )
    op.runtime = V2Runtime()
    op.start()
    res = op.step()
    seen = op.runtime.seen[0]
    assert seen["api"].tolist() == pytest.approx([0.8, 0.4, 0.2, 1.0, 1.5])
    assert seen["worker"].tolist() == pytest.approx([0.5, 0.2, 0.1, 1.0, 0.5])
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["policy_input"] == pytest.approx([0.8, 0.4, 0.2, 1.0, 1.5])
    assert api["features"]["cpu_pct"] == 80.0  # raw telemetry is still logged


def test_rps_trend_uses_one_minute_lookback(tmp_path):
    op, _ = make_operator(tmp_path)
    assert op._rps_trend("a", 10.0, 0.0) == 1.0          # no history yet
    assert op._rps_trend("a", 20.0, 30.0) == 1.0         # history younger than the lookback
    assert op._rps_trend("a", 30.0, 60.0) == pytest.approx(3.0)  # 30 / 10 one minute earlier
    assert op._rps_trend("a", 30.0, 90.0) == pytest.approx(1.5)  # 30 / 20
    assert op._rps_trend("b", 0.0, 0.0) == 1.0
    assert op._rps_trend("b", 4.0, 60.0) == 3.0          # traffic appeared from zero
    assert op._rps_trend("c", None, 0.0) == 1.0


def test_v1_runtime_still_gets_raw_features(tmp_path):
    op, _ = make_operator(tmp_path)
    rt = V2Runtime()
    rt.observation_version = 1
    op.runtime = rt
    op.start()
    op.step()
    assert rt.seen[0]["api"][0] == 80.0


def test_slo_for_override():
    p = AppPolicy(name="x", namespace="x", slo_latency_ms=250.0, services={"a": ServiceBounds(slo_latency_ms=900.0)})
    assert p.slo_for("a") == 900.0 and p.slo_for("b") == 250.0


@pytest.fixture(scope="module")
def v2_model(tmp_path_factory):
    from stable_baselines3 import PPO
    from flexascale.rl.gnn_encoder import GNNExtractor

    m = PPO("MlpPolicy", env(), n_steps=8, batch_size=8,
            policy_kwargs=dict(features_extractor_class=GNNExtractor, features_extractor_kwargs=dict(features_dim=16, hidden_dim=16)))
    d = tmp_path_factory.mktemp("v2model")
    m.save(str(d / "m.zip"))
    return d


def test_runtime_infers_v2_without_card_and_pads_with_v2_idle(v2_model):
    from flexascale.rl.policy_runtime import PolicyRuntime

    rt = PolicyRuntime(v2_model / "m.zip")
    assert rt.observation_version == 2 and rt.callees_first
    assert rt.card is None and rt.info()["observation_fields"] == list(FEATURE_NAMES)
    assert V2_FIELDS == FEATURE_NAMES
    out = rt.predict({"a": v2_features(50, 20, 2, 10, 1, 100, 200), "b": v2_features(10, 20, 1, 10, 1, 0, 200)},
                     [("a", "b")])
    assert out.mode == "ppo_neighborhood" and out.windows[0] == ["a", "b"]


def test_runtime_rejects_card_that_contradicts_model(v2_model):
    from flexascale.rl.policy_runtime import PolicyRuntime

    (v2_model / "model_card.json").write_text(json.dumps({"observation": {"version": 1}}))
    try:
        with pytest.raises(ValueError, match="observation version"):
            PolicyRuntime(v2_model / "m.zip")
    finally:
        (v2_model / "model_card.json").unlink()


def test_scale_up_cooldown_spaces_out_scale_ups(tmp_path):
    op, c = make_operator(tmp_path, mode="live", action=2, confidence=0.9, scale_up_cooldown_seconds=30)
    op.start()
    first = {d["service"]: d for d in op.step().decisions}
    assert first["api"]["applied"] is True
    second = {d["service"]: d for d in op.step().decisions}
    assert second["api"]["applied"] is False and "scale_up_cooldown" in second["api"]["safety_reasons"]
    op._last_scale_up = {k: v - 31 for k, v in op._last_scale_up.items()}
    third = {d["service"]: d for d in op.step().decisions}
    assert third["api"]["applied"] is True
    op.shutdown()


def test_focal_control_scores_slot0_and_drives_background():
    e = env(control="focal", background_epsilon=0.0)
    e.reset(seed=5)
    before = dict(e._simulated_replicas)
    cpu = e._simulate()["cpu_pct"]
    _, r, _, _, info = e.step([1, 0, 0, 0])  # heads 1-3 must be ignored
    sids = e._all_service_ids
    assert e._simulated_replicas[sids[0]] == before[sids[0]]
    for sid, c in zip(sids[1:], cpu[1:]):
        expect = 1 if c > 77 else (-1 if c < 63 else 0)
        assert e._simulated_replicas[sid] == max(1, min(10, before[sid] + expect))
    assert "focal_violation" in info


def test_runtime_never_uses_direct_mode_for_focal_models(v2_model):
    from flexascale.rl.policy_runtime import PolicyRuntime

    (v2_model / "model_card.json").write_text(json.dumps({"observation": {"version": 2, "decision_slot": 0}}))
    try:
        rt = PolicyRuntime(v2_model / "m.zip")
        f = {s: v2_features(50, 20, 2, 10, 1, 100, 200) for s in "abcd"}
        assert rt.predict(f, [("a", "b"), ("b", "c"), ("c", "d")]).mode == "ppo_neighborhood"
    finally:
        (v2_model / "model_card.json").unlink()
