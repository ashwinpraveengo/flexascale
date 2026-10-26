"""v6: control-loop simulator, native-HPA algorithm, delta actions in the operator, lab data reset."""

import json

import numpy as np
import pytest

from flexascale.config.env_config import EnvConfig
from flexascale.rl.imitation import ratio_teacher
from flexascale.simulator.control_env import FlexaScaleEnvV3, hpa_recommendation
from flexascale.operator.app_operator import action_label

from tests.test_policy_and_operator import FakeRuntime, make_operator

CFG = dict(demand_model="normalized", control="focal", service_sampling="random", split="val", split_method="service",
           max_replicas=10, randomize_initial_replicas=True, peak_replicas_low=1, peak_replicas_high=4,
           reward_weights={"slo": 1.0, "efficiency": 0.3, "stability": 0.1, "cost": 1.0})


@pytest.fixture(scope="module")
def env():
    return FlexaScaleEnvV3(EnvConfig(**CFG))


def test_hpa_recommendation_matches_kubernetes_formula():
    cfg = EnvConfig(**CFG)
    assert hpa_recommendation(2, 140.0, cfg) == 4          # ceil(2 x 140 / 70)
    assert hpa_recommendation(4, 74.0, cfg) == 4           # inside the 10% tolerance
    assert hpa_recommendation(2, 700.0, cfg) == 6          # scale-up limit max(2x, +4)
    assert hpa_recommendation(5, 10.0, cfg) == 1           # ceil(5 x 10 / 70)


def test_episode_has_15_second_decisions_and_delta_actions(env):
    obs, _ = env.reset(seed=1)
    assert env.action_space.nvec.tolist() == [6] * 4
    assert obs.shape == (20,)
    hold = int(np.where(env.deltas == 0)[0][0])
    steps = 0
    while True:
        obs, r, term, _, info = env.step([hold] * 4)
        if term:
            break
        steps += 1
    assert steps == env.episode_length - 1 == 119


def test_new_replicas_start_after_a_delay():
    env = FlexaScaleEnvV3(EnvConfig(**CFG, startup_delay_steps=2))
    env.reset(seed=3)
    env._desired[0] = 2
    env._pending[0] = []
    env._last_up[0] = -100
    up3 = int(np.where(env.deltas == 3)[0][0])
    hold = int(np.where(env.deltas == 0)[0][0])
    _, _, _, _, info = env.step([up3, hold, hold, hold])
    assert env._desired[0] == 5
    assert info["guard"] == "accepted" and info["ready"][0] == 2   # the three new pods are still starting
    for _ in range(3):
        _, _, _, _, info = env.step([hold] * 4)
    assert info["ready"][0] == env._desired[0]


def test_guards_match_the_operator(env):
    env.reset(seed=4)
    raw = env._simulate()
    env._desired[0] = 4
    env._pending[0] = [(env._k + 5, 1)]                     # one replica still starting
    assert env.guarded_target(0, +2, raw) == (4, "scale_up_waiting_for_readiness")
    env._pending[0] = []
    env._last_up[0] = env._k
    assert env.guarded_target(0, +2, raw)[1] == "scale_up_cooldown"
    env._last_down[0] = -100
    raw = dict(raw, cpu_pct=np.array([10.0] * 4), latency_ms=np.zeros(4))
    assert env.guarded_target(0, -2, raw) == (2, "accepted")  # at most max_scale_down_step down
    raw = dict(raw, cpu_pct=np.array([90.0] * 4))
    assert env.guarded_target(0, -1, raw) == (4, "scale_down_blocked_cpu")


def test_hpa_controller_keeps_replicas_through_stabilisation(env):
    obs, _ = env.reset(seed=5, options={"slot0_controller": "hpa"})
    env._desired[0] = 6
    env._recs[0].clear()
    env._recs[0].extend([6] * 5)
    env._cpu_hist[0].clear()
    env._cpu_hist[0].extend([5.0] * 4)
    env._raw = env._simulate()
    env.step([0, 2, 2, 2])
    assert env._desired[0] == 6                            # recent recommendation of 6 holds the scale-down
    env.reset(seed=5, options={"slot0_controller": "agent"})


def test_ratio_teacher_follows_hpa_and_uses_nearest_delta():
    t = ratio_teacher((-2, -1, 0, 1, 2, 3), max_replicas=10)
    obs = np.array([0.98, 0.3, 0.2, 1.0, 0.5] * 4, dtype=np.float32)  # 2 replicas at 98% -> 3 (+1)
    assert t(obs)[0] == 3
    obs[0] = 1.0
    obs[2] = 0.5                                             # 5 replicas at 100% -> ceil(7.14) = 8 -> +3
    assert t(obs)[0] == 5
    obs[0] = 0.05                                            # 5 replicas at 5% -> 1 -> clipped to -2
    assert t(obs)[0] == 0


def test_action_labels():
    assert action_label(0) == "hold"
    assert action_label(1) == "scale_up" and action_label(-1) == "scale_down"
    assert action_label(3) == "scale_up_3" and action_label(-2) == "scale_down_2"


class DeltaRuntime(FakeRuntime):
    action_deltas = [-2, -1, 0, 1, 2, 3]


def test_operator_applies_model_deltas_within_policy_limits(tmp_path):
    op, c = make_operator(tmp_path, mode="live", action=5, max_step=2)   # model asks +3, policy allows +2
    op.runtime = DeltaRuntime(5, 0.9)
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert api["policy"]["delta"] == 3 and api["policy"]["action_label"] == "scale_up_3"
    assert c.deployments["api"]["spec"]["replicas"] == 4                  # 2 + min(3, max_step 2)
    op.shutdown()


def test_operator_scale_down_limited_by_max_scale_down_step(tmp_path):
    op, c = make_operator(tmp_path, mode="live", action=0, max_scale_down_step=1,
                          metrics={"api": {"cpu_pct": 10.0, "memory_pct": 40.0}, "worker": {"cpu_pct": 10.0, "memory_pct": 40.0}})
    op.runtime = DeltaRuntime(0, 0.9)
    c.deployments["api"]["spec"]["replicas"] = 4
    c.deployments["api"]["status"]["replicas"] = c.deployments["api"]["status"]["readyReplicas"] = 4
    op.start()
    op.step()
    assert c.deployments["api"]["spec"]["replicas"] == 3                  # model asks -2, policy allows -1
    op.shutdown()


def test_multi_replica_step_is_clipped_to_the_budget(tmp_path):
    op, c = make_operator(tmp_path, mode="live", action=5, max_step=3, max_total_replicas=5)
    op.runtime = DeltaRuntime({"api": 5, "worker": 2}, 0.9)                # api +3, worker hold
    op.start()
    res = op.step()
    api = next(d for d in res.decisions if d["service"] == "api")
    assert "scale_up_clipped_replica_budget" in api["safety_reasons"]
    assert c.deployments["api"]["spec"]["replicas"] == 4                  # budget 5 - worker 1 = 4
    op.shutdown()


def test_lab_app_reset_requests_are_loaded(tmp_path):
    from flexascale.lab.experiments import LabConfig

    p = tmp_path / "lab.yaml"
    p.write_text("apps:\n  shop:\n    policy: x.yaml\n    reset_requests:\n"
                 "      - {method: PUT, path: '/api/inventory/{id}', ids: [1, 2], json: {stock_quantity: 5}}\n")
    app = LabConfig.load(p).apps["shop"]
    assert app.reset_requests[0]["ids"] == [1, 2] and app.reset_requests[0]["method"] == "PUT"


def test_bundled_shop_config_resets_data_before_runs():
    from flexascale.lab.experiments import LabConfig

    app = LabConfig.load("config/lab.yaml").apps["shopping"]
    paths = [r["path"] for r in app.reset_requests]
    assert "/api/inventory/{id}" in paths and "/api/cart/{id}/items" in paths
