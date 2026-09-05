"""
Comprehensive tests for the FlexaScale Gymnasium environment.

Covers all 15 required validation points:
    1.  Environment can be imported
    2.  Environment can be instantiated (cluster & single service)
    3.  reset() works
    4.  reset() returns (obs, info)
    5.  Observation belongs to observation_space
    6.  Valid actions belong to action_space
    7.  step() works (supports multi-action array and scalar broadcasting)
    8.  step() returns (obs, reward, terminated, truncated, info)
    9.  Observation remains valid after step()
    10. Episode eventually terminates
    11. reset() after episode completion works
    12. No NaN/Inf observations
    13. Reward is finite
    14. Different valid actions produce meaningful simulator behavior
    15. Seeded runs are deterministic
"""

import numpy as np
import pytest
from gymnasium.spaces import Box, Discrete, MultiDiscrete

from flexascale.config.env_config import EnvConfig
from flexascale.data.schema import VECTOR_DIM, VECTOR_FIELDS
from flexascale.simulator.flexascale_env import (
    ACTION_MAINTAIN,
    ACTION_SCALE_DOWN,
    ACTION_SCALE_UP,
    NUM_ACTIONS,
    FlexaScaleEnv,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config() -> EnvConfig:
    """Default config pointing to the real processed dataset."""
    return EnvConfig()


@pytest.fixture
def env(config):
    """Cluster environment instance (4 services)."""
    e = FlexaScaleEnv(config=config)
    yield e
    e.close()


@pytest.fixture
def single_env():
    """Single-service environment instance."""
    cfg = EnvConfig(
        service_id="002251d4123496684687c2acad43bdef9419a5e4fc01a65d2c558af92a5ad649"
    )
    e = FlexaScaleEnv(config=cfg)
    yield e
    e.close()


# ---------------------------------------------------------------------------
# 1. Import
# ---------------------------------------------------------------------------

class TestImport:

    def test_import_environment(self):
        from flexascale.simulator.flexascale_env import FlexaScaleEnv
        assert FlexaScaleEnv is not None

    def test_import_from_package(self):
        from flexascale.simulator import FlexaScaleEnv
        assert FlexaScaleEnv is not None

    def test_import_config(self):
        from flexascale.config.env_config import EnvConfig
        assert EnvConfig is not None

    def test_import_action_constants(self):
        assert ACTION_SCALE_DOWN == 0
        assert ACTION_MAINTAIN == 1
        assert ACTION_SCALE_UP == 2
        assert NUM_ACTIONS == 3


# ---------------------------------------------------------------------------
# 2. Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:

    def test_default_config(self, env):
        assert env is not None
        assert env.num_services == 4

    def test_custom_config(self):
        cfg = EnvConfig(latency_target_ms=50.0, max_replicas=20)
        e = FlexaScaleEnv(config=cfg)
        assert e.config.latency_target_ms == 50.0
        assert e.config.max_replicas == 20
        e.close()

    def test_dataset_loaded(self, env):
        assert env.num_services > 0
        assert env.num_timestamps > 0


# ---------------------------------------------------------------------------
# 3 & 4. reset()
# ---------------------------------------------------------------------------

class TestReset:

    def test_reset_returns_tuple(self, env):
        result = env.reset(seed=42)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_reset_obs_shape(self, env):
        obs, _ = env.reset(seed=42)
        assert obs.shape == (env.num_services * VECTOR_DIM,)

    def test_reset_single_service_obs_shape(self, single_env):
        obs, _ = single_env.reset(seed=42)
        assert obs.shape == (VECTOR_DIM,)

    def test_reset_obs_dtype(self, env):
        obs, _ = env.reset(seed=42)
        assert obs.dtype == np.float32

    def test_reset_info_dict(self, env):
        _, info = env.reset(seed=42)
        assert isinstance(info, dict)
        assert "service_id" in info
        assert "timestep" in info
        assert "simulated_replicas" in info
        assert "slo_violated" in info

    def test_reset_with_fixed_service(self, single_env):
        _, info = single_env.reset()
        assert info["service_id"] == single_env.config.service_id


# ---------------------------------------------------------------------------
# 5. Observation ∈ observation_space
# ---------------------------------------------------------------------------

class TestObservationSpace:

    def test_obs_in_space_after_reset(self, env):
        obs, _ = env.reset(seed=42)
        assert env.observation_space.contains(obs)

    def test_obs_in_space_after_step(self, env):
        env.reset(seed=42)
        for _ in range(5):
            action = env.action_space.sample()
            obs, _, terminated, _, _ = env.step(action)
            assert env.observation_space.contains(obs)
            if terminated:
                break

    def test_observation_space_shape(self, env):
        assert env.observation_space.shape == (env.num_services * VECTOR_DIM,)

    def test_single_service_observation_space_shape(self, single_env):
        assert single_env.observation_space.shape == (VECTOR_DIM,)


# ---------------------------------------------------------------------------
# 6. Action space
# ---------------------------------------------------------------------------

class TestActionSpace:

    def test_action_space_type(self, env):
        assert isinstance(env.action_space, MultiDiscrete)

    def test_single_service_action_space_type(self, single_env):
        assert isinstance(single_env.action_space, Discrete)

    def test_valid_actions(self, env):
        sample = env.action_space.sample()
        assert env.action_space.contains(sample)

    def test_scalar_action_broadcast_in_step(self, env):
        env.reset(seed=42)
        # Passing integer action should broadcast across all services without error
        obs, reward, terminated, truncated, info = env.step(ACTION_MAINTAIN)
        assert isinstance(reward, float)


# ---------------------------------------------------------------------------
# 7 & 8. step()
# ---------------------------------------------------------------------------

class TestStep:

    def test_step_returns_5tuple(self, env):
        env.reset(seed=42)
        result = env.step(ACTION_MAINTAIN)
        assert isinstance(result, tuple)
        assert len(result) == 5

    def test_step_types(self, env):
        env.reset(seed=42)
        obs, reward, terminated, truncated, info = env.step(ACTION_MAINTAIN)
        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_step_info_contents(self, env):
        env.reset(seed=42)
        _, _, _, _, info = env.step(ACTION_MAINTAIN)
        assert "simulated_replicas" in info
        assert "slo_violated" in info
        assert "reward_components" in info


# ---------------------------------------------------------------------------
# 9. Observation valid after step
# ---------------------------------------------------------------------------

class TestObsValidAfterStep:

    def test_obs_shape_after_step(self, env):
        env.reset(seed=42)
        obs, _, _, _, _ = env.step(ACTION_SCALE_UP)
        assert obs.shape == (env.num_services * VECTOR_DIM,)
        assert obs.dtype == np.float32

    def test_no_nan_or_inf_observations(self, env):
        env.reset(seed=42)
        for _ in range(10):
            action = env.action_space.sample()
            obs, reward, terminated, _, _ = env.step(action)
            assert not np.isnan(obs).any()
            assert not np.isinf(obs).any()
            assert not np.isnan(reward)
            assert not np.isinf(reward)
            if terminated:
                break


# ---------------------------------------------------------------------------
# 10 & 11. Episode termination and reset
# ---------------------------------------------------------------------------

class TestEpisodeTermination:

    def test_episode_terminates(self, env):
        env.reset(seed=42)
        steps = 0
        terminated = False
        while not terminated and steps < 2000:
            _, _, terminated, _, _ = env.step(ACTION_MAINTAIN)
            steps += 1
        assert terminated is True

    def test_reset_after_termination(self, env):
        env.reset(seed=42)
        while True:
            _, _, terminated, _, _ = env.step(ACTION_MAINTAIN)
            if terminated:
                break
        obs, info = env.reset(seed=99)
        assert obs.shape == (env.num_services * VECTOR_DIM,)
        assert info["timestep"] == 0


# ---------------------------------------------------------------------------
# 14. Action Effects
# ---------------------------------------------------------------------------

class TestActionEffects:

    def test_scale_up_increases_replicas(self, single_env):
        single_env.reset(seed=42)
        _, info_before = single_env.reset(seed=42)
        reps_before = info_before["simulated_replicas"]

        _, _, _, _, info_after = single_env.step(ACTION_SCALE_UP)
        reps_after = info_after["simulated_replicas"]

        if reps_before < single_env.config.max_replicas:
            assert reps_after == reps_before + 1

    def test_scale_down_decreases_replicas(self, single_env):
        single_env.reset(seed=42)
        # Set replicas higher then step down
        single_env._simulated_replicas[single_env._all_service_ids[0]] = 5
        _, _, _, _, info_after = single_env.step(ACTION_SCALE_DOWN)
        reps_after = info_after["simulated_replicas"]
        assert reps_after == 4

    def test_maintain_keeps_replicas(self, single_env):
        single_env.reset(seed=42)
        single_env._simulated_replicas[single_env._all_service_ids[0]] = 5
        _, _, _, _, info_after = single_env.step(ACTION_MAINTAIN)
        assert info_after["simulated_replicas"] == 5


# ---------------------------------------------------------------------------
# 15. Seeded Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_seeded_reset_same_state(self, env):
        obs1, info1 = env.reset(seed=42)
        obs2, info2 = env.reset(seed=42)
        np.testing.assert_array_equal(obs1, obs2)
        assert info1["service_id"] == info2["service_id"]

    def test_seeded_episode_deterministic(self, env):
        def run_trajectory(seed):
            obs, _ = env.reset(seed=seed)
            trajectory = [obs.copy()]
            rewards = []
            for _ in range(10):
                obs, rew, terminated, _, _ = env.step(ACTION_MAINTAIN)
                trajectory.append(obs.copy())
                rewards.append(rew)
                if terminated:
                    break
            return trajectory, rewards

        traj1, rew1 = run_trajectory(42)
        traj2, rew2 = run_trajectory(42)

        for t1, t2 in zip(traj1, traj2):
            np.testing.assert_array_almost_equal(t1, t2)
        np.testing.assert_almost_equal(rew1, rew2)


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------

class TestRender:

    def test_render_after_reset(self, env, capsys):
        env.reset(seed=42)
        env.render()
        captured = capsys.readouterr()
        assert "replicas=" in captured.out

    def test_render_before_reset(self, env, capsys):
        env.render()
        captured = capsys.readouterr()
        assert "Not initialised" in captured.out
