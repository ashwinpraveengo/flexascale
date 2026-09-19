"""
Safety Coordinator for FlexaScale Phase 4.

Orchestrates the confidence-driven HPA fallback loop and mutual-exclusion locking:
- Evaluates RL confidence against activation/deactivation thresholds with hysteresis
- Enforces mutual exclusion: RL and HPA never control the workload concurrently
- Handles fail-safe recovery on crash, timeout, invalid confidence, or API failures
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from flexascale.config.safety_config import SafetyConfig
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ControlMode, ScalingLockManager

logger = logging.getLogger(__name__)


@dataclass
class SafetyDecision:
    """Detailed record of a safety coordinator scaling decision."""

    service_id: str
    chosen_mode: ControlMode
    confidence: float | None
    target_replicas: int
    action_applied: int | None
    lock_acquired: bool
    hpa_frozen: bool
    hpa_active: bool
    reason: str


class SafetyCoordinator:
    """
    Central safety execution coordinator.

    Routes scaling decisions between the RL controller and Kubernetes HPA
    based on model confidence, lock status, and safety thresholds.
    """

    def __init__(
        self,
        config: SafetyConfig | None = None,
        lock_manager: ScalingLockManager | None = None,
        hpa_manager: HPAManager | None = None,
    ) -> None:
        self.config = config or SafetyConfig()
        self.lock_manager = lock_manager or ScalingLockManager(
            config=self.config,
            sync_k8s=not self.config.dry_run,
        )
        self.hpa_manager = hpa_manager or HPAManager(
            config=self.config,
            mock=self.config.dry_run,
        )

        self._last_fallback_time: dict[str, float] = {}

    def evaluate_and_execute(
        self,
        service_id: str,
        action: int | None,
        confidence: float | None,
        current_replicas: int | None = None,
    ) -> SafetyDecision:
        """
        Evaluate confidence and apply the scaling decision safely.

        Args:
            service_id: Target microservice name ('frontend', 'orders', etc.).
            action: Action integer from RL agent (0=scale down, 1=maintain, 2=scale up).
            confidence: Float confidence score in [0.0, 1.0].
            current_replicas: Current replica count (queried from cluster if None).

        Returns:
            SafetyDecision describing the chosen mode, actions, and safety state.
        """
        now = time.time()
        curr_mode = self.lock_manager.get_control_mode(service_id)

        if current_replicas is None:
            current_replicas = self.hpa_manager.get_deployment_replicas(service_id)

        # ------------------------------------------------------------------
        # 1. Invalid or Missing Confidence -> Immediate Safe Fallback to HPA
        # ------------------------------------------------------------------
        if confidence is None or math.isnan(confidence) or not (0.0 <= confidence <= 1.0):
            logger.warning(
                "[SAFETY] Invalid or missing confidence for '%s' (value=%s). Falling back safely to HPA.",
                service_id,
                confidence,
            )
            return self._execute_hpa_fallback(
                service_id=service_id,
                confidence=confidence,
                current_replicas=current_replicas,
                reason="invalid_or_missing_confidence",
            )

        logger.info("[SAFETY] RL confidence for '%s': %.2f", service_id, confidence)

        # ------------------------------------------------------------------
        # 2. Check Hysteresis & Cooldown to Determine Target Mode
        # ------------------------------------------------------------------
        target_mode: ControlMode

        if curr_mode == ControlMode.RL:
            # RL currently owns scaling -> check hysteresis deactivation floor
            if confidence >= self.config.deactivation_threshold:
                target_mode = ControlMode.RL
            else:
                logger.info(
                    "[SAFETY] RL confidence (%.2f) dropped below deactivation floor (%.2f). Falling back to HPA.",
                    confidence,
                    self.config.deactivation_threshold,
                )
                target_mode = ControlMode.HPA
        else:
            # HPA currently owns scaling -> check activation threshold + cooldown
            if confidence >= self.config.confidence_threshold:
                last_fb = self._last_fallback_time.get(service_id, 0.0)
                elapsed = now - last_fb
                if elapsed < self.config.cooldown_seconds:
                    logger.info(
                        "[SAFETY] RL confidence (%.2f) >= threshold (%.2f), but cooldown active (%.1fs remaining). Maintaining HPA.",
                        confidence,
                        self.config.confidence_threshold,
                        self.config.cooldown_seconds - elapsed,
                    )
                    target_mode = ControlMode.HPA
                else:
                    logger.info(
                        "[SAFETY] RL confidence (%.2f) above activation threshold (%.2f). Transferring ownership to RL.",
                        confidence,
                        self.config.confidence_threshold,
                    )
                    target_mode = ControlMode.RL
            else:
                logger.info(
                    "[SAFETY] RL confidence (%.2f) below activation threshold (%.2f). Maintaining HPA fallback.",
                    confidence,
                    self.config.confidence_threshold,
                )
                target_mode = ControlMode.HPA

        # ------------------------------------------------------------------
        # 3. Execution Branch: RL Mode vs HPA Mode
        # ------------------------------------------------------------------
        if target_mode == ControlMode.RL and action is not None:
            return self._execute_rl_scaling(
                service_id=service_id,
                action=action,
                confidence=confidence,
                current_replicas=current_replicas,
            )
        else:
            return self._execute_hpa_fallback(
                service_id=service_id,
                confidence=confidence,
                current_replicas=current_replicas,
                reason="low_confidence" if target_mode == ControlMode.HPA else "no_action",
            )

    def _execute_rl_scaling(
        self,
        service_id: str,
        action: int,
        confidence: float,
        current_replicas: int,
    ) -> SafetyDecision:
        """Execute scaling under RL ownership while freezing HPA to avoid conflict."""
        try:
            # Step A: Acquire mutual-exclusion lock
            lock_ok = self.lock_manager.acquire_rl_lock(
                service_id=service_id,
                confidence=confidence,
                timeout_seconds=self.config.lock_timeout_seconds,
            )
            if not lock_ok:
                logger.warning(
                    "[LOCK] Failed to acquire lock for '%s'. Falling back safely to HPA.",
                    service_id,
                )
                return self._execute_hpa_fallback(
                    service_id=service_id,
                    confidence=confidence,
                    current_replicas=current_replicas,
                    reason="lock_acquisition_failed",
                )

            # Step B: Calculate new replica count
            delta = action - 1  # 0 -> -1, 1 -> 0, 2 -> +1
            target_replicas = max(
                self.config.hpa_min_replicas,
                min(self.config.hpa_max_replicas, current_replicas + delta),
            )

            # Step C: Prevent HPA conflict by freezing HPA bounds
            freeze_ok = self.hpa_manager.freeze_hpa(
                service_id=service_id,
                target_replicas=target_replicas,
            )
            if not freeze_ok:
                logger.warning(
                    "[HPA] Failed to freeze HPA for '%s'. Aborting RL scale to prevent conflict.",
                    service_id,
                )
                return self._execute_hpa_fallback(
                    service_id=service_id,
                    confidence=confidence,
                    current_replicas=current_replicas,
                    reason="hpa_freeze_failed",
                )

            # Step D: Apply RL scaling to Deployment
            scale_ok = self.hpa_manager.scale_deployment(
                service_id=service_id,
                target_replicas=target_replicas,
            )
            if not scale_ok:
                logger.error(
                    "[RL] Scaling command failed for '%s'. Falling back safely to HPA.",
                    service_id,
                )
                return self._execute_hpa_fallback(
                    service_id=service_id,
                    confidence=confidence,
                    current_replicas=current_replicas,
                    reason="scale_deployment_failed",
                )

            logger.info(
                "[RL] Successfully scaled '%s' to %d replicas under RL ownership.",
                service_id,
                target_replicas,
            )

            return SafetyDecision(
                service_id=service_id,
                chosen_mode=ControlMode.RL,
                confidence=confidence,
                target_replicas=target_replicas,
                action_applied=action,
                lock_acquired=True,
                hpa_frozen=True,
                hpa_active=False,
                reason="high_confidence_rl_scaling",
            )

        except Exception as exc:
            logger.exception(
                "[SAFETY] Unexpected error during RL scaling for '%s': %s. Failing safe to HPA.",
                service_id,
                exc,
            )
            return self._execute_hpa_fallback(
                service_id=service_id,
                confidence=confidence,
                current_replicas=current_replicas,
                reason=f"exception: {exc}",
            )

    def _execute_hpa_fallback(
        self,
        service_id: str,
        confidence: float | None,
        current_replicas: int,
        reason: str,
    ) -> SafetyDecision:
        """Safely restore dynamic HPA control and release any RL lock."""
        # 1. Release RL lock
        self.lock_manager.release_rl_lock(service_id=service_id, reason=reason)

        # 2. Restore dynamic HPA scaling
        hpa_ok = self.hpa_manager.ensure_hpa_active(service_id=service_id)

        # 3. Record fallback timestamp for cooldown tracking
        self._last_fallback_time[service_id] = time.time()

        logger.info(
            "[SAFETY] Service '%s' governed by HPA (reason: %s). RL scaling disabled.",
            service_id,
            reason,
        )

        return SafetyDecision(
            service_id=service_id,
            chosen_mode=ControlMode.HPA,
            confidence=confidence,
            target_replicas=current_replicas,
            action_applied=None,
            lock_acquired=False,
            hpa_frozen=False,
            hpa_active=hpa_ok,
            reason=reason,
        )

    def fallback_all_to_hpa(
        self,
        reason: str = "cluster_shutdown",
        services: Sequence[str] | None = None,
    ) -> None:
        """Emergency or teardown helper: ensures all services are under active HPA control."""
        logger.info("[SAFETY] Falling back all services to HPA (reason: %s)...", reason)
        target_services = list(services) if services is not None else list(self.config.service_names)
        for sid in target_services:
            self._execute_hpa_fallback(
                service_id=sid,
                confidence=None,
                current_replicas=self.config.hpa_min_replicas,
                reason=reason,
            )
