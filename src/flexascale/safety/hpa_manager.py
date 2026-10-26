"""
Kubernetes HorizontalPodAutoscaler (HPA) Manager for FlexaScale.

Handles safe interaction with Kubernetes HPAs and Deployments:
- Enforces dynamic HPA scaling in fallback mode
- Clamps/freezes HPA bounds during RL ownership to prevent concurrent controller conflicts
- Executes deployment scale commands safely with timeout enforcement
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from flexascale.config.safety_config import SafetyConfig
from flexascale.discovery.workloads import (
    ANNOTATION_FROZEN_BY,
    ANNOTATION_ORIGINAL_BEHAVIOR,
    ANNOTATION_ORIGINAL_MAX,
    ANNOTATION_ORIGINAL_METRICS,
    ANNOTATION_ORIGINAL_MIN,
    ANNOTATION_ORIGINAL_REPLICAS,
    HPAInfo,
)
from flexascale.k8s.kube import Kube

logger = logging.getLogger(__name__)


class HPAManager:
    """
    Manages Kubernetes HPA bounds and Deployment replica scaling.

    Supports live cluster interaction via `kubectl` and mock execution for testing.
    """

    def __init__(
        self,
        config: SafetyConfig | None = None,
        mock: bool = False,
        kube: Kube | None = None,
        holder: str = "flexascale",
    ) -> None:
        self.config = config or SafetyConfig()
        self.mock = mock
        self.kube = kube or Kube()
        self.holder = holder
        self.last_note: str = ""

        # In-memory state for mock mode / unit tests
        self._mock_replicas: dict[str, int] = {
            sid: self.config.hpa_min_replicas for sid in self.config.service_names
        }
        self._mock_hpa_bounds: dict[str, tuple[int, int]] = {
            sid: (self.config.hpa_min_replicas, self.config.hpa_max_replicas)
            for sid in self.config.service_names
        }

    def ensure_hpa_active(self, service_id: str) -> bool:
        """
        Return scaling to the Deployment's native HPA.

        Live mode restores the HPA's *original* min/max bounds recorded when
        FlexaScale froze it (annotations on the HPA). An HPA FlexaScale never
        froze is left untouched. Mock mode resets to the configured bounds.
        """
        min_reps = self.config.hpa_min_replicas
        max_reps = self.config.hpa_max_replicas

        if self.mock or self.config.dry_run:
            logger.info(
                "[HPA] Restoring dynamic HPA bounds for '%s' (min=%d, max=%d, targetCPU=%d%%)",
                service_id,
                min_reps,
                max_reps,
                self.config.target_cpu_utilization,
            )
            self._mock_hpa_bounds[service_id] = (min_reps, max_reps)
            return True

        hpa = self.find_hpa(service_id)
        if hpa is None:
            self.last_note = "no_hpa"
            return True
        return self.restore_hpa(hpa)

    def freeze_hpa(self, service_id: str, target_replicas: int) -> bool:
        """
        Freeze HPA by clamping minReplicas == maxReplicas == target_replicas.

        This guarantees that the native Kubernetes HPA controller will not fight or
        override the RL controller's scaling decisions while RL holds the lock.
        """
        logger.info(
            "[HPA] Freezing HPA conflicts for '%s' to target replicas (min=%d, max=%d)",
            service_id,
            target_replicas,
            target_replicas,
        )

        if self.mock or self.config.dry_run:
            self._mock_hpa_bounds[service_id] = (target_replicas, target_replicas)
            return True

        hpa = self.find_hpa(service_id)
        if hpa is None:
            # No native autoscaler targets this Deployment, so there is nothing to conflict with,
            # but nothing would undo our scaling either: record the starting count for restore.
            if not self._record_original_replicas(service_id):
                return False
            self.last_note = "no_hpa"
            return True
        annotations = {ANNOTATION_FROZEN_BY: self.holder}
        if not hpa.frozen:
            annotations[ANNOTATION_ORIGINAL_MIN] = str(hpa.min_replicas)
            annotations[ANNOTATION_ORIGINAL_MAX] = str(hpa.max_replicas)
        patch = {
            "metadata": {"annotations": annotations},
            "spec": {"minReplicas": int(target_replicas), "maxReplicas": int(target_replicas)},
        }
        res = self.kube.patch("hpa", hpa.name, self.config.namespace, patch)
        if not res.ok:
            logger.error("[HPA] Failed to freeze HPA '%s': %s", hpa.name, res.stderr)
        self.last_note = "frozen" if res.ok else f"freeze_failed: {res.stderr[:120]}"
        return res.ok

    def scale_deployment(self, service_id: str, target_replicas: int) -> bool:
        """
        Apply replica scaling action directly to the Kubernetes Deployment.
        """
        logger.info(
            "[RL] Applying scale action to '%s': %d replicas",
            service_id,
            target_replicas,
        )

        if self.mock or self.config.dry_run:
            self._mock_replicas[service_id] = target_replicas
            return True

        res = self.kube.scale(service_id, self.config.namespace, target_replicas)
        if not res.ok:
            logger.error("Failed to scale deployment '%s': %s", service_id, res.stderr)
        return res.ok

    def get_deployment_replicas(self, service_id: str) -> int:
        """Query current running replicas for a deployment."""
        if self.mock or self.config.dry_run:
            return self._mock_replicas.setdefault(service_id, self.config.hpa_min_replicas)

        cmd = [
            "kubectl",
            "get",
            f"deployment/{service_id}",
            "-n",
            self.config.namespace,
            "-o",
            "jsonpath={.spec.replicas}",
        ]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=5.0,
            )
            val = res.stdout.strip()
            return int(val) if val.isdigit() else self.config.hpa_min_replicas
        except Exception as exc:
            logger.warning("Could not read replicas for '%s': %s", service_id, exc)
            return self.config.hpa_min_replicas

    def get_hpa_bounds(self, service_id: str) -> tuple[int, int]:
        """Query (minReplicas, maxReplicas) from the HPA resource."""
        if self.mock or self.config.dry_run:
            return self._mock_hpa_bounds.setdefault(
                service_id,
                (self.config.hpa_min_replicas, self.config.hpa_max_replicas),
            )

        hpa = self.find_hpa(service_id)
        if hpa is None:
            return (self.config.hpa_min_replicas, self.config.hpa_max_replicas)
        return (hpa.min_replicas, hpa.max_replicas)

    # ------------------------------------------------------------------
    # Live helpers
    # ------------------------------------------------------------------

    def find_hpa(self, service_id: str) -> HPAInfo | None:
        """Locate the HPA whose scaleTargetRef points at Deployment ``service_id``."""
        items = self.kube.list_items("hpa", self.config.namespace)
        for obj in items or []:
            ref = obj.get("spec", {}).get("scaleTargetRef", {})
            if ref.get("kind") == "Deployment" and ref.get("name") == service_id:
                return HPAInfo.from_object(obj)
        return None

    def restore_hpa(self, hpa: HPAInfo) -> bool:
        """Restore original bounds of an HPA frozen by FlexaScale and drop the markers."""
        if not hpa.frozen:
            return True
        patch = {
            "metadata": {
                "annotations": {
                    ANNOTATION_ORIGINAL_MIN: None,
                    ANNOTATION_ORIGINAL_MAX: None,
                    ANNOTATION_FROZEN_BY: None,
                }
            },
            "spec": {
                "minReplicas": int(hpa.original_min_replicas),
                "maxReplicas": int(hpa.original_max_replicas or hpa.original_min_replicas),
            },
        }
        res = self.kube.patch("hpa", hpa.name, self.config.namespace, patch)
        if res.ok:
            logger.info(
                "[HPA] Restored '%s' to original bounds min=%s max=%s",
                hpa.name,
                hpa.original_min_replicas,
                hpa.original_max_replicas,
            )
        else:
            logger.error("[HPA] Failed to restore '%s': %s", hpa.name, res.stderr)
        self.last_note = "restored" if res.ok else f"restore_failed: {res.stderr[:120]}"
        return res.ok

    def restore_all_frozen(self) -> list[str]:
        """Restore every HPA in the namespace that carries FlexaScale freeze markers."""
        restored = []
        if self.mock or self.config.dry_run:
            return restored
        for obj in self.kube.list_items("hpa", self.config.namespace) or []:
            hpa = HPAInfo.from_object(obj)
            if hpa.frozen and self.restore_hpa(hpa):
                restored.append(hpa.name)
        return restored

    def set_scale_down_window(self, seconds: int) -> list[str]:
        """
        Set every HPA's scale-down stabilisation window (native HPA default 300 s).

        The original ``spec.behavior`` is stored on the HPA first, so
        :meth:`restore_all_behavior` can put it back even from another process.
        """
        changed = []
        if self.mock or self.config.dry_run:
            return changed
        for obj in self.kube.list_items("hpa", self.config.namespace) or []:
            meta, spec = obj.get("metadata", {}), obj.get("spec", {})
            annotations = {}
            if ANNOTATION_ORIGINAL_BEHAVIOR not in (meta.get("annotations") or {}):
                annotations[ANNOTATION_ORIGINAL_BEHAVIOR] = json.dumps(spec.get("behavior"))
            patch = {"spec": {"behavior": {"scaleDown": {"stabilizationWindowSeconds": int(seconds)}}}}
            if annotations:
                patch["metadata"] = {"annotations": annotations}
            res = self.kube.patch("hpa", meta["name"], self.config.namespace, patch)
            if res.ok:
                changed.append(meta["name"])
            else:
                logger.error("[HPA] Failed to set scale-down window on '%s': %s", meta["name"], res.stderr)
        return changed

    def restore_all_behavior(self) -> list[str]:
        """Restore the ``spec.behavior`` recorded by :meth:`set_scale_down_window` and drop the marker."""
        restored = []
        if self.mock or self.config.dry_run:
            return restored
        for obj in self.kube.list_items("hpa", self.config.namespace) or []:
            meta = obj.get("metadata", {})
            raw = (meta.get("annotations") or {}).get(ANNOTATION_ORIGINAL_BEHAVIOR)
            if raw is None:
                continue
            try:
                original = json.loads(raw)
            except ValueError:
                original = None
            # Clear first: a merge patch would otherwise keep fields the original did not have.
            res = self.kube.patch("hpa", meta["name"], self.config.namespace, {"spec": {"behavior": None}})
            if res.ok and original:
                res = self.kube.patch("hpa", meta["name"], self.config.namespace, {"spec": {"behavior": original}})
            if res.ok:
                res = self.kube.patch("hpa", meta["name"], self.config.namespace,
                                      {"metadata": {"annotations": {ANNOTATION_ORIGINAL_BEHAVIOR: None}}})
            if res.ok:
                restored.append(meta["name"])
            else:
                logger.error("[HPA] Failed to restore behavior of '%s': %s", meta["name"], res.stderr)
        return restored

    def set_cpu_target(self, pct: int) -> list[str]:
        """
        Set every HPA's CPU utilisation target (percent of the CPU request) for one run.

        The original ``spec.metrics`` is stored on the HPA first, so :meth:`restore_all_metrics`
        can put it back even from another process. HPAs without a CPU resource metric are left alone.
        """
        changed = []
        if self.mock or self.config.dry_run:
            return changed
        for obj in self.kube.list_items("hpa", self.config.namespace) or []:
            meta, spec = obj.get("metadata", {}), obj.get("spec", {})
            metrics = spec.get("metrics") or []
            new_metrics, found = [], False
            for m in metrics:
                m = json.loads(json.dumps(m))
                res = m.get("resource") or {}
                if m.get("type") == "Resource" and res.get("name") == "cpu":
                    res["target"] = {"type": "Utilization", "averageUtilization": int(pct)}
                    found = True
                new_metrics.append(m)
            if not found:
                continue
            patch: dict[str, Any] = {"spec": {"metrics": new_metrics}}  # a merge patch replaces the whole list
            if ANNOTATION_ORIGINAL_METRICS not in (meta.get("annotations") or {}):
                patch["metadata"] = {"annotations": {ANNOTATION_ORIGINAL_METRICS: json.dumps(metrics)}}
            res = self.kube.patch("hpa", meta["name"], self.config.namespace, patch)
            if res.ok:
                changed.append(meta["name"])
            else:
                logger.error("[HPA] Failed to set the CPU target on '%s': %s", meta["name"], res.stderr)
        return changed

    def restore_all_metrics(self) -> list[str]:
        """Restore the ``spec.metrics`` recorded by :meth:`set_cpu_target` and drop the marker."""
        restored = []
        if self.mock or self.config.dry_run:
            return restored
        for obj in self.kube.list_items("hpa", self.config.namespace) or []:
            meta = obj.get("metadata", {})
            raw = (meta.get("annotations") or {}).get(ANNOTATION_ORIGINAL_METRICS)
            if raw is None:
                continue
            try:
                original = json.loads(raw)
            except ValueError:
                logger.error("[HPA] Unreadable original metrics on '%s'; left for manual repair", meta["name"])
                continue
            if not isinstance(original, list) or not original:
                logger.error("[HPA] Original metrics on '%s' are empty; left for manual repair", meta["name"])
                continue
            res = self.kube.patch("hpa", meta["name"], self.config.namespace,
                                  {"spec": {"metrics": original},
                                   "metadata": {"annotations": {ANNOTATION_ORIGINAL_METRICS: None}}})
            if res.ok:
                restored.append(meta["name"])
            else:
                logger.error("[HPA] Failed to restore metrics of '%s': %s", meta["name"], res.stderr)
        return restored

    def _record_original_replicas(self, service_id: str) -> bool:
        """Annotate an HPA-less Deployment with its replica count, once, before we first scale it."""
        dep = self.kube.get_json("deployment", self.config.namespace, name=service_id)
        if dep is None:
            self.last_note = "record_failed: deployment not readable"
            return False
        if ANNOTATION_ORIGINAL_REPLICAS in (dep.get("metadata", {}).get("annotations") or {}):
            return True
        replicas = int(dep.get("spec", {}).get("replicas", 1))
        patch = {"metadata": {"annotations": {ANNOTATION_ORIGINAL_REPLICAS: str(replicas),
                                              ANNOTATION_FROZEN_BY: self.holder}}}
        res = self.kube.patch("deployment", service_id, self.config.namespace, patch)
        if not res.ok:
            logger.error("[HPA] Failed to record original replicas of '%s': %s", service_id, res.stderr)
            self.last_note = f"record_failed: {res.stderr[:120]}"
        return res.ok

    def restore_unmanaged_replicas(self) -> list[str]:
        """
        Scale every Deployment FlexaScale scaled without an HPA back to its recorded count.

        Called on shutdown only: mid-run handbacks keep the current count, since
        dropping replicas under load with no autoscaler to catch it is unsafe.
        """
        restored: list[str] = []
        if self.mock or self.config.dry_run:
            return restored
        for dep in self.kube.list_items("deployment", self.config.namespace) or []:
            meta = dep.get("metadata", {})
            original = (meta.get("annotations") or {}).get(ANNOTATION_ORIGINAL_REPLICAS)
            if original is None or not str(original).isdigit():
                continue
            name = meta["name"]
            if int(dep.get("spec", {}).get("replicas", 0)) != int(original):
                if not self.kube.scale(name, self.config.namespace, int(original)).ok:
                    logger.error("[HPA] Failed to restore '%s' to %s replicas", name, original)
                    continue
            patch = {"metadata": {"annotations": {ANNOTATION_ORIGINAL_REPLICAS: None, ANNOTATION_FROZEN_BY: None}}}
            if self.kube.patch("deployment", name, self.config.namespace, patch).ok:
                logger.info("[HPA] Restored Deployment '%s' (no HPA) to %s replicas", name, original)
                restored.append(name)
        return restored
