"""
Environment configuration for the FlexaScale RL simulation.

Centralises every tuneable parameter so that no magic numbers are
scattered throughout the environment or reward code.  All downstream
consumers (GNN encoder, PPO agent, confidence loop) can import and
override fields via ``dataclasses.replace(cfg, latency_target_ms=50)``.

Usage::

    from flexascale.config.env_config import EnvConfig

    cfg = EnvConfig()                       # all defaults
    cfg = EnvConfig(latency_target_ms=50)   # override one field
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EnvConfig:
    """Immutable configuration for :class:`FlexaScaleEnv`."""

    # ------------------------------------------------------------------
    # Dataset
    # ------------------------------------------------------------------

    dataset_path: str = str(
        Path("data/processed/alibaba_service_state.csv")
    )
    """Path to the processed Alibaba trace CSV produced by Phase 1."""

    service_id: str | None = None
    """
    Specific service to simulate.

    If ``None``, a service is chosen uniformly at random on each
    ``reset()`` call — useful for diverse RL training.
    """

    # ------------------------------------------------------------------
    # Replica limits
    # ------------------------------------------------------------------

    min_replicas: int = 1
    """Minimum number of replicas the agent can maintain."""

    max_replicas: int = 50
    """Maximum number of replicas the agent can scale to."""

    # ------------------------------------------------------------------
    # SLO targets
    # ------------------------------------------------------------------

    latency_target_ms: float = 100.0
    """
    Latency SLO threshold in milliseconds.

    The reward function penalises the agent when simulated latency
    exceeds this value.
    """

    cpu_target_pct: float = 70.0
    """
    Desired mean CPU utilisation (percentage points).

    The efficiency reward component drives the agent toward this target.
    """

    memory_target_pct: float = 80.0
    """
    Desired mean memory utilisation (percentage points).

    Currently used for observation bounds; can be wired into reward
    if needed.
    """

    # ------------------------------------------------------------------
    # Reward weights
    # ------------------------------------------------------------------

    reward_weights: dict[str, float] = field(
        default_factory=lambda: {
            "slo": 1.0,
            "efficiency": 0.3,
            "stability": 0.1,
        }
    )
    """
    Component weights for the composite reward.

    Keys:
        slo         – weight for the SLO / latency compliance term
        efficiency  – weight for the CPU-target proximity term
        stability   – weight for the scaling-churn penalty
    """

    # ------------------------------------------------------------------
    # Observation bounds (used for Gymnasium Box space)
    # ------------------------------------------------------------------

    obs_max_rps: float = 10_000.0
    """Upper bound for request-rate in the observation Box."""

    obs_max_latency: float = 10_000.0
    """Upper bound for latency in the observation Box."""
