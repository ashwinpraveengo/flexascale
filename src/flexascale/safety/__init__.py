"""
FlexaScale Safety and Execution Layer (Phase 4).

Provides confidence-driven HPA fallback, mutual-exclusion locking,
and safety coordination between RL policies and Kubernetes HPA.
"""

from flexascale.safety.coordinator import SafetyCoordinator, SafetyDecision
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ControlMode, LockState, ScalingLockManager

__all__ = [
    "ControlMode",
    "LockState",
    "ScalingLockManager",
    "HPAManager",
    "SafetyCoordinator",
    "SafetyDecision",
]
