#!/usr/bin/env python3
"""
FlexaScale Safety Controller CLI (Phase 4).

Demonstrates and verifies HPA fallback, mutual-exclusion locking,
hysteresis, and crash-recovery on Kubernetes or in simulation.

Usage:
    # Run comprehensive automated safety demo (mock mode)
    python scripts/run_safety_controller.py --demo

    # Run against live Minikube cluster
    python scripts/run_safety_controller.py --live --demo
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure src/ is importable
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from flexascale.config.safety_config import SafetyConfig
from flexascale.safety.coordinator import SafetyCoordinator
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ControlMode, ScalingLockManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SafetyController")


def run_automated_demo(coordinator: SafetyCoordinator, service: str = "frontend") -> None:
    """Run an automated sequence validating all 7 safety scenarios."""
    print("\n" + "=" * 80)
    print(f"FLEXASCALE PHASE 4 — SAFETY & HPA FALLBACK VERIFICATION DEMO")
    print(f"Target Service: {service}")
    print(f"Confidence Threshold (RL Activation):   {coordinator.config.confidence_threshold:.2f}")
    print(f"Deactivation Floor (Hysteresis):        {coordinator.config.deactivation_threshold:.2f}")
    print(f"Cooldown Period:                        {coordinator.config.cooldown_seconds:.1f}s")
    print(f"Lock TTL (Crash Recovery):              {coordinator.config.lock_timeout_seconds:.1f}s")
    print("=" * 80)

    # ------------------------------------------------------------------
    # Scenario 1: High Confidence Scaling (RL Ownership)
    # ------------------------------------------------------------------
    print("\n[Scenario 1] High Confidence RL Action (conf=0.85, action=2 -> Scale UP)")
    print("-" * 80)
    dec1 = coordinator.evaluate_and_execute(
        service_id=service,
        action=2,
        confidence=0.85,
        current_replicas=1,
    )
    print(f"Result -> Mode: {dec1.chosen_mode.value}, Target Replicas: {dec1.target_replicas}, Lock: {dec1.lock_acquired}, HPA Frozen: {dec1.hpa_frozen}")
    assert dec1.chosen_mode == ControlMode.RL
    assert dec1.target_replicas == 2
    assert dec1.lock_acquired is True

    # ------------------------------------------------------------------
    # Scenario 2: Hysteresis Maintenance (conf=0.65, between floor 0.60 and 0.70)
    # ------------------------------------------------------------------
    print("\n[Scenario 2] Confidence Soft Drop (conf=0.65: above 0.60 floor, maintains RL)")
    print("-" * 80)
    dec2 = coordinator.evaluate_and_execute(
        service_id=service,
        action=1,
        confidence=0.65,
        current_replicas=2,
    )
    print(f"Result -> Mode: {dec2.chosen_mode.value}, Replicas: {dec2.target_replicas}, HPA Frozen: {dec2.hpa_frozen}")
    assert dec2.chosen_mode == ControlMode.RL
    assert dec2.hpa_frozen is True

    # ------------------------------------------------------------------
    # Scenario 3: Low Confidence -> Safe Fallback to HPA
    # ------------------------------------------------------------------
    print("\n[Scenario 3] Low Confidence Drop (conf=0.45 < 0.60 -> Release Lock, Restore HPA)")
    print("-" * 80)
    dec3 = coordinator.evaluate_and_execute(
        service_id=service,
        action=2,
        confidence=0.45,
        current_replicas=2,
    )
    print(f"Result -> Mode: {dec3.chosen_mode.value}, Lock: {dec3.lock_acquired}, HPA Active: {dec3.hpa_active}")
    assert dec3.chosen_mode == ControlMode.HPA
    assert dec3.lock_acquired is False
    assert dec3.hpa_active is True

    # ------------------------------------------------------------------
    # Scenario 4: Rapid Flapping Prevention via Cooldown
    # ------------------------------------------------------------------
    print("\n[Scenario 4] Immediate High Confidence Spike During Cooldown (conf=0.88)")
    print("-" * 80)
    dec4 = coordinator.evaluate_and_execute(
        service_id=service,
        action=2,
        confidence=0.88,
        current_replicas=2,
    )
    print(f"Result -> Mode: {dec4.chosen_mode.value}, Reason: {dec4.reason}")
    assert dec4.chosen_mode == ControlMode.HPA

    # ------------------------------------------------------------------
    # Scenario 5: Invalid/Missing Confidence -> Fail-Safe HPA Fallback
    # ------------------------------------------------------------------
    print("\n[Scenario 5] Missing/Invalid Confidence (conf=None -> Fail Safe to HPA)")
    print("-" * 80)
    dec5 = coordinator.evaluate_and_execute(
        service_id=service,
        action=0,
        confidence=None,
        current_replicas=2,
    )
    print(f"Result -> Mode: {dec5.chosen_mode.value}, HPA Active: {dec5.hpa_active}")
    assert dec5.chosen_mode == ControlMode.HPA

    # ------------------------------------------------------------------
    # Scenario 6: Crash / Lease Expiry Recovery
    # ------------------------------------------------------------------
    print("\n[Scenario 6] Simulated Crash / Lease Expiration Recovery")
    print("-" * 80)
    # Manually simulate expired lock
    coordinator.lock_manager.acquire_rl_lock(service, confidence=0.9, timeout_seconds=0.1)
    print(f"Acquired short-lived lease. Waiting for TTL expiration...")
    time.sleep(0.15)
    expired = coordinator.lock_manager.check_all_expiries()
    mode_now = coordinator.lock_manager.get_control_mode(service)
    print(f"Expired services: {expired} -> Mode restored to: {mode_now.value}")
    assert service in expired
    assert mode_now == ControlMode.HPA

    # ------------------------------------------------------------------
    # Scenario 7: Full HPA Re-activation
    # ------------------------------------------------------------------
    print("\n[Scenario 7] Cluster Teardown / Safe Fallback All to HPA")
    print("-" * 80)
    coordinator.fallback_all_to_hpa(reason="demo_complete")
    for sid in coordinator.config.service_names:
        assert coordinator.lock_manager.get_control_mode(sid) == ControlMode.HPA

    print("\n" + "=" * 80)
    print("ALL PHASE 4 SAFETY & HPA FALLBACK SCENARIOS VERIFIED SUCCESSFULLY!")
    print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(description="FlexaScale Safety Controller CLI")
    parser.add_argument("--demo", action="store_true", help="Run automated 7-scenario safety verification")
    parser.add_argument("--live", action="store_true", help="Execute against live Kubernetes cluster via kubectl")
    parser.add_argument("--service", type=str, default="frontend", help="Target microservice (default: frontend)")
    parser.add_argument("--threshold", type=float, default=0.70, help="Confidence threshold (default: 0.70)")
    parser.add_argument("--cooldown", type=float, default=15.0, help="Cooldown seconds (default: 15.0)")
    args = parser.parse_args()

    config = SafetyConfig(
        confidence_threshold=args.threshold,
        cooldown_seconds=args.cooldown,
        dry_run=not args.live,
    )

    lock_mgr = ScalingLockManager(config=config, sync_k8s=args.live)
    hpa_mgr = HPAManager(config=config, mock=not args.live)
    coordinator = SafetyCoordinator(config=config, lock_manager=lock_mgr, hpa_manager=hpa_mgr)

    if args.demo:
        run_automated_demo(coordinator, service=args.service)
    else:
        print(f"Safety Controller initialized for service '{args.service}' (live={args.live}).")
        print("Use --demo to run the automated safety verification suite.")


if __name__ == "__main__":
    main()
