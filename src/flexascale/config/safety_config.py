"""
Safety and execution configuration for FlexaScale Phase 4.

Defines all tuneable thresholds for HPA fallback, mutual-exclusion locking,
confidence hysteresis, and Kubernetes HPA replica bounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class SafetyConfig:
    """
    Immutable configuration for Phase 4 Safety & Execution layer.
    """

    # ------------------------------------------------------------------
    # Confidence & Hysteresis Thresholds
    # ------------------------------------------------------------------

    confidence_threshold: float = 0.70
    """
    Minimum probability score required for RL controller to take ownership.
    Actions with confidence >= confidence_threshold are applied via RL.
    """

    deactivation_threshold: float = 0.60
    """
    Hysteresis floor. If RL currently owns the workload, it maintains ownership
    until confidence drops below this value. Prevents rapid flapping.
    """

    cooldown_seconds: float = 15.0
    """
    Minimum duration (seconds) required before re-activating RL after falling back to HPA.
    """

    # ------------------------------------------------------------------
    # Mutual-Exclusion Lock Parameters
    # ------------------------------------------------------------------

    lock_timeout_seconds: float = 60.0
    """
    Maximum lease duration (TTL) for RL scaling ownership.
    If the RL controller crashes or fails to renew, the lock expires automatically
    and safely reverts control to HPA.
    """

    lock_configmap_name: str = "flexascale-safety-lock"
    """Name of the Kubernetes ConfigMap tracking live lock state."""

    # ------------------------------------------------------------------
    # Kubernetes Target & HPA Bounds
    # ------------------------------------------------------------------

    namespace: str = "flexascale-apps"
    """Kubernetes namespace where microservices and HPAs reside."""

    service_names: tuple[str, ...] = (
        "frontend",
        "orders",
        "inventory",
        "payments",
    )
    """List of microservices governed by the safety layer."""

    hpa_min_replicas: int = 1
    """Default minimum replicas for dynamic HPA scaling."""

    hpa_max_replicas: int = 10
    """Default maximum replicas for dynamic HPA scaling."""

    target_cpu_utilization: int = 70
    """Target CPU utilization percentage for baseline HPA."""

    dry_run: bool = False
    """If True, simulates scaling decisions without executing Kubernetes commands."""
