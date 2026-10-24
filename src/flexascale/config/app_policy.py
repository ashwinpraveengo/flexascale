"""
Application policy for FlexaScale.

An ``AppPolicy`` registers one Kubernetes microservice application with
FlexaScale without touching the application's source code. It selects the
target Deployments, bounds what the controller may do to them, and decides
whether FlexaScale only observes (default) or is allowed to scale.

Policies are plain YAML or JSON files (see ``config/apps/``) and are also
rendered by the Helm chart into the operator's ConfigMap.

Usage::

    from flexascale.config.app_policy import AppPolicy

    policy = AppPolicy.load("config/apps/shopping.yaml")
    errors = policy.validate()
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MODES = ("observe", "live")

DEFAULT_EXCLUDE_PATTERNS: Tuple[str, ...] = (
    r"^flexascale-.*",
    r".*prometheus.*",
    r".*grafana.*",
    r".*alertmanager.*",
    r".*kube-state-metrics.*",
)
"""Name patterns for monitoring and FlexaScale's own workloads."""

DATASTORE_IMAGE_MARKERS: Tuple[str, ...] = (
    "postgres",
    "mysql",
    "mariadb",
    "redis",
    "mongo",
    "cassandra",
    "elasticsearch",
    "opensearch",
    "kafka",
    "zookeeper",
    "rabbitmq",
    "etcd",
    "memcached",
    "clickhouse",
)
"""Container image substrings that mark stateful infrastructure (never scaled unless included)."""


@dataclass
class ServiceBounds:
    """Per-Deployment replica bounds (and optional latency SLO) overriding the application defaults."""

    min_replicas: Optional[int] = None
    max_replicas: Optional[int] = None
    slo_latency_ms: Optional[float] = None


@dataclass
class CostProfile:
    """
    Pricing assumptions for resource-cost estimation.

    When both prices are ``None`` FlexaScale reports a normalized resource-cost
    proxy (vCPU-hours + memory_weight * GiB-hours) instead of money.
    """

    currency: str = "USD"
    cpu_per_vcpu_hour: Optional[float] = None
    memory_per_gib_hour: Optional[float] = None
    memory_weight: float = 0.125
    """Weight of one GiB-hour relative to one vCPU-hour in the proxy (1 vCPU : 8 GiB)."""
    label: str = "normalized resource-cost proxy (no pricing configured)"

    @property
    def is_priced(self) -> bool:
        return self.cpu_per_vcpu_hour is not None and self.memory_per_gib_hour is not None


@dataclass
class AppPolicy:
    """Registration and safety policy for one target application."""

    name: str
    namespace: str
    label_selector: str = ""
    include: List[str] = field(default_factory=list)
    """Allowlist of Deployment names. Empty means every eligible discovered Deployment."""
    exclude: List[str] = field(default_factory=list)
    """Denylist of Deployment names."""
    exclude_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE_PATTERNS))
    exclude_datastores: bool = True
    """Skip Deployments whose images look like databases/brokers unless explicitly included."""

    mode: str = "observe"
    """'observe' computes and records decisions only; 'live' may scale Deployments."""

    min_replicas: int = 1
    max_replicas: int = 10
    max_step: int = 1
    """Maximum replica change per decision."""
    max_total_replicas: Optional[int] = None
    """App-wide replica budget across all managed Deployments; FlexaScale never scales up beyond it."""
    services: Dict[str, ServiceBounds] = field(default_factory=dict)

    cpu_target_pct: float = 70.0
    scale_down_block_cpu_pct: float = 85.0
    """Never scale down while CPU (percent of request) is at or above this value."""
    scale_down_block_memory_pct: float = 90.0
    """Never scale down while memory (percent of limit) is at or above this value."""
    slo_latency_ms: Optional[float] = 100.0
    """Per-service mean latency SLO; ``None`` disables latency checks."""

    confidence_threshold: float = 0.70
    deactivation_threshold: float = 0.60
    cooldown_seconds: float = 15.0
    scale_down_cooldown_seconds: float = 60.0
    """Minimum time between two scale-down actions on the same Deployment."""
    scale_up_cooldown_seconds: float = 0.0
    """Minimum time between two scale-up actions on the same Deployment (0 = only wait for readiness)."""
    hpa_fallback: bool = True
    """Return control to the Deployment's own HPA when FlexaScale is not confident."""
    lease_seconds: float = 30.0

    poll_interval_seconds: float = 10.0
    stale_after_seconds: float = 120.0
    prometheus_url: str = "http://localhost:9090"
    model_path: str = "models/flexascale_v3/best_model/best_model.zip"

    topology: List[Tuple[str, str]] = field(default_factory=list)
    """Optional (caller, callee) edges. Inferred from telemetry when empty."""

    cost: CostProfile = field(default_factory=CostProfile)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppPolicy":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown policy keys: {unknown}")
        kwargs = dict(data)
        if "services" in kwargs:
            kwargs["services"] = {
                name: ServiceBounds(**(bounds or {}))
                for name, bounds in (kwargs["services"] or {}).items()
            }
        if "cost" in kwargs:
            kwargs["cost"] = CostProfile(**(kwargs["cost"] or {}))
        if "topology" in kwargs:
            kwargs["topology"] = [tuple(edge) for edge in (kwargs["topology"] or [])]
        for key in ("include", "exclude", "exclude_patterns"):
            if key in kwargs and kwargs[key] is None:
                kwargs[key] = []
        return cls(**kwargs)

    @classmethod
    def load(cls, path: str | Path) -> "AppPolicy":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            import yaml

            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["topology"] = [list(edge) for edge in self.topology]
        return data

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> List[str]:
        """Return a list of human-readable problems (empty when valid)."""
        errors: List[str] = []
        if not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", self.name or ""):
            errors.append("name must be a DNS-1123 label (lowercase letters, digits, '-')")
        if not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", self.namespace or ""):
            errors.append("namespace must be a DNS-1123 label")
        if self.mode not in MODES:
            errors.append(f"mode must be one of {MODES}, got '{self.mode}'")
        if self.min_replicas < 1:
            errors.append("min_replicas must be >= 1")
        if self.max_replicas < self.min_replicas:
            errors.append("max_replicas must be >= min_replicas")
        if self.max_total_replicas is not None and self.max_total_replicas < self.min_replicas:
            errors.append("max_total_replicas must be >= min_replicas")
        if self.max_step < 1:
            errors.append("max_step must be >= 1")
        for name, bounds in self.services.items():
            lo = bounds.min_replicas if bounds.min_replicas is not None else self.min_replicas
            hi = bounds.max_replicas if bounds.max_replicas is not None else self.max_replicas
            if lo < 1 or hi < lo:
                errors.append(f"services.{name}: invalid bounds min={lo} max={hi}")
        if set(self.include) & set(self.exclude):
            errors.append(f"deployments both included and excluded: {sorted(set(self.include) & set(self.exclude))}")
        for pattern in self.exclude_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append(f"invalid exclude pattern '{pattern}': {exc}")
        if not 0.0 < self.cpu_target_pct <= 100.0:
            errors.append("cpu_target_pct must be in (0, 100]")
        if self.slo_latency_ms is not None and self.slo_latency_ms <= 0:
            errors.append("slo_latency_ms must be positive or null")
        if not 0.0 <= self.deactivation_threshold <= self.confidence_threshold <= 1.0:
            errors.append("require 0 <= deactivation_threshold <= confidence_threshold <= 1")
        if self.scale_up_cooldown_seconds < 0 or self.scale_down_cooldown_seconds < 0:
            errors.append("cooldowns must be >= 0")
        if self.poll_interval_seconds <= 0:
            errors.append("poll_interval_seconds must be positive")
        if self.lease_seconds < 2 * self.poll_interval_seconds:
            errors.append("lease_seconds must be at least twice poll_interval_seconds")
        if self.stale_after_seconds < self.poll_interval_seconds:
            errors.append("stale_after_seconds must be >= poll_interval_seconds")
        for edge in self.topology:
            if len(edge) != 2:
                errors.append(f"topology edge {edge} must have exactly two entries")
        cost = self.cost
        for label, value in (("cpu_per_vcpu_hour", cost.cpu_per_vcpu_hour), ("memory_per_gib_hour", cost.memory_per_gib_hour)):
            if value is not None and value < 0:
                errors.append(f"cost.{label} must be non-negative")
        if (cost.cpu_per_vcpu_hour is None) != (cost.memory_per_gib_hour is None):
            errors.append("cost: set both cpu_per_vcpu_hour and memory_per_gib_hour, or neither")
        return errors

    def assert_valid(self) -> None:
        errors = self.validate()
        if errors:
            raise ValueError("Invalid FlexaScale application policy:\n  - " + "\n  - ".join(errors))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def bounds_for(self, deployment: str) -> Tuple[int, int]:
        override = self.services.get(deployment)
        lo = self.min_replicas
        hi = self.max_replicas
        if override is not None:
            if override.min_replicas is not None:
                lo = override.min_replicas
            if override.max_replicas is not None:
                hi = override.max_replicas
        return lo, hi

    def slo_for(self, deployment: str) -> Optional[float]:
        override = self.services.get(deployment)
        if override is not None and override.slo_latency_ms is not None:
            return override.slo_latency_ms
        return self.slo_latency_ms

    @property
    def live(self) -> bool:
        return self.mode == "live"
