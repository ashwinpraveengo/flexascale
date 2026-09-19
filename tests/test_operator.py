"""
Unit and integration tests for FlexaScaleOperator (Phase 4).
"""

import pytest

from flexascale.config.safety_config import SafetyConfig
from flexascale.operator.operator import FlexaScaleOperator, default_hpa_heuristic
from flexascale.safety.coordinator import SafetyCoordinator
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ControlMode, ScalingLockManager
from flexascale.state.graph_inference import LiveGraphInference
from flexascale.state.live_builder import LiveStateBuilder


def test_default_hpa_heuristic():
    # obs: [cpu, mem, reps, rps, lat]
    obs_high = [85.0, 50.0, 2.0, 20.0, 50.0]
    assert default_hpa_heuristic(obs_high, cpu_target=70.0) == 2  # Scale Up

    obs_low = [40.0, 50.0, 2.0, 20.0, 50.0]
    assert default_hpa_heuristic(obs_low, cpu_target=70.0) == 0  # Scale Down

    obs_target = [71.0, 50.0, 2.0, 20.0, 50.0]
    assert default_hpa_heuristic(obs_target, cpu_target=70.0) == 1  # Maintain


def test_operator_initialization():
    config = SafetyConfig(dry_run=True)
    operator = FlexaScaleOperator(
        safety_config=config,
        mock=True,
        poll_interval_seconds=1.0,
    )
    status = operator.get_status()
    assert "running" in status
    assert "modes" in status
    assert len(status["services"]) == 4


def test_operator_step_execution():
    config = SafetyConfig(
        confidence_threshold=0.70,
        deactivation_threshold=0.60,
        dry_run=True,
    )
    lock_mgr = ScalingLockManager(config=config, sync_k8s=False)
    hpa_mgr = HPAManager(config=config, mock=True)
    coordinator = SafetyCoordinator(
        config=config,
        lock_manager=lock_mgr,
        hpa_manager=hpa_mgr,
    )
    state_builder = LiveStateBuilder(mock=True)
    graph_infer = LiveGraphInference()

    operator = FlexaScaleOperator(
        safety_config=config,
        coordinator=coordinator,
        state_builder=state_builder,
        graph_inference=graph_infer,
        mock=True,
    )

    decisions = operator.step()
    assert len(decisions) == 4

    # Check recent decisions history
    history = operator.get_recent_decisions()
    assert len(history) == 4
    for item in history:
        assert item["service_id"] in ["frontend", "orders", "inventory", "payments"]
        assert item["chosen_mode"] in ["RL", "HPA"]


def test_operator_clean_shutdown():
    config = SafetyConfig(dry_run=True)
    operator = FlexaScaleOperator(
        safety_config=config,
        mock=True,
    )
    # Run a step
    operator.step()
    # Trigger shutdown
    operator.shutdown()
    assert operator._running is False

    # Check that all services are in HPA mode
    for sid in operator.services:
        mode = operator.coordinator.lock_manager.get_control_mode(sid)
        assert mode == ControlMode.HPA
