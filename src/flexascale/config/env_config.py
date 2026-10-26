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

    split: str = "all"
    """
    Dataset partition to simulate:
    - 'all': use entire dataset without partition filtering.
    - 'train': use training split (first 70% timestamps by default).
    - 'val': use validation split (middle 15% timestamps by default).
    - 'test': use testing split (final 15% timestamps by default).
    """

    split_method: str = "temporal"
    """
    Splitting methodology if dynamic slicing is used ('temporal', 'random', 'service').
    """

    train_ratio: float = 0.70
    """Proportion of data for the training split."""

    val_ratio: float = 0.15
    """Proportion of data for the validation split."""

    test_ratio: float = 0.15
    """Proportion of data for the test split."""

    service_id: str | None = None
    """
    Specific service to simulate.

    If ``None``, a service is chosen uniformly at random on each
    ``reset()`` call — useful for diverse RL training.
    """

    num_services: int = 4
    """Number of services simulated together in multi-service mode."""

    service_sampling: str = "top_frequency"
    """
    How multi-service episodes pick their services:
    - 'top_frequency': the ``num_services`` most frequent services (fixed).
    - 'random': a fresh random subset on every ``reset()`` drawn from services
      present at every timestamp of the split, so the policy cannot memorise
      slot identities.
    """

    demand_model: str = "trace"
    """
    How trace load is mapped to simulated utilisation:
    - 'trace': CPU scales with trace_replicas / simulated_replicas (original model).
    - 'normalized': each service's CPU demand (cpu% x instances) is rescaled per
      episode so its peak needs between ``peak_replicas_low`` and
      ``peak_replicas_high`` replicas at ``cpu_target_pct``; latency follows an
      M/M/1-style congestion factor. Keeps observations in the live replica range.
    """

    peak_replicas_low: int = 2
    """Lower bound of the per-episode peak replica requirement ('normalized' mode)."""

    peak_replicas_high: int = 8
    """Upper bound of the per-episode peak replica requirement ('normalized' mode)."""

    randomize_initial_replicas: bool = False
    """Start each episode from a uniform random replica count in [min, max]."""

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
            "cost": 0.0,
        }
    )
    """
    Component weights for the composite reward.

    Keys:
        slo         – weight for the SLO / latency compliance term
        efficiency  – weight for the CPU-target proximity term
        stability   – weight for the scaling-churn penalty
        cost        – weight for the allocation-cost penalty -replicas/max_replicas
                      (0 reproduces the original reward)
    """

    # ------------------------------------------------------------------
    # Dependency-aware dynamics (FlexaScaleEnvV2 only; ignored by FlexaScaleEnv)
    # ------------------------------------------------------------------

    slo_slack_low: float = 1.2
    slo_slack_high: float = 2.0
    """Per-service SLO = slack x the service's latency at ``cpu_target_pct`` (attainable by design)."""

    downstream_coupling_high: float = 1.0
    """Slot i calls slot i+1; a fraction U(0, high) of the callee's latency adds to the caller's."""

    external_latency_high: float = 2.0
    """Per-service latency that replicas cannot remove, U(0, high) x service time (e.g. a database)."""

    bottleneck_probability: float = 0.4
    """Probability that an episode has a shared dependency whose latency grows with total load."""

    traffic_events: bool = True
    """Overlay one app-wide traffic event (spike, ramp or drop) on the trace demand per episode."""

    control: str = "all"
    """
    'all': the agent's four action heads scale all four services and the reward averages them.
    'focal': the agent scales slot 0 only and is rewarded for slot 0 only; slots 1-3 (slot 0's
    downstream chain) follow ``background_policy``. Matches live neighbourhood inference, where only
    the slot-0 decision of each window is used.
    """

    background_epsilon: float = 0.2
    """'focal' control: probability that a background service takes a random action instead of the HPA rule."""

    slo_penalty_cap: float = 3.0
    """Bounded SLO penalty: a violating step scores max(-(latency/SLO - 1), -cap)."""

    # ------------------------------------------------------------------
    # Control-loop realism (FlexaScaleEnvV3 only; see simulator/control_env.py)
    # ------------------------------------------------------------------

    substeps: int = 4
    """Control steps per one-minute trace step (4 = 15 s, the live poll interval)."""

    action_deltas: tuple[int, ...] = (-2, -1, 0, 1, 2, 3)
    """Replica change for each action index."""

    max_scale_down_step: int = 2
    """Operator guard: at most this many replicas removed per decision."""

    startup_delay_steps: int = 1
    """Control steps before a new replica is ready (live median 10 s, p90 15 s)."""

    cpu_window_steps: int = 4
    """Observed CPU is the mean over this many control steps (Prometheus rate over 1 minute)."""

    trend_lookback_steps: int = 4
    """Request-rate trend compares with this many control steps ago (~60 s, as live)."""

    scale_up_cooldown_steps: int = 1
    """Operator guard: steps between two scale-ups of one service (live 15 s)."""

    scale_down_cooldown_steps: int = 2
    """Operator guard: steps between two scale-downs of one service (live 30 s)."""

    scale_down_block_cpu_pct: float = 85.0
    """Operator guard: no scale-down at or above this observed CPU."""

    hpa_stabilization_steps: int = 20
    """Native HPA scale-down stabilisation window (default 300 s)."""

    hpa_tolerance: float = 0.1
    """Native HPA tolerance around the CPU target."""

    # ------------------------------------------------------------------
    # Observation bounds (used for Gymnasium Box space)
    # ------------------------------------------------------------------

    obs_max_rps: float = 10_000.0
    """Upper bound for request-rate in the observation Box."""

    obs_max_latency: float = 10_000.0
    """Upper bound for latency in the observation Box."""
