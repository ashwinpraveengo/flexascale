"""
Policy-driven workload discovery.

Lists the Deployments of one target namespace, applies the application
policy (label selector, allow/deny lists, name patterns, datastore exclusion)
and attaches each Deployment's HorizontalPodAutoscaler, found through the
HPA's ``scaleTargetRef`` rather than by naming convention.

Nothing outside the selected namespace is ever considered, and nothing is
selected implicitly when the policy has an allowlist.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from flexascale.config.app_policy import DATASTORE_IMAGE_MARKERS, AppPolicy
from flexascale.k8s.kube import Kube, parse_cpu, parse_memory

logger = logging.getLogger(__name__)

ANNOTATION_ORIGINAL_MIN = "flexascale.io/original-min-replicas"
ANNOTATION_ORIGINAL_MAX = "flexascale.io/original-max-replicas"
ANNOTATION_FROZEN_BY = "flexascale.io/frozen-by"
# Set on a Deployment with no HPA before FlexaScale first scales it; consumed on restore.
ANNOTATION_ORIGINAL_REPLICAS = "flexascale.io/original-replicas"
LABEL_EXCLUDE = "flexascale.io/exclude"


@dataclass
class HPAInfo:
    name: str
    min_replicas: int
    max_replicas: int
    current_replicas: Optional[int] = None
    desired_replicas: Optional[int] = None
    original_min_replicas: Optional[int] = None
    original_max_replicas: Optional[int] = None
    frozen_by: Optional[str] = None

    @property
    def frozen(self) -> bool:
        return self.original_min_replicas is not None

    @classmethod
    def from_object(cls, obj: Dict[str, Any]) -> "HPAInfo":
        meta = obj.get("metadata", {})
        ann = meta.get("annotations", {}) or {}
        spec = obj.get("spec", {})
        status = obj.get("status", {})

        def _int(v: Any) -> Optional[int]:
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        return cls(
            name=meta.get("name", ""),
            min_replicas=int(spec.get("minReplicas", 1)),
            max_replicas=int(spec.get("maxReplicas", 1)),
            current_replicas=_int(status.get("currentReplicas")),
            desired_replicas=_int(status.get("desiredReplicas")),
            original_min_replicas=_int(ann.get(ANNOTATION_ORIGINAL_MIN)),
            original_max_replicas=_int(ann.get(ANNOTATION_ORIGINAL_MAX)),
            frozen_by=ann.get(ANNOTATION_FROZEN_BY),
        )


@dataclass
class WorkloadInfo:
    name: str
    namespace: str
    desired_replicas: int
    ready_replicas: int
    available_replicas: int
    labels: Dict[str, str] = field(default_factory=dict)
    images: List[str] = field(default_factory=list)
    cpu_request_cores: float = 0.0
    """Sum of container CPU requests for one pod."""
    memory_request_bytes: float = 0.0
    memory_limit_bytes: float = 0.0
    hpa: Optional[HPAInfo] = None
    eligible: bool = True
    reason: str = "eligible"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["hpa"] = asdict(self.hpa) if self.hpa else None
        return data


def _pod_resources(template_spec: Dict[str, Any]) -> tuple[float, float, float]:
    cpu = mem_req = mem_lim = 0.0
    for c in template_spec.get("containers", []) or []:
        res = c.get("resources", {}) or {}
        req = res.get("requests", {}) or {}
        lim = res.get("limits", {}) or {}
        cpu += parse_cpu(req.get("cpu"))
        mem_req += parse_memory(req.get("memory"))
        mem_lim += parse_memory(lim.get("memory"))
    return cpu, mem_req, mem_lim


class WorkloadDiscovery:
    """Discovers the Deployments an ``AppPolicy`` makes eligible for scaling."""

    def __init__(self, policy: AppPolicy, kube: Optional[Kube] = None, cache_ttl_seconds: float = 5.0) -> None:
        self.policy = policy
        self.kube = kube or Kube()
        self.cache_ttl = cache_ttl_seconds
        self._patterns = [re.compile(p) for p in policy.exclude_patterns]
        self._cache: Optional[List[WorkloadInfo]] = None
        self._cache_time = 0.0
        self.last_error: Optional[str] = None

    def _eligibility(self, name: str, labels: Dict[str, str], images: List[str]) -> tuple[bool, str]:
        p = self.policy
        if name in p.exclude:
            return False, "denylisted"
        if p.include:
            return (True, "allowlisted") if name in p.include else (False, "not in allowlist")
        if str(labels.get(LABEL_EXCLUDE, "")).lower() == "true":
            return False, f"label {LABEL_EXCLUDE}=true"
        for pattern in self._patterns:
            if pattern.search(name):
                return False, f"matches exclude pattern '{pattern.pattern}'"
        if p.exclude_datastores:
            for image in images:
                lowered = image.lower()
                for marker in DATASTORE_IMAGE_MARKERS:
                    if marker in lowered:
                        return False, f"datastore image ({marker})"
        return True, "eligible"

    def list_all(self, force_refresh: bool = False) -> List[WorkloadInfo]:
        """All Deployments matching the selector, each marked eligible or not."""
        now = time.time()
        if not force_refresh and self._cache is not None and now - self._cache_time < self.cache_ttl:
            return list(self._cache)

        ns = self.policy.namespace
        deployments = self.kube.list_items("deployments", ns, selector=self.policy.label_selector)
        if deployments is None:
            self.last_error = f"cannot list deployments in namespace '{ns}'"
            return list(self._cache or [])
        hpas = self.kube.list_items("hpa", ns) or []

        hpa_by_target: Dict[str, HPAInfo] = {}
        for obj in hpas:
            ref = obj.get("spec", {}).get("scaleTargetRef", {})
            if ref.get("kind") == "Deployment" and ref.get("name"):
                hpa_by_target[ref["name"]] = HPAInfo.from_object(obj)

        workloads: List[WorkloadInfo] = []
        for dep in deployments:
            meta = dep.get("metadata", {})
            name = meta.get("name", "")
            spec = dep.get("spec", {})
            status = dep.get("status", {})
            template = spec.get("template", {}).get("spec", {})
            images = [c.get("image", "") for c in template.get("containers", []) or []]
            labels = meta.get("labels", {}) or {}
            cpu, mem_req, mem_lim = _pod_resources(template)
            eligible, reason = self._eligibility(name, labels, images)
            workloads.append(
                WorkloadInfo(
                    name=name,
                    namespace=ns,
                    desired_replicas=int(spec.get("replicas", 0) or 0),
                    ready_replicas=int(status.get("readyReplicas", 0) or 0),
                    available_replicas=int(status.get("availableReplicas", 0) or 0),
                    labels=labels,
                    images=images,
                    cpu_request_cores=cpu,
                    memory_request_bytes=mem_req,
                    memory_limit_bytes=mem_lim,
                    hpa=hpa_by_target.get(name),
                    eligible=eligible,
                    reason=reason,
                )
            )

        missing = [n for n in self.policy.include if n not in {w.name for w in workloads}]
        if missing:
            logger.warning("[DISCOVERY] Allowlisted deployments not found in '%s': %s", ns, missing)

        workloads.sort(key=lambda w: w.name)
        self._cache = workloads
        self._cache_time = now
        self.last_error = None
        return list(workloads)

    def discover(self, force_refresh: bool = False) -> List[WorkloadInfo]:
        """Eligible Deployments only, sorted by name (deterministic node order)."""
        return [w for w in self.list_all(force_refresh) if w.eligible]

    def names(self, force_refresh: bool = False) -> List[str]:
        return [w.name for w in self.discover(force_refresh)]

    def get(self, name: str) -> Optional[WorkloadInfo]:
        for w in self.list_all():
            if w.name == name:
                return w
        return None
