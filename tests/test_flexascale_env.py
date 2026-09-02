"""
Comprehensive tests for the FlexaScale Gymnasium environment.

Covers all 15 required validation points:
    1.  Environment can be imported
    2.  Environment can be instantiated
    3.  reset() works
    4.  reset() returns (obs, info)
    5.  Observation belongs to observation_space
    6.  Valid actions belong to action_space
    7.  step() works
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

from flexascale.config.env_config import EnvConfig
from flexascale.data.schema import VECTOR_DIM, VECTOR_FIELDS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config() -> EnvConfig:
    """Default config pointing to the real processed dataset."""
    return EnvConfig()


@pytest.fixture
def env(config):
    """A fresh environment instance, closed after each test."""
    from flexascale.simulator.flexascale_env import FlexaScaleEnv

    env = FlexaScaleEnv(config=config)
    yield env
    env.close()


@pytest.fixture
def seeded_env(config):
    """Environment reset with a fixed seed for determinism tests."""
    from flexascale.simulator.flexascale_env import FlexaScaleEnv

    env = FlexaScaleEnv(config=config)
    env.reset(seed=12345)
    yield env
    env.close()


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
        from flexascale.simulator.flexascale_env import (
            ACTION_SCALE_DOWN,
            ACTION_MAINTAIN,
            ACTION_SCALE_UP,
            NUM_ACTIONS,
        )
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

    def test_custom_config(self):
        from flexascale.simulator.flexascale_env import FlexaScaleEnv

        cfg = EnvConfig(latency_target_ms=50.0, max_replicas=20)
        env = FlexaScaleEnv(config=cfg)
        assert env.config.latency_target_ms == 50.0
        assert env.config.max_replicas == 20
        env.close()

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

    def test_reset_with_fixed_service(self):
        from flexascale.simulator.flexascale_env import FlexaScaleEnv

        cfg = EnvConfig(
            service_id="002251d4123496684687c2acad43bdef"
                       "9419a5e4fc01a65d2c558af92a5ad649"
        )
        env = FlexaScaleEnv(config=cfg)
        _, info = env.reset()
        assert info["service_id"] == cfg.service_id
        env.close()


# ---------------------------------------------------------------------------
# 5. Observation ∈ observation_space
# ---------------------------------------------------------------------------

class TestObservationSpace:

    def test_obs_in_space_after_reset(self, env):
        obs, _ = env.reset(seed=42)
        assert env.observation_space.contains(obs), (
            f"Observation {obs} not in space {env.observation_space}"
        )

    def test_obs_in_space_after_step(self, env):
        env.reset(seed=42)
        for _ in range(5):
            action = env.action_space.sample()
            obs, _, terminated, _, _ = env.step(action)
            assert env.observation_space.contains(obs)
            if terminated:
                break

    def test_observation_space_shape(self, env):
        assert env.observation_space.shape == (VECTOR_DIM,)

    def test_observation_space_dtype(self, env):
        assert env.observation_space.dtype == np.float32


# ---------------------------------------------------------------------------
# 6. Action space
# ---------------------------------------------------------------------------

class TestActionSpace:

    def test_action_space_type(self, env):
        from gymnasium.spaces import Discrete
        assert isinstance(env.action_space, Discrete)

    def test_action_space_n(self, env):
        assert env.action_space.n == 3

    def test_valid_actions(self, env):
        for a in [0, 1, 2]:
            assert env.action_space.contains(a)

    def test_invalid_actions(self, env):
        assert not env.action_space.contains(-1)
        assert not env.action_space.contains(3)


# ---------------------------------------------------------------------------
# 7 & 8. step()
# ---------------------------------------------------------------------------

class TestStep:

    def test_step_returns_5tuple(self, env):
        env.reset(seed=42)
        result = env.step(1)  # maintain
        assert isinstance(result, tuple)
        assert len(result) == 5

    def test_step_types(self, env):
        env.reset(seed=42)
        obs, reward, terminated, truncated, info = env.step(1)
        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_step_info_contents(self, env):
        env.reset(seed=42)
        _, _, _, _, info = env.step(1)
        assert "simulated_replicas" in info
        assert "slo_violated" in info
        assert "reward_components" in info


# ---------------------------------------------------------------------------
# 9. Observation valid after step
# ---------------------------------------------------------------------------

class TestObsValidAfterStep:

    def test_obs_shape_after_step(self, env):
        env.reset(seed=42)
        obs, _, _, _, _ = env.step(2)
        assert obs.shape == (VECTOR_DIM,)
        assert obs.dtype == np.float32


# ---------------------------------------------------------------------------
# 10. Episode eventually terminates
# ---------------------------------------------------------------------------

class TestEpisodeTermination:

    def test_episode_terminates(self, env):
        env.reset(seed=42)
        terminated = False
        steps = 0
        max_steps = 10_000  # safety limit

        while not terminated and steps < max_steps:
            _, _, terminated, _, _ = env.step(1)
            steps += 1

        assert terminated, (
            f"Episode did not terminate after {max_steps} steps"
        )

    def test_episode_length_matches_trace(self, env):
        env.reset(seed=42)
        expected_steps = env.episode_length
        steps = 0

        while True:
            _, _, terminated, _, _ = env.step(1)
            steps += 1
            if terminated:
                break

        assert steps == expected_steps


# ---------------------------------------------------------------------------
# 11. Reset after episode completion
# ---------------------------------------------------------------------------

class TestResetAfterEpisode:

    def test_reset_after_termination(self, env):
        env.reset(seed=42)

        # Run to termination.
        while True:
            _, _, terminated, _, _ = env.step(1)
            if terminated:
                break

        # Reset and run again.
        obs, info = env.reset(seed=99)
        assert obs.shape == (VECTOR_DIM,)
        assert env.observation_space.contains(obs)

        obs2, _, terminated2, _, _ = env.step(1)
        assert obs2.shape == (VECTOR_DIM,)
        assert not terminated2 or env.episode_length <= 2


# ---------------------------------------------------------------------------
# 12. No NaN / Inf
# ---------------------------------------------------------------------------

class TestNoNanInf:

    def test_no_nan_after_reset(self, env):
        obs, _ = env.reset(seed=42)
        assert not np.any(np.isnan(obs)), f"NaN in obs: {obs}"
        assert not np.any(np.isinf(obs)), f"Inf in obs: {obs}"

    def test_no_nan_during_episode(self, env):
        env.reset(seed=42)
        for _ in range(50):
            action = env.action_space.sample()
            obs, _, terminated, _, _ = env.step(action)
            assert not np.any(np.isnan(obs)), f"NaN in obs: {obs}"
            assert not np.any(np.isinf(obs)), f"Inf in obs: {obs}"
            if terminated:
                break


# ---------------------------------------------------------------------------
# 13. Reward is finite
# ---------------------------------------------------------------------------

class TestRewardFinite:

    def test_reward_finite_during_episode(self, env):
        env.reset(seed=42)
        for _ in range(50):
            action = env.action_space.sample()
            _, reward, terminated, _, _ = env.step(action)
            assert np.isfinite(reward), f"Non-finite reward: {reward}"
            if terminated:
                break


# ---------------------------------------------------------------------------
# 14. Different actions produce meaningful behavior
# ---------------------------------------------------------------------------

class TestActionEffects:

    def test_scale_up_increases_replicas(self, env):
        env.reset(seed=42)
        _, info_before = env.reset(seed=42)
        replicas_before = info_before["simulated_replicas"]

        _, _, _, _, info_after = env.step(2)  # scale up
        replicas_after = info_after["simulated_replicas"]

        if replicas_before < env.config.max_replicas:
            assert replicas_after == replicas_before + 1

    def test_scale_down_decreases_replicas(self, env):
        # Use a config that starts with enough replicas.
        env.reset(seed=42)
        _, info_before = env.reset(seed=42)
        replicas_before = info_before["simulated_replicas"]

        _, _, _, _, info_after = env.step(0)  # scale down
        replicas_after = info_after["simulated_replicas"]

        if replicas_before > env.config.min_replicas:
            assert replicas_after == replicas_before - 1

    def test_maintain_keeps_replicas(self, env):
        env.reset(seed=42)
        _, info_before = env.reset(seed=42)
        replicas_before = info_before["simulated_replicas"]

        _, _, _, _, info_after = env.step(1)  # maintain
        replicas_after = info_after["simulated_replicas"]
        assert replicas_after == replicas_before

    def test_different_actions_different_rewards(self, env):
        """Different actions from the same state should generally
        produce different rewards (at least for up vs down)."""
        rewards = {}
        for action in [0, 1, 2]:
            env.reset(seed=42)
            # Take one step to get past initial state.
            env.step(1)
            _, reward, _, _, _ = env.step(action)
            rewards[action] = reward

        # At least two actions should give different rewards.
        unique_rewards = len(set(rewards.values()))
        assert unique_rewards >= 2, (
            f"All actions produced same reward: {rewards}"
        )


# ---------------------------------------------------------------------------
# 15. Seeded determinism
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_seeded_reset_same_service(self, env):
        _, info1 = env.reset(seed=42)
        _, info2 = env.reset(seed=42)
        assert info1["service_id"] == info2["service_id"]

    def test_seeded_reset_same_obs(self, env):
        obs1, _ = env.reset(seed=42)
        obs2, _ = env.reset(seed=42)
        np.testing.assert_array_equal(obs1, obs2)

    def test_seeded_episode_deterministic(self, env):
        def run_episode(seed):
            obs, _ = env.reset(seed=seed)
            trajectory = [obs.copy()]
            rewards = []
            for _ in range(10):
                obs, reward, terminated, _, _ = env.step(1)
                trajectory.append(obs.copy())
                rewards.append(reward)
                if terminated:
                    break
            return trajectory, rewards

        traj1, rew1 = run_episode(42)
        traj2, rew2 = run_episode(42)

        assert len(traj1) == len(traj2)
        for o1, o2 in zip(traj1, traj2):
            np.testing.assert_array_equal(o1, o2)
        assert rew1 == rew2


# ---------------------------------------------------------------------------
# Gymnasium check_env
# ---------------------------------------------------------------------------

class TestGymnasiumCheck:

    def test_check_env_passes(self, env):
        """Run Gymnasium's built-in environment checker."""
        from gymnasium.utils.env_checker import check_env

        # check_env resets and steps internally — just verify no errors.
        try:
            check_env(env.unwrapped, skip_render_check=True)
        except Exception as exc:
            pytest.fail(f"Gymnasium check_env failed: {exc}")


# ---------------------------------------------------------------------------
# EnvConfig
# ---------------------------------------------------------------------------

class TestEnvConfig:

    def test_default_values(self):
        cfg = EnvConfig()
        assert cfg.min_replicas == 1
        assert cfg.max_replicas == 50
        assert cfg.latency_target_ms == 100.0
        assert cfg.cpu_target_pct == 70.0
        assert "slo" in cfg.reward_weights

    def test_frozen_immutability(self):
        cfg = EnvConfig()
        with pytest.raises(AttributeError):
            cfg.min_replicas = 5  # type: ignore[misc]

    def test_custom_reward_weights(self):
        cfg = EnvConfig(
            reward_weights={"slo": 2.0, "efficiency": 0.5, "stability": 0.2}
        )
        assert cfg.reward_weights["slo"] == 2.0


# ---------------------------------------------------------------------------
# Render
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
