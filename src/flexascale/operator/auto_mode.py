"""
Auto mode: per-service, explainable choice between FlexaScale and native HPA.

In Auto mode the operator still computes FlexaScale's proposal for every
service, and also what native HPA would do from the same telemetry (the
Kubernetes formula ``ceil(replicas x cpu / target)`` outside the tolerance
band). An ordered rule list then decides who *owns* the service for this step:

1. ``controller_health``: no trained model, missing/stale CPU telemetry, or no
   application Lease -> HPA. FlexaScale can only own a service it can see.
2. ``policy_confidence``: the policy's probability for its action is below the
   activation threshold (or below the deactivation threshold once it owns the
   service) -> HPA.
3. ``sla_risk``: the service is over its latency SLO or above the CPU risk level,
   and HPA would add more replicas than FlexaScale proposes -> HPA. Capacity
   first: under SLA risk the more generous controller wins.
4. ``efficiency``: otherwise FlexaScale owns the service (its proposal is applied
   through the usual safety guards).

A change of owner needs the new rule result for ``dwell_steps`` consecutive
steps (hysteresis), except that ``controller_health`` and ``sla_risk`` hand to
HPA immediately (the safe direction). Ownership itself is enforced by the
operator's existing mechanism: FlexaScale freezes a service's HPA before it
scales it and restores the HPA's original bounds when it hands back, under the
application Lease, so the two controllers never act on one Deployment at once.

Every decision records the rule, the inputs it used and a one-line reason, so
the dashboard can show *why* each service is owned by whom.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AutoConfig:
    """Auto-mode rule parameters (``auto:`` in the application policy)."""

    sla_latency_ratio: float = 1.0
    """SLA risk when mean latency > ratio x the service's SLO."""
    cpu_risk_pct: float = 85.0
    """SLA risk when CPU (percent of request) is at or above this."""
    dwell_steps: int = 2
    """Consecutive steps a new owner must be chosen before it takes over (not for hand-backs to HPA on risk)."""
    hpa_target_pct: Optional[float] = None
    """CPU target used to compute HPA's recommendation; default: the policy's cpu_target_pct."""
    hpa_tolerance: float = 0.1

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AutoConfig":
        data = dict(data or {})
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown auto keys: {unknown}")
        return cls(**data)

    def validate(self) -> list[str]:
        errors = []
        if self.sla_latency_ratio <= 0:
            errors.append("auto.sla_latency_ratio must be > 0")
        if not 0 < self.cpu_risk_pct <= 1000:
            errors.append("auto.cpu_risk_pct must be in (0, 1000]")
        if self.dwell_steps < 1:
            errors.append("auto.dwell_steps must be >= 1")
        return errors


def hpa_recommendation(current: int, cpu_pct: float, target_pct: float, tolerance: float,
                       lo: int, hi: int) -> int:
    """Native HPA's recommendation for one Deployment (no stabilisation; one sync)."""
    current = max(1, int(current))
    ratio = cpu_pct / target_pct if target_pct > 0 else 1.0
    if abs(ratio - 1.0) <= tolerance:
        rec = current
    else:
        rec = int(math.ceil(current * ratio - 1e-9))
        rec = min(rec, max(2 * current, current + 4))
    return max(lo, min(hi, rec))


@dataclass
class AutoDecision:
    owner: str  # "flexascale" | "hpa"
    rule: str
    reason: str
    candidate: str
    """Owner the rules chose this step (before hysteresis)."""
    hpa_recommendation: Optional[int] = None
    flexascale_proposal: Optional[int] = None
    streak: int = 0
    inputs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AutoArbiter:
    """Keeps per-service hysteresis state and applies the rules in order."""

    def __init__(self, config: AutoConfig, cpu_target_pct: float) -> None:
        self.config = config
        self.cpu_target_pct = config.hpa_target_pct or cpu_target_pct
        self._owner: Dict[str, str] = {}
        self._pending: Dict[str, tuple[str, int]] = {}

    def owner(self, service: str) -> str:
        return self._owner.get(service, "hpa")

    def decide(
        self,
        service: str,
        *,
        model_available: bool,
        telemetry_ok: bool,
        lease_held: bool,
        confidence: float,
        activation: float,
        deactivation: float,
        current: int,
        flexascale_proposal: int,
        cpu_pct: Optional[float],
        latency_ms: Optional[float],
        slo_ms: Optional[float],
        lo: int,
        hi: int,
    ) -> AutoDecision:
        cfg = self.config
        prev = self.owner(service)
        hpa_rec = None
        if cpu_pct is not None:
            hpa_rec = hpa_recommendation(current, cpu_pct, self.cpu_target_pct, cfg.hpa_tolerance, lo, hi)
        inputs = {
            "confidence": round(float(confidence), 4), "cpu_pct": None if cpu_pct is None else round(float(cpu_pct), 1),
            "latency_ms": None if latency_ms is None else round(float(latency_ms), 1), "slo_ms": slo_ms,
            "current": current, "previous_owner": prev,
        }

        def done(owner: str, rule: str, reason: str, immediate: bool) -> AutoDecision:
            if owner == prev:
                self._pending.pop(service, None)
                final, streak = owner, 0
            elif immediate:
                self._pending.pop(service, None)
                final, streak = owner, 0
            else:
                cand, n = self._pending.get(service, (owner, 0))
                n = n + 1 if cand == owner else 1
                self._pending[service] = (owner, n)
                if n >= cfg.dwell_steps:
                    final, streak = owner, n
                    self._pending.pop(service, None)
                else:
                    final, streak = prev, n
                    reason += f" (waiting {n}/{cfg.dwell_steps} steps before switching)"
            self._owner[service] = final
            return AutoDecision(owner=final, rule=rule, reason=reason, candidate=owner, hpa_recommendation=hpa_rec,
                                flexascale_proposal=flexascale_proposal, streak=streak, inputs=inputs)

        # 1. Controller health
        if not model_available:
            return done("hpa", "controller_health", "no trained FlexaScale model loaded", True)
        if not telemetry_ok:
            return done("hpa", "controller_health", "CPU telemetry missing or stale", True)
        if not lease_held:
            return done("hpa", "controller_health", "FlexaScale does not hold the application Lease", True)
        # 2. Policy confidence (hysteresis on the threshold itself, as in the operator)
        threshold = deactivation if prev == "flexascale" else activation
        if confidence < threshold:
            return done("hpa", "policy_confidence",
                        f"policy confidence {confidence:.3f} below {threshold:.2f}", prev == "flexascale")
        # 3. SLA risk: capacity first
        at_risk_latency = latency_ms is not None and slo_ms and latency_ms > cfg.sla_latency_ratio * slo_ms
        at_risk_cpu = cpu_pct is not None and cpu_pct >= cfg.cpu_risk_pct
        if (at_risk_latency or at_risk_cpu) and hpa_rec is not None and hpa_rec > flexascale_proposal:
            why = (f"latency {latency_ms:.0f} ms > SLO {slo_ms:.0f} ms" if at_risk_latency
                   else f"CPU {cpu_pct:.0f}% >= {cfg.cpu_risk_pct:.0f}%")
            return done("hpa", "sla_risk",
                        f"{why}; HPA would scale to {hpa_rec}, FlexaScale proposes {flexascale_proposal}", True)
        # 4. Efficiency: FlexaScale
        if hpa_rec is not None and flexascale_proposal < hpa_rec:
            why = f"no SLA risk; FlexaScale proposes {flexascale_proposal} vs HPA {hpa_rec} replicas (saves capacity)"
        elif hpa_rec is not None and flexascale_proposal > hpa_rec:
            why = f"no SLA risk; FlexaScale proposes {flexascale_proposal} vs HPA {hpa_rec} replicas (scales ahead)"
        else:
            why = "no SLA risk; FlexaScale and HPA agree" if hpa_rec is not None else "no SLA risk"
        return done("flexascale", "efficiency", why, False)
