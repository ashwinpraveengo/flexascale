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
    ) -> None:
        self.config = config or SafetyConfig()
        self.mock = mock

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
        Restore dynamic HPA bounds (minReplicas=1, maxReplicas=10).

        Called during HPA fallback so Kubernetes HPA handles dynamic scaling.
        """
        min_reps = self.config.hpa_min_replicas
        max_reps = self.config.hpa_max_replicas

        logger.info(
            "[HPA] Restoring dynamic HPA bounds for '%s' (min=%d, max=%d, targetCPU=%d%%)",
            service_id,
            min_reps,
            max_reps,
            self.config.target_cpu_utilization,
        )

        if self.mock or self.config.dry_run:
            self._mock_hpa_bounds[service_id] = (min_reps, max_reps)
            return True

        hpa_name = f"{service_id}-hpa"
        patch = {
            "spec": {
                "minReplicas": min_reps,
                "maxReplicas": max_reps,
            }
        }
        return self._patch_hpa(hpa_name, patch)

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

        hpa_name = f"{service_id}-hpa"
        patch = {
            "spec": {
                "minReplicas": target_replicas,
                "maxReplicas": target_replicas,
            }
        }
        return self._patch_hpa(hpa_name, patch)

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

        cmd = [
            "kubectl",
            "scale",
            f"deployment/{service_id}",
            f"--replicas={target_replicas}",
            "-n",
            self.config.namespace,
        ]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=10.0,
            )
            logger.debug("kubectl scale result: %s", res.stdout.strip())
            return True
        except Exception as exc:
            logger.error("Failed to scale deployment '%s': %s", service_id, exc)
            return False

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

        for hpa_name in (f"{service_id}-hpa", service_id):
            cmd = [
                "kubectl",
                "get",
                f"hpa/{hpa_name}",
                "-n",
                self.config.namespace,
                "-o",
                "json",
            ]
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5.0,
                )
                data = json.loads(res.stdout)
                spec = data.get("spec", {})
                return (
                    int(spec.get("minReplicas", self.config.hpa_min_replicas)),
                    int(spec.get("maxReplicas", self.config.hpa_max_replicas)),
                )
            except Exception:
                continue

        return (self.config.hpa_min_replicas, self.config.hpa_max_replicas)

    def _patch_hpa(self, hpa_name: str, patch_data: dict[str, Any]) -> bool:
        """Patch an HPA resource via kubectl, trying both {service_id}-hpa and {service_id}."""
        candidate_names = [hpa_name]
        if hpa_name.endswith("-hpa"):
            candidate_names.append(hpa_name[:-4])
        else:
            candidate_names.append(f"{hpa_name}-hpa")

        for name in candidate_names:
            cmd = [
                "kubectl",
                "patch",
                f"hpa/{name}",
                "-n",
                self.config.namespace,
                "--type=merge",
                "-p",
                json.dumps(patch_data),
            ]
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5.0,
                )
                if res.returncode == 0:
                    return True
            except Exception:
                continue

        logger.debug("Failed to patch HPA candidate names %s in namespace %s", candidate_names, self.config.namespace)
        return False
