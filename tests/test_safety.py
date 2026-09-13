"""
Unit tests for FlexaScale Phase 4: HPA Fallback + Mutual-Exclusion Lock.

Covers all 7 validation requirements:
    1. High confidence: RL acquires ownership, freezes HPA, applies action
    2. Low confidence: RL blocked, HPA dynamic mode active
    3. Mutual exclusion: RL and HPA cannot simultaneously scale workload
    4. Lock release: Lock released properly when returning to HPA
    5. RL failure: Exceptions fail safe to HPA fallback without permanent locking
    6. Invalid/missing confidence: None, NaN, out-of-range fails safe to HPA
    7. Rapid fluctuations: Hysteresis and cooldown prevent controller flapping
"""

import math
import time
import pytest

from flexascale.config.safety_config import SafetyConfig
from flexascale.safety.coordinator import SafetyCoordinator
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ControlMode, ScalingLockManager


@pytest.fixture
def safety_config() -> SafetyConfig:
    return SafetyConfig(
        confidence_threshold=0.70,
        deactivation_threshold=0.60,
        cooldown_seconds=1.0,  # Short cooldown for test speed
        lock_timeout_seconds=2.0,
        hpa_min_replicas=1,
        hpa_max_replicas=10,
        dry_run=True,
    )


@pytest.fixture
def lock_mgr(safety_config) -> ScalingLockManager:
    return ScalingLockManager(config=safety_config, sync_k8s=False)


@pytest.fixture
def hpa_mgr(safety_config) -> HPAManager:
    return HPAManager(config=safety_config, mock=True)


@pytest.fixture
def coordinator(safety_config, lock_mgr, hpa_mgr) -> SafetyCoordinator:
    return SafetyCoordinator(
        config=safety_config,
        lock_manager=lock_mgr,
        hpa_manager=hpa_mgr,
    )


class TestSafetyHPAFallback:
    """Test suite for Phase 4 HPA Fallback and Mutual Exclusion."""

    def test_high_confidence_rl_scaling(self, coordinator, hpa_mgr):
        """Test 1: High confidence enables RL ownership and freezes HPA."""
        # Initial state: 2 replicas
        hpa_mgr._mock_replicas["frontend"] = 2

        # RL action=2 (Scale UP), confidence=0.85 >= 0.70
        decision = coordinator.evaluate_and_execute(
            service_id="frontend",
            action=2,
            confidence=0.85,
            current_replicas=2,
        )

        assert decision.chosen_mode == ControlMode.RL
        assert decision.lock_acquired is True
        assert decision.hpa_frozen is True
        assert decision.hpa_active is False
        assert decision.target_replicas == 3
        assert decision.action_applied == 2

        # Verify HPA bounds are clamped to prevent HPA conflicts
        bounds = hpa_mgr.get_hpa_bounds("frontend")
        assert bounds == (3, 3)
        assert hpa_mgr.get_deployment_replicas("frontend") == 3

    def test_low_confidence_hpa_fallback(self, coordinator, hpa_mgr):
        """Test 2: Low confidence keeps HPA in control and blocks RL."""
        decision = coordinator.evaluate_and_execute(
            service_id="orders",
            action=2,
            confidence=0.55,  # Below 0.70 threshold
            current_replicas=2,
        )

        assert decision.chosen_mode == ControlMode.HPA
        assert decision.lock_acquired is False
        assert decision.action_applied is None
        assert decision.hpa_active is True
        assert decision.hpa_frozen is False

        # Verify HPA has dynamic bounds
        bounds = hpa_mgr.get_hpa_bounds("orders")
        assert bounds == (1, 10)

    def test_mutual_exclusion(self, coordinator, lock_mgr, hpa_mgr):
        """Test 3: Mutual exclusion prevents concurrent scaling."""
        # RL acquires lock on inventory
        decision = coordinator.evaluate_and_execute(
            service_id="inventory",
            action=2,
            confidence=0.80,
            current_replicas=1,
        )
        assert decision.chosen_mode == ControlMode.RL
        assert lock_mgr.is_rl_locked("inventory")

        # In RL mode, HPA is frozen to target replicas (2, 2)
        assert hpa_mgr.get_hpa_bounds("inventory") == (2, 2)

        # Mode cannot be simultaneously HPA and RL
        mode = lock_mgr.get_control_mode("inventory")
        assert mode == ControlMode.RL
        assert mode != ControlMode.HPA

    def test_lock_release(self, coordinator, lock_mgr, hpa_mgr):
        """Test 4: Falling back releases the lock and restores dynamic HPA."""
        # 1. RL acquires lock
        coordinator.evaluate_and_execute(
            service_id="payments",
            action=1,
            confidence=0.80,
            current_replicas=2,
        )
        assert lock_mgr.is_rl_locked("payments")

        # 2. Confidence drops -> triggers release
        dec = coordinator.evaluate_and_execute(
            service_id="payments",
            action=1,
            confidence=0.40,
            current_replicas=2,
        )

        assert dec.chosen_mode == ControlMode.HPA
        assert not lock_mgr.is_rl_locked("payments")
        assert lock_mgr.get_control_mode("payments") == ControlMode.HPA
        assert hpa_mgr.get_hpa_bounds("payments") == (1, 10)

    def test_rl_failure_fails_safe_to_hpa(self, coordinator, hpa_mgr, lock_mgr, monkeypatch):
        """Test 5: Exceptions during RL execution safely fall back to HPA."""
        # Force scale_deployment to fail
        def mock_failing_scale(service_id, target_replicas):
            raise RuntimeError("Simulated Kubernetes connection timeout")

        monkeypatch.setattr(hpa_mgr, "scale_deployment", mock_failing_scale)

        decision = coordinator.evaluate_and_execute(
            service_id="frontend",
            action=2,
            confidence=0.95,
            current_replicas=2,
        )

        # Must fail safe to HPA
        assert decision.chosen_mode == ControlMode.HPA
        assert decision.action_applied is None
        assert not lock_mgr.is_rl_locked("frontend")
        assert hpa_mgr.get_hpa_bounds("frontend") == (1, 10)

    @pytest.mark.parametrize("bad_conf", [None, float("nan"), -0.5, 1.5])
    def test_invalid_missing_confidence_fails_safe(self, coordinator, bad_conf):
        """Test 6: None, NaN, and out-of-range confidence scores trigger HPA fallback."""
        decision = coordinator.evaluate_and_execute(
            service_id="orders",
            action=2,
            confidence=bad_conf,
            current_replicas=1,
        )

        assert decision.chosen_mode == ControlMode.HPA
        assert decision.lock_acquired is False
        assert decision.reason == "invalid_or_missing_confidence"

    def test_hysteresis_and_cooldown(self, coordinator):
        """Test 7: Hysteresis floor and cooldown prevent controller oscillation."""
        # Step A: High confidence -> RL takes control (0.85 >= 0.70)
        decA = coordinator.evaluate_and_execute("frontend", action=1, confidence=0.85, current_replicas=2)
        assert decA.chosen_mode == ControlMode.RL

        # Step B: Soft dip to 0.65 -> above deactivation floor (0.60), stays in RL mode
        decB = coordinator.evaluate_and_execute("frontend", action=1, confidence=0.65, current_replicas=2)
        assert decB.chosen_mode == ControlMode.RL

        # Step C: Deep dip to 0.50 -> below 0.60, falls back to HPA
        decC = coordinator.evaluate_and_execute("frontend", action=1, confidence=0.50, current_replicas=2)
        assert decC.chosen_mode == ControlMode.HPA

        # Step D: Rapid spike back to 0.85 within cooldown period -> Cooldown blocks RL, stays in HPA
        decD = coordinator.evaluate_and_execute("frontend", action=1, confidence=0.85, current_replicas=2)
        assert decD.chosen_mode == ControlMode.HPA

        # Step E: Wait for cooldown (1.1s > 1.0s) -> RL re-activates
        time.sleep(1.1)
        decE = coordinator.evaluate_and_execute("frontend", action=1, confidence=0.85, current_replicas=2)
        assert decE.chosen_mode == ControlMode.RL

    def test_lock_lease_expiry_crash_recovery(self, lock_mgr):
        """Test 8: Automatic expiration of RL lease if controller crashes without unlocking."""
        # Acquire lock with 0.1s TTL
        lock_mgr.acquire_rl_lock("inventory", confidence=0.9, timeout_seconds=0.1)
        assert lock_mgr.is_rl_locked("inventory")

        time.sleep(0.15)
        # Lease should have expired
        assert not lock_mgr.is_rl_locked("inventory")
        expired = lock_mgr.check_all_expiries()
        assert "inventory" in expired
        assert lock_mgr.get_control_mode("inventory") == ControlMode.HPA
