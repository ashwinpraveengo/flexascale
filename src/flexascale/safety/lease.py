"""
Cluster-wide controller ownership via a Kubernetes ``coordination.k8s.io/v1`` Lease.

Exactly one FlexaScale controller instance may scale an application at a
time. Acquisition and renewal use ``kubectl replace`` with the Lease's
``resourceVersion`` so two contenders cannot both win (optimistic
concurrency enforced by the API server). An expired lease (holder stopped
renewing) can be taken over; a live lease held by someone else cannot.

This complements the per-Deployment HPA freeze: the Lease prevents two
FlexaScale instances from fighting, the freeze prevents FlexaScale and the
HPA controller from fighting.
"""

from __future__ import annotations

import logging
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flexascale.k8s.kube import Kube

logger = logging.getLogger(__name__)


def _now_micro() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_time(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def default_identity() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"


@dataclass
class LeaseStatus:
    exists: bool
    holder: Optional[str]
    renew_time: Optional[float]
    duration_seconds: int
    expired: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exists": self.exists,
            "holder": self.holder,
            "renew_time": self.renew_time,
            "duration_seconds": self.duration_seconds,
            "expired": self.expired,
        }


class ControllerLease:
    def __init__(
        self,
        namespace: str,
        app_name: str,
        identity: Optional[str] = None,
        duration_seconds: float = 30.0,
        kube: Optional[Kube] = None,
    ) -> None:
        self.namespace = namespace
        self.name = f"flexascale-{app_name}"
        self.identity = identity or default_identity()
        self.duration = int(max(2, round(duration_seconds)))
        self.kube = kube or Kube()
        self.held = False
        self.last_error: Optional[str] = None

    def _get(self) -> Optional[Dict[str, Any]]:
        return self.kube.get_json("lease", self.namespace, name=self.name)

    def status(self) -> LeaseStatus:
        obj = self._get()
        if obj is None:
            return LeaseStatus(False, None, None, self.duration, True)
        spec = obj.get("spec", {})
        holder = spec.get("holderIdentity") or None
        renew = _parse_time(spec.get("renewTime"))
        duration = int(spec.get("leaseDurationSeconds") or self.duration)
        expired = holder is None or renew is None or (time.time() > renew + duration)
        return LeaseStatus(True, holder, renew, duration, expired)

    def _manifest(self, obj: Optional[Dict[str, Any]], holder: Optional[str], acquire: bool) -> Dict[str, Any]:
        now = _now_micro()
        spec: Dict[str, Any] = dict((obj or {}).get("spec", {}))
        spec["holderIdentity"] = holder or ""
        spec["leaseDurationSeconds"] = self.duration
        spec["renewTime"] = now
        if acquire:
            spec["acquireTime"] = now
            spec["leaseTransitions"] = int(spec.get("leaseTransitions", 0)) + (1 if obj else 0)
        metadata: Dict[str, Any] = {
            "name": self.name,
            "namespace": self.namespace,
            "labels": {"app.kubernetes.io/managed-by": "flexascale"},
        }
        if obj is not None:
            metadata["resourceVersion"] = obj.get("metadata", {}).get("resourceVersion")
        return {"apiVersion": "coordination.k8s.io/v1", "kind": "Lease", "metadata": metadata, "spec": spec}

    def acquire(self) -> bool:
        """Take or renew the lease. Returns False when another live holder owns it."""
        obj = self._get()
        if obj is None:
            res = self.kube.create(self._manifest(None, self.identity, acquire=True))
            self.held = res.ok
            self.last_error = None if res.ok else res.stderr
            return self.held

        spec = obj.get("spec", {})
        holder = spec.get("holderIdentity") or None
        renew = _parse_time(spec.get("renewTime"))
        duration = int(spec.get("leaseDurationSeconds") or self.duration)
        mine = holder == self.identity
        expired = holder is None or renew is None or time.time() > renew + duration
        if not mine and not expired:
            self.held = False
            self.last_error = f"lease held by '{holder}'"
            return False

        res = self.kube.replace(self._manifest(obj, self.identity, acquire=not mine))
        self.held = res.ok
        self.last_error = None if res.ok else res.stderr
        if not res.ok:
            logger.warning("[LEASE] %s on %s/%s failed: %s", "renew" if mine else "acquire", self.namespace, self.name, res.stderr)
        return self.held

    renew = acquire

    def release(self) -> bool:
        """Give the lease up (only if we hold it)."""
        obj = self._get()
        if obj is None:
            self.held = False
            return True
        if (obj.get("spec", {}).get("holderIdentity") or None) != self.identity:
            self.held = False
            return True
        manifest = self._manifest(obj, None, acquire=False)
        manifest["spec"].pop("renewTime", None)
        res = self.kube.replace(manifest)
        if res.ok:
            self.held = False
        return res.ok

    def force_release(self) -> bool:
        """Clear the lease regardless of holder (used by the review shutdown script)."""
        obj = self._get()
        if obj is None:
            return True
        manifest = self._manifest(obj, None, acquire=False)
        manifest["spec"].pop("renewTime", None)
        return self.kube.replace(manifest).ok
