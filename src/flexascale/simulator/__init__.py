"""
FlexaScale simulator package.

Exports:
    FlexaScaleEnv   – Gymnasium environment for trace-driven RL training.
    MockClusterEnv  – Synthetic mock environment (backward compatibility).
"""

from flexascale.simulator.flexascale_env import FlexaScaleEnv
from flexascale.simulator.mock_env import MockClusterEnv

__all__ = ["FlexaScaleEnv", "MockClusterEnv"]
