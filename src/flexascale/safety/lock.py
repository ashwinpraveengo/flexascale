"""
Mutual-Exclusion Scaling Lock Manager for FlexaScale.

Enforces strict single-controller ownership over Kubernetes workloads:
RL and HPA can never scale the workload concurrently.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from flexascale.config.safety_config import SafetyConfig

logger = logging.getLogger(__name__)


class ControlMode(str, Enum):
    """
    Explicit controller ownership state for a workload.
    """

    HPA = "HPA"
    """Kubernetes HPA is active; RL is prohibited from scaling."""

    RL = "RL"
    """RL controller is active; HPA is prevented from conflicting."""

    LOCKED = "LOCKED"
    """Transition or critical state; no uncoordinated scaling permitted."""


@dataclass
class LockState:
    """State record for a service's scaling lock lease."""

    service_id: str
    mode: ControlMode = ControlMode.HPA
    owner: str = "hpa"
    confidence: float = 0.0
    acquired_at: float = 0.0
    expires_at: float = 0.0

    def is_expired(self, current_time: float | None = None) -> bool:
        """Return True if an RL lease has passed its TTL expiration."""
        now = current_time if current_time is not None else time.time()
        if self.mode == ControlMode.RL and self.expires_at > 0:
            return now >= self.expires_at
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "mode": self.mode.value,
            "owner": self.owner,
            "confidence": round(self.confidence, 4),
            "acquired_at": round(self.acquired_at, 2),
            "expires_at": round(self.expires_at, 2),
        }


class ScalingLockManager:
    """
    Manages mutual-exclusion locking between RL and HPA controllers.

    Supports both in-memory leasing (for unit tests / mock execution)
    and live Kubernetes ConfigMap synchronization.
    """

    def __init__(
        self,
        config: SafetyConfig | None = None,
        sync_k8s: bool = False,
    ) -> None:
        self.config = config or SafetyConfig()
        self.sync_k8s = sync_k8s
        self._locks: dict[str, LockState] = {}

        # Initialize lock records for all configured services in HPA mode
        for sid in self.config.service_names:
            self._locks[sid] = LockState(
                service_id=sid,
                mode=ControlMode.HPA,
                owner="hpa",
            )

        if self.sync_k8s and not self.config.dry_run:
            self._sync_to_k8s()

    def get_lock_state(self, service_id: str) -> LockState:
        """Return current LockState for a service, updating TTL expiration."""
        if service_id not in self._locks:
            self._locks[service_id] = LockState(
                service_id=service_id,
                mode=ControlMode.HPA,
                owner="hpa",
            )
        self._check_service_expiry(service_id)
        return self._locks[service_id]

    def get_control_mode(self, service_id: str) -> ControlMode:
        """Return current ControlMode for a service."""
        return self.get_lock_state(service_id).mode

    def acquire_rl_lock(
        self,
        service_id: str,
        confidence: float,
        timeout_seconds: float | None = None,
    ) -> bool:
        """
        Attempt to acquire an RL scaling lock for the specified service.

        Transitions state through ControlMode.LOCKED into ControlMode.RL.

        Args:
            service_id: Service to lock (e.g. 'frontend').
            confidence: Confidence score of the RL action triggering acquisition.
            timeout_seconds: Custom lease duration in seconds (defaults to config TTL).

        Returns:
            True if RL scaling lock was successfully acquired, False otherwise.
        """
        now = time.time()
        ttl = timeout_seconds if timeout_seconds is not None else self.config.lock_timeout_seconds
        state = self.get_lock_state(service_id)

        # Check if already locked by an active unexpired RL lease
        if state.mode == ControlMode.RL and not state.is_expired(now):
            # Renew existing lease
            state.confidence = confidence
            state.expires_at = now + ttl
            logger.info(
                "[LOCK] Renewed RL scaling lease for '%s' (expires in %.1fs)",
                service_id,
                ttl,
            )
            if self.sync_k8s and not self.config.dry_run:
                self._sync_to_k8s()
            return True

        if state.mode == ControlMode.LOCKED:
            logger.warning(
                "[LOCK] Cannot acquire lock for '%s': currently in LOCKED transition state",
                service_id,
            )
            return False

        # Transition safely: HPA -> LOCKED -> RL
        logger.info("[LOCK] Acquiring scaling ownership for '%s'...", service_id)
        state.mode = ControlMode.LOCKED
        state.owner = "transition"

        # Commit RL ownership
        state.mode = ControlMode.RL
        state.owner = "rl-controller"
        state.confidence = confidence
        state.acquired_at = now
        state.expires_at = now + ttl

        logger.info(
            "[LOCK] RL acquired scaling ownership for '%s' (ControlMode=RL, TTL=%.1fs)",
            service_id,
            ttl,
        )

        if self.sync_k8s and not self.config.dry_run:
            self._sync_to_k8s()

        return True

    def release_rl_lock(self, service_id: str, reason: str = "") -> None:
        """
        Release RL ownership and return the service safely to HPA control.

        Args:
            service_id: Target service name.
            reason: Optional description of why release occurred (e.g. 'confidence_drop').
        """
        if service_id not in self._locks:
            return
        state = self._locks[service_id]
        if state.mode == ControlMode.HPA:
            return  # Already under HPA control

        logger.info(
            "[LOCK] Releasing scaling ownership for '%s' back to HPA%s",
            service_id,
            f" (reason: {reason})" if reason else "",
        )

        state.mode = ControlMode.HPA
        state.owner = "hpa"
        state.expires_at = 0.0

        if self.sync_k8s and not self.config.dry_run:
            self._sync_to_k8s()

    def is_rl_locked(self, service_id: str) -> bool:
        """Return True if RL holds an active, non-expired lock on the service."""
        if service_id not in self._locks:
            return False
        state = self._locks[service_id]
        return state.mode == ControlMode.RL and not state.is_expired()

    def check_all_expiries(self) -> list[str]:
        """
        Scan all active leases; expire any whose TTL has lapsed and restore HPA.

        Returns:
            List of service IDs whose leases expired.
        """
        expired = []
        now = time.time()
        for sid in list(self._locks.keys()):
            state = self._locks[sid]
            if state.mode == ControlMode.RL and state.is_expired(now):
                logger.warning(
                    "[LOCK] Lease expired for '%s' (TTL elapsed). Failing safe to HPA.",
                    sid,
                )
                self.release_rl_lock(sid, reason="lease_ttl_expired")
                expired.append(sid)
        return expired

    def _check_service_expiry(self, service_id: str) -> None:
        """Check and handle TTL expiration for a single service."""
        if service_id in self._locks:
            state = self._locks[service_id]
            if state.mode == ControlMode.RL and state.is_expired():
                logger.warning(
                    "[LOCK] Lease expired for '%s'. Reverting ownership to HPA.",
                    service_id,
                )
                self.release_rl_lock(service_id, reason="lease_ttl_expired")

    def _sync_to_k8s(self) -> None:
        """Persist current lock states to Kubernetes ConfigMap for cluster observability."""
        try:
            data = {sid: json.dumps(lock.to_dict()) for sid, lock in self._locks.items()}
            data["last_updated"] = str(time.time())

            manifest = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": self.config.lock_configmap_name,
                    "namespace": self.config.namespace,
                    "labels": {"app.kubernetes.io/managed-by": "flexascale-safety"},
                },
                "data": data,
            }

            cmd = ["kubectl", "apply", "-f", "-"]
            subprocess.run(
                cmd,
                input=json.dumps(manifest),
                text=True,
                check=True,
                capture_output=True,
                timeout=5.0,
            )
        except Exception as exc:
            logger.debug("Failed to sync lock to ConfigMap: %s", exc)
