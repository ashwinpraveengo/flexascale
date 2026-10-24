"""
Resource-efficiency and cost accounting for autoscaling experiments.

Inputs are time-ordered telemetry samples recorded during an experiment.
Each sample holds, per Deployment, the ready replica count, the per-pod CPU
and memory *requests* (allocation) and the observed CPU cores / memory bytes
in use. Integration uses the left Riemann sum: a sample's state is assumed to
hold until the next sample.

Terminology (kept separate in every report):
    allocated   requested CPU/memory of ready replicas (what a scheduler reserves)
    observed    CPU/memory actually used, from cAdvisor
    replica-h   ready replicas x hours
    estimated   allocated resources x configured prices (only if prices are set)
    proxy       vCPU-hours + memory_weight x GiB-hours (when no prices are set)
Actual cloud billing is never computed here; Minikube has no bill.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

from flexascale.config.app_policy import CostProfile

GIB = 1024.0 ** 3


@dataclass
class ResourceSummary:
    duration_s: float
    replica_hours: float
    avg_ready_replicas: float
    peak_ready_replicas: int
    allocated_vcpu_hours: float
    allocated_gib_hours: float
    used_vcpu_hours: Optional[float]
    used_gib_hours: Optional[float]
    cpu_allocation_efficiency_pct: Optional[float]
    """Observed CPU / allocated CPU over the run."""
    memory_allocation_efficiency_pct: Optional[float]
    cost_model: str
    """'priced' or 'proxy'."""
    cost_currency: Optional[str]
    estimated_cost: Optional[float]
    resource_cost_proxy: float
    cost_label: str

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for k, v in out.items():
            if isinstance(v, float):
                out[k] = round(v, 6)
        return out


def summarize_resources(samples: Sequence[Dict[str, Any]], cost: Optional[CostProfile] = None) -> ResourceSummary:
    """
    Args:
        samples: [{"t": epoch_seconds, "services": {name: {"ready": int,
                   "cpu_request_cores": float, "memory_request_bytes": float,
                   "cpu_cores": float|None, "memory_bytes": float|None}}}, ...]
    """
    cost = cost or CostProfile()
    ordered = sorted(samples, key=lambda s: s["t"])
    duration = (ordered[-1]["t"] - ordered[0]["t"]) if len(ordered) > 1 else 0.0

    rep_s = cpu_alloc_s = mem_alloc_s = 0.0
    cpu_used_s = mem_used_s = 0.0
    cpu_used_known = mem_used_known = True
    peak = 0
    for cur, nxt in zip(ordered, ordered[1:]):
        dt = max(0.0, nxt["t"] - cur["t"])
        total_ready = 0
        for svc in cur["services"].values():
            ready = int(svc.get("ready") or 0)
            total_ready += ready
            rep_s += ready * dt
            cpu_alloc_s += ready * float(svc.get("cpu_request_cores") or 0.0) * dt
            mem_alloc_s += ready * float(svc.get("memory_request_bytes") or 0.0) * dt
            if svc.get("cpu_cores") is None:
                cpu_used_known = False
            else:
                cpu_used_s += float(svc["cpu_cores"]) * dt
            if svc.get("memory_bytes") is None:
                mem_used_known = False
            else:
                mem_used_s += float(svc["memory_bytes"]) * dt
        peak = max(peak, total_ready)
    if ordered:
        peak = max(peak, sum(int(s.get("ready") or 0) for s in ordered[-1]["services"].values()))

    hours = 3600.0
    alloc_cpu_h = cpu_alloc_s / hours
    alloc_gib_h = mem_alloc_s / GIB / hours
    used_cpu_h = cpu_used_s / hours if cpu_used_known and duration > 0 else None
    used_gib_h = mem_used_s / GIB / hours if mem_used_known and duration > 0 else None

    proxy = alloc_cpu_h + cost.memory_weight * alloc_gib_h
    if cost.is_priced:
        estimated = alloc_cpu_h * cost.cpu_per_vcpu_hour + alloc_gib_h * cost.memory_per_gib_hour
        model, currency = "priced", cost.currency
        label = (
            f"estimated {cost.currency} at {cost.cpu_per_vcpu_hour}/vCPU-h and "
            f"{cost.memory_per_gib_hour}/GiB-h of requested resources (assumption, not a bill)"
        )
    else:
        estimated, model, currency = None, "proxy", None
        label = f"resource-cost proxy = vCPU-h + {cost.memory_weight} x GiB-h of requested resources (unitless)"

    return ResourceSummary(
        duration_s=duration,
        replica_hours=rep_s / hours,
        avg_ready_replicas=(rep_s / duration) if duration > 0 else 0.0,
        peak_ready_replicas=peak,
        allocated_vcpu_hours=alloc_cpu_h,
        allocated_gib_hours=alloc_gib_h,
        used_vcpu_hours=used_cpu_h,
        used_gib_hours=used_gib_h,
        cpu_allocation_efficiency_pct=(100.0 * used_cpu_h / alloc_cpu_h) if used_cpu_h is not None and alloc_cpu_h > 0 else None,
        memory_allocation_efficiency_pct=(100.0 * used_gib_h / alloc_gib_h) if used_gib_h is not None and alloc_gib_h > 0 else None,
        cost_model=model,
        cost_currency=currency,
        estimated_cost=estimated,
        resource_cost_proxy=proxy,
        cost_label=label,
    )


def percent_change(baseline: Optional[float], candidate: Optional[float]) -> Optional[float]:
    """(candidate - baseline) / baseline * 100, only for a strictly positive baseline."""
    if baseline is None or candidate is None or baseline <= 0:
        return None
    return 100.0 * (candidate - baseline) / baseline


def scaling_stability(replica_series: Dict[str, List[int]]) -> Dict[str, int]:
    """Count desired-replica changes and direction reversals (oscillations) per run."""
    changes = reversals = 0
    for series in replica_series.values():
        last_dir = 0
        for a, b in zip(series, series[1:]):
            if b == a:
                continue
            changes += 1
            direction = 1 if b > a else -1
            if last_dir and direction != last_dir:
                reversals += 1
            last_dir = direction
    return {"scaling_events": changes, "oscillations": reversals}
