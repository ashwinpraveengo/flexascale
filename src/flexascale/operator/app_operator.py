"""
Policy-driven FlexaScale operator for one registered application.

Control loop (one ``step()``):

1. Discover eligible Deployments (``WorkloadDiscovery``).
2. Collect live telemetry (``WorkloadMetricsClient``), flag missing/stale data.
3. Build per-service observations in the model's observation version:
   v1 ``[cpu%, mem%, replicas, rps, latency_ms]`` or v2 (unit-free)
   ``[cpu/request, mem/limit, replicas/max, rps trend over ~60 s, latency/SLO]``.
4. Build/refresh the dependency graph (policy topology or observed traffic).
5. Evaluate the trained PPO + GNN policy (``PolicyRuntime``).
6. Validate each proposal with safety guards and confidence hysteresis.
7. In ``live`` mode only: freeze the Deployment's HPA, then scale.
8. Record the *proposed* and the *applied* outcome separately (JSON lines).

Observation-only (``mode: observe``) is the default: every decision is
computed and logged, nothing in the cluster is modified. Live mode requires a
valid policy and the application's controller Lease; losing the Lease returns
every Deployment to its HPA and drops back to observation.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from flexascale.config.app_policy import AppPolicy
from flexascale.config.safety_config import SafetyConfig
from flexascale.discovery.workloads import WorkloadDiscovery, WorkloadInfo
from flexascale.k8s.kube import Kube
from flexascale.metrics.workload_metrics import WorkloadMetrics, WorkloadMetricsClient
from flexascale.operator.auto_mode import AutoArbiter, AutoConfig, hpa_recommendation
from flexascale.rl.features_v3 import FeatureTracker
from flexascale.rl.policy_runtime import PolicyOutput, PolicyRuntime
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lease import ControllerLease
from flexascale.safety.lock import ControlMode, ScalingLockManager
from flexascale.simulator.dependency_env import v2_features
from flexascale.state.graph_inference import LiveGraphInference

logger = logging.getLogger(__name__)

ACTION_LABELS = {0: "scale_down", 1: "hold", 2: "scale_up"}
HEURISTIC_DELTAS = [-1, 0, 1]


def action_label(delta: int) -> str:
    """'scale_up' / 'hold' / 'scale_down', with the size when it is more than one replica."""
    if delta == 0:
        return "hold"
    name = "scale_up" if delta > 0 else "scale_down"
    return name if abs(delta) == 1 else f"{name}_{abs(delta)}"
TREND_LOOKBACK_SECONDS = 60.0
"""v2 models were trained on one-minute trace steps: the rate trend compares with ~60 s ago."""


def heuristic_actions(features: Dict[str, np.ndarray], cpu_target: float) -> PolicyOutput:
    """CPU-threshold rule (HPA-like). Used only when no trained model is available."""
    services = sorted(features)
    actions, confs = [], []
    for s in services:
        cpu = float(features[s][0])
        if cpu > cpu_target * 1.1:
            actions.append(2)
        elif cpu < cpu_target * 0.9:
            actions.append(0)
        else:
            actions.append(1)
        confs.append(1.0)
    return PolicyOutput(actions, confs, mode="heuristic_cpu_threshold", windows=[[s] for s in services])


@dataclass
class StepResult:
    step: int
    timestamp: float
    mode: str
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


class AppOperator:
    def __init__(
        self,
        policy: AppPolicy,
        kube: Optional[Kube] = None,
        metrics: Optional[WorkloadMetricsClient] = None,
        runtime: Optional[PolicyRuntime] = None,
        decision_log: Optional[str] = None,
        status_file: Optional[str] = None,
        identity: Optional[str] = None,
        load_model: bool = True,
        auto: bool = False,
    ) -> None:
        policy.assert_valid()
        self.policy = policy
        self.arbiter: Optional[AutoArbiter] = (
            AutoArbiter(AutoConfig.from_dict(policy.auto), policy.cpu_target_pct) if auto else None)
        self.auto_state: Dict[str, Dict[str, Any]] = {}
        self.kube = kube or Kube()
        self.discovery = WorkloadDiscovery(policy, kube=self.kube)
        self.metrics = metrics or WorkloadMetricsClient(
            policy.prometheus_url, stale_after_seconds=policy.stale_after_seconds
        )
        self.runtime = runtime
        self.model_error: Optional[str] = None
        self.rule: Dict[str, Any] = dict(policy.controller_rule or {})
        """A hand-written rule replaces the model (attribution arm, docs/POLICY_V7.md §3.2)."""
        self.tracker: Optional[FeatureTracker] = None
        if self.runtime is None and load_model and not self.rule:
            try:
                self.runtime = PolicyRuntime(policy.model_path)
            except Exception as exc:
                self.model_error = f"{type(exc).__name__}: {exc}"
                logger.error("[OPERATOR] Trained model unavailable (%s); decisions use the CPU heuristic.", exc)

        self.safety_config = SafetyConfig(
            confidence_threshold=policy.confidence_threshold,
            deactivation_threshold=policy.deactivation_threshold,
            cooldown_seconds=policy.cooldown_seconds,
            lock_timeout_seconds=policy.lease_seconds,
            lock_configmap_name=f"flexascale-{policy.name}-ownership",
            namespace=policy.namespace,
            label_selector=policy.label_selector,
            hpa_min_replicas=policy.min_replicas,
            hpa_max_replicas=policy.max_replicas,
            target_cpu_utilization=int(policy.cpu_target_pct),
            dry_run=not policy.live,
        )
        self.lock_manager = ScalingLockManager(self.safety_config, sync_k8s=policy.live, kube=self.kube)
        self.hpa = HPAManager(self.safety_config, mock=not policy.live, kube=self.kube, holder=f"flexascale-{policy.name}")
        self.lease = ControllerLease(policy.namespace, policy.name, identity=identity, duration_seconds=policy.lease_seconds, kube=self.kube)
        self.graph = LiveGraphInference(services=[], initial_edges=[])

        self.decision_log = Path(decision_log) if decision_log else None
        self.status_file = Path(status_file) if status_file else None
        self.step_count = 0
        self._planned_total = 0
        self.effective_mode = "observe"
        self._last_fallback: Dict[str, float] = {}
        self._last_scale_down: Dict[str, float] = {}
        self._last_scale_up: Dict[str, float] = {}
        self._rps_history: Dict[str, deque] = {}
        self._running = False
        self._stop = threading.Event()
        self.last_result: Optional[StepResult] = None
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> Dict[str, Any]:
        """Validate prerequisites and, in live mode, take the controller Lease."""
        event: Dict[str, Any] = {"type": "event", "event": "operator_start", "ts": time.time(),
                                 "app": self.policy.name, "requested_mode": self.policy.mode,
                                 "model": self.runtime.info() if self.runtime else None,
                                 "model_error": self.model_error, "controller_rule": self.rule or None}
        if self.policy.live:
            if self.runtime is None and not self.rule:
                event["result"] = "refused_live_without_model"
                self.effective_mode = "observe"
            elif not self.lease.acquire():
                event["result"] = f"lease_unavailable: {self.lease.last_error}"
                self.effective_mode = "observe"
            else:
                event["result"] = "lease_acquired"
                event["lease_identity"] = self.lease.identity
                self.effective_mode = "live"
        else:
            event["result"] = "observe_only"
            self.effective_mode = "observe"
        self._log(event)
        return event

    def shutdown(self, reason: str = "operator_shutdown") -> Dict[str, Any]:
        """Return every Deployment to its HPA and release the Lease. Idempotent."""
        self._stop.set()
        restored: List[str] = []
        if self.policy.live and self.effective_mode == "live":
            for sid in list(self.lock_manager._locks):
                self.lock_manager.release_rl_lock(sid, reason=reason)
            restored = self.hpa.restore_all_frozen()
            restored += self.hpa.restore_unmanaged_replicas()
            self.lease.release()
        self.effective_mode = "observe"
        event = {"type": "event", "event": "operator_shutdown", "ts": time.time(), "reason": reason,
                 "restored_hpas": restored}
        self._log(event)
        self._write_status()
        return event

    def run(self, max_steps: Optional[int] = None) -> None:
        self.start()
        self._running = True
        try:
            while not self._stop.is_set():
                started = time.time()
                try:
                    self.step()
                except Exception as exc:  # never let one bad step leave HPAs frozen
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    logger.exception("[OPERATOR] Step failed; returning control to HPA")
                    self._fallback_all("step_exception")
                if max_steps and self.step_count >= max_steps:
                    break
                self._stop.wait(max(0.0, self.policy.poll_interval_seconds - (time.time() - started)))
        finally:
            self._running = False
            self.shutdown()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Control step
    # ------------------------------------------------------------------

    def _edges(self, names: Sequence[str]) -> List[Tuple[str, str]]:
        if self.policy.topology:
            return [(u, v) for u, v in self.policy.topology if u in names and v in names]
        try:
            from flexascale.metrics.client import MetricsClient

            flows = MetricsClient(self.policy.prometheus_url).query_inter_service_traffic(self.policy.namespace)
        except Exception:
            flows = []
        self.graph.update_from_cluster(services=list(names), traffic_flows=flows or None, telemetry_rps=None)
        return [(u, v) for u, v in self.graph.get_active_edges() if u in names and v in names]

    def _fallback_all(self, reason: str) -> None:
        if not (self.policy.live and self.effective_mode == "live"):
            return
        for sid in list(self.lock_manager._locks):
            self.lock_manager.release_rl_lock(sid, reason=reason)
        self.hpa.restore_all_frozen()

    def step(self) -> StepResult:
        self.step_count += 1
        now = time.time()
        result = StepResult(step=self.step_count, timestamp=now, mode=self.effective_mode)

        if self.policy.live and self.effective_mode == "live" and not self.lease.renew():
            self._fallback_all("lease_lost")
            self.effective_mode = "observe"
            result.events.append({"type": "event", "event": "lease_lost", "ts": now, "error": self.lease.last_error})
        result.mode = self.effective_mode
        live = self.effective_mode == "live"

        workloads = self.discovery.discover(force_refresh=True)
        if not workloads:
            result.events.append({"type": "event", "event": "no_eligible_workloads", "ts": now,
                                  "error": self.discovery.last_error})
            self._finish(result)
            return result
        by_name = {w.name: w for w in workloads}
        names = sorted(by_name)

        telemetry = self.metrics.collect(
            self.policy.namespace,
            names,
            {w.name: w.cpu_request_cores for w in workloads},
            {w.name: (w.memory_limit_bytes or w.memory_request_bytes) for w in workloads},
        )
        features = {
            n: np.asarray(WorkloadMetricsClient.observation(telemetry[n], by_name[n].desired_replicas), dtype=np.float32)
            for n in names
        }
        edges = self._edges(names)
        self._planned_total = sum(w.desired_replicas for w in workloads)
        policy_inputs = self._policy_inputs(names, telemetry, by_name, features, now)

        if self.rule:
            output = self._rule_output(names, telemetry, by_name)
        elif self.runtime is not None and getattr(self.runtime, "graph", False):
            output = self.runtime.predict_graph(policy_inputs, edges)
        elif self.runtime is not None:
            output = self.runtime.predict(policy_inputs, edges)
        else:
            output = heuristic_actions(features, self.policy.cpu_target_pct)

        for i, name in enumerate(names):
            decision = self._decide(
                name, by_name[name], telemetry[name], features[name],
                output.actions[i], output.confidences[i], output, i, live, now,
            )
            if policy_inputs is not features:
                decision["policy_input"] = [round(float(v), 4) for v in policy_inputs[name]]
            result.decisions.append(decision)

        self._finish(result)
        return result

    def _rps_trend(self, name: str, rps: Optional[float], now: float) -> float:
        """Request rate now / rate ~60 s ago (1.0 when unknown), as in the v2 simulator."""
        hist = self._rps_history.setdefault(name, deque(maxlen=64))
        if rps is not None:
            hist.append((now, float(rps)))
        while len(hist) > 1 and now - hist[1][0] >= TREND_LOOKBACK_SECONDS:
            hist.popleft()
        if rps is None or not hist or now - hist[0][0] < 0.75 * TREND_LOOKBACK_SECONDS:
            return 1.0
        prev = hist[0][1]
        if prev <= 0.0:
            return 1.0 if rps <= 0.0 else 3.0
        return float(rps) / prev

    def _rule_output(self, names: Sequence[str], telemetry: Dict[str, WorkloadMetrics],
                     by_name: Dict[str, WorkloadInfo]) -> PolicyOutput:
        """``controller_rule``: ``limit_target`` exactly as ``simulator.twin_control.limit_target_policy``.

        ``latency_target`` (docs/POLICY_V8.md §2) adds scale-ups on each service's latency inflation, its mean latency
        over its lowest latency in the last 30 min (``features_v3``), for services whose bottleneck is not CPU. It adds
        +1/+2/+3 replicas at 2/4/8x (``latency_up_log2`` = 1), and scales down only when inflation is below
        ``latency_down_log2`` and the CPU rule allows it too.
        """
        target, down = float(self.rule["target"]), float(self.rule["down"])
        latency_rule = self.rule.get("type") == "latency_target"
        up_log2 = float(self.rule.get("latency_up_log2", 1.0))
        down_log2 = float(self.rule.get("latency_down_log2", 0.3))
        min_rps = float(self.rule.get("min_rps", 0.5))
        if latency_rule and self.tracker is None:
            self.tracker = FeatureTracker(names, max_replicas=10)
        now = time.time()
        deltas: List[int] = []
        for n in names:
            m, w = telemetry[n], by_name[n]
            cores = m.cpu_cores
            lo, _ = self.policy.bounds_for(n)
            cur = max(1, int(w.desired_replicas))
            limit = w.cpu_limit_cores or 1.0  # no CPU limit: one core, what a single-threaded worker can use
            inflation = 0.0
            if latency_rule:
                x = self.tracker.update(now, n, cpu_cores=cores, ready=w.ready_replicas, desired=w.desired_replicas,
                                        cpu_limit=limit, rps=m.request_rate, latency_ms=m.latency_mean_ms)
                inflation = float(x[3]) if (m.request_rate or 0.0) >= min_rps else 0.0
            if cores is None and not latency_rule:
                deltas.append(0)
                continue
            need = math.ceil(cores / (target * limit) - 1e-9) if cores is not None else cur
            up = max(need - cur, min(3, int(inflation // up_log2)) if inflation >= up_log2 else 0)
            if up > 0:
                deltas.append(min(up, self.policy.max_step))
            elif cur > lo and (cores is None or cores / (max(cur - 1, 1) * limit) < down) and inflation < down_log2:
                deltas.append(-1)
            else:
                deltas.append(0)
        return PolicyOutput(actions=[1] * len(names), confidences=[1.0] * len(names),
                            mode="rule_latency_target" if latency_rule else "rule_limit_target",
                            windows=[[n] for n in names], deltas=deltas)

    def _policy_inputs(
        self,
        names: Sequence[str],
        telemetry: Dict[str, WorkloadMetrics],
        by_name: Dict[str, WorkloadInfo],
        features: Dict[str, np.ndarray],
        now: float,
    ) -> Dict[str, np.ndarray]:
        if self.runtime is not None and getattr(self.runtime, "graph", False):
            if self.tracker is None:
                self.tracker = FeatureTracker(names, max_replicas=int(getattr(self.runtime, "max_replicas", 10)))
            return {n: self.tracker.update(now, n, cpu_cores=telemetry[n].cpu_cores, ready=by_name[n].ready_replicas,
                                           desired=by_name[n].desired_replicas,
                                           cpu_limit=by_name[n].cpu_limit_cores or 1.0,
                                           rps=telemetry[n].request_rate, latency_ms=telemetry[n].latency_mean_ms)
                    for n in names}
        if self.runtime is None or getattr(self.runtime, "observation_version", 1) < 2:
            return features
        out: Dict[str, np.ndarray] = {}
        for n in names:
            m = telemetry[n]
            slo = self.policy.slo_for(n)
            out[n] = v2_features(
                cpu_pct=float(m.cpu_pct or 0.0),
                memory_pct=float(m.memory_pct or 0.0),
                replicas=float(max(1, by_name[n].desired_replicas)),
                max_replicas=float(getattr(self.runtime, "max_replicas", 10)),
                rps_trend=self._rps_trend(n, m.request_rate, now),
                latency_ms=float(m.latency_mean_ms or 0.0),
                slo_ms=float(slo or 0.0),
            )
        return out

    def _delta(self, action: int, output: PolicyOutput, idx: Optional[int] = None) -> int:
        """Replica change requested by an action index (the model's own deltas for PPO output, a rule's own deltas)."""
        if output.deltas is not None and idx is not None:
            return int(output.deltas[idx])
        deltas = HEURISTIC_DELTAS
        if self.runtime is not None and output.mode.startswith("ppo"):
            deltas = getattr(self.runtime, "action_deltas", HEURISTIC_DELTAS)
        return int(deltas[int(action)])

    def _auto(self, record: Dict[str, Any], name: str, *, owner_hint: bool, confidence: float, current: int,
              proposed: int, m: WorkloadMetrics, lo: int, hi: int, live: bool):
        p = self.policy
        dec = self.arbiter.decide(
            name, model_available=self.runtime is not None or bool(self.rule), telemetry_ok=owner_hint,
            lease_held=(self.effective_mode == "live") if live else True,
            confidence=confidence, activation=p.confidence_threshold, deactivation=p.deactivation_threshold,
            current=current, flexascale_proposal=int(proposed), cpu_pct=m.cpu_pct, latency_ms=m.latency_mean_ms,
            slo_ms=p.slo_for(name), lo=lo, hi=hi)
        record["auto"] = dec.to_dict()
        self.auto_state[name] = record["auto"]
        return dec

    def _decide(
        self,
        name: str,
        workload: WorkloadInfo,
        m: WorkloadMetrics,
        feat: np.ndarray,
        action: int,
        confidence: float,
        output: PolicyOutput,
        idx: int,
        live: bool,
        now: float,
    ) -> Dict[str, Any]:
        p = self.policy
        lo, hi = p.bounds_for(name)
        current = int(workload.desired_replicas)
        reasons: List[str] = []
        record: Dict[str, Any] = {
            "type": "decision",
            "ts": now,
            "step": self.step_count,
            "app": p.name,
            "mode": "live" if live else "observe",
            "service": name,
            "features": {k: round(float(v), 3) for k, v in zip(
                ["cpu_pct", "memory_pct", "replicas", "request_rate", "latency_ms"], feat)},
            "missing": list(m.missing),
            "stale": bool(m.stale),
            "policy": {
                "mode": output.mode,
                "action": int(action),
                "action_label": action_label(self._delta(action, output, idx)),
                "delta": self._delta(action, output, idx),
                "confidence": round(float(confidence), 4),
                "probabilities": output.probabilities[idx] if output.probabilities else None,
                "window": output.windows[idx] if output.windows else None,
                "clipped": output.clipped[idx] if output.clipped else [],
            },
            "current_replicas": current,
            "ready_replicas": int(workload.ready_replicas),
            "hpa": workload.hpa.name if workload.hpa else None,
        }

        # What native HPA's rule would ask for from the same telemetry (one sync, no stabilisation): an
        # estimate for the dashboard timeline, labelled as such, never used to scale.
        if m.cpu_pct is not None:
            record["hpa_recommendation"] = hpa_recommendation(current, m.cpu_pct, p.cpu_target_pct, 0.1, lo, hi)

        telemetry_ok = m.cpu_pct is not None and not m.stale
        if not telemetry_ok:
            reasons.append("telemetry_unavailable" if m.cpu_pct is None else "telemetry_stale")
            proposed = current
            owner = ControlMode.HPA
            if self.arbiter is not None:
                self._auto(record, name, owner_hint=False, confidence=confidence, current=current, proposed=current,
                           m=m, lo=lo, hi=hi, live=live)
        else:
            delta = max(-p.max_scale_down_step, min(p.max_step, self._delta(action, output, idx)))
            proposed = max(lo, min(hi, current + delta))
            record["policy_replicas"] = int(proposed)  # the policy's own proposal, before the safety guards
            if current < lo or current > hi:
                proposed = max(lo, min(hi, current))
                reasons.append("restore_replica_bounds")
            if proposed > current and p.max_total_replicas is not None and \
                    self._planned_total + (proposed - current) > p.max_total_replicas:
                room = max(0, p.max_total_replicas - self._planned_total)
                proposed = current + min(proposed - current, room)  # a multi-replica step shrinks to the budget
                reasons.append("scale_up_blocked_replica_budget" if room == 0 else "scale_up_clipped_replica_budget")
            if proposed > current and workload.ready_replicas < current:
                # Earlier replicas are still starting (or unschedulable): do not pile more on.
                proposed = current
                reasons.append("scale_up_waiting_for_readiness")
            if proposed > current and now - self._last_scale_up.get(name, float("-inf")) < p.scale_up_cooldown_seconds:
                # Telemetry is averaged over a window: let it reflect the last scale-up first.
                proposed = current
                reasons.append("scale_up_cooldown")
            if proposed < current:
                cpu = m.cpu_pct or 0.0
                if cpu >= p.scale_down_block_cpu_pct:
                    proposed, _ = current, reasons.append("scale_down_blocked_cpu")
                elif (m.memory_pct or 0.0) >= p.scale_down_block_memory_pct:
                    proposed, _ = current, reasons.append("scale_down_blocked_memory")
                elif p.slo_for(name) and (m.latency_mean_ms or 0.0) > p.slo_for(name):
                    proposed, _ = current, reasons.append("scale_down_blocked_slo")
                elif now - self._last_scale_down.get(name, 0.0) < p.scale_down_cooldown_seconds:
                    proposed, _ = current, reasons.append("scale_down_cooldown")
                elif workload.ready_replicas < current:
                    proposed, _ = current, reasons.append("scale_down_waiting_for_readiness")
            # Auto mode: ordered, explainable rules choose the owner (operator/auto_mode.py).
            if self.arbiter is not None:
                dec = self._auto(record, name, owner_hint=True, confidence=confidence, current=current, proposed=proposed,
                                 m=m, lo=lo, hi=hi, live=live)
                owner = ControlMode.RL if dec.owner == "flexascale" else ControlMode.HPA
                if owner == ControlMode.HPA:
                    reasons.append(f"auto_{dec.rule}")
            # Confidence gate with hysteresis.
            elif (owner_now := self.lock_manager.get_control_mode(name)) == ControlMode.RL:
                owner = ControlMode.RL if confidence >= p.deactivation_threshold else ControlMode.HPA
                if owner == ControlMode.HPA:
                    reasons.append("confidence_below_deactivation")
            elif confidence >= p.confidence_threshold:
                if now - self._last_fallback.get(name, 0.0) < p.cooldown_seconds:
                    owner = ControlMode.HPA
                    reasons.append("ownership_cooldown")
                else:
                    owner = ControlMode.RL
            else:
                owner = ControlMode.HPA
                reasons.append("confidence_below_activation")

        if owner == ControlMode.RL and telemetry_ok:
            self._planned_total += proposed - current
        if owner == ControlMode.HPA and not p.hpa_fallback and telemetry_ok:
            # Policy forbids handing back to HPA: hold replicas under FlexaScale instead.
            owner = ControlMode.RL
            proposed = current
            reasons.append("hold_no_hpa_fallback")

        record["controller"] = "flexascale" if owner == ControlMode.RL else ("hpa" if workload.hpa else "none")
        record["proposed_replicas"] = int(proposed if owner == ControlMode.RL else current)
        record["safety_reasons"] = reasons or ["accepted"]
        record["applied"] = False
        record["apply_error"] = None

        if not live:
            record["note"] = "observation only: no cluster change"
            return record

        if owner == ControlMode.RL:
            ok = self.lock_manager.acquire_rl_lock(name, confidence, timeout_seconds=p.lease_seconds)
            if not ok:
                record["apply_error"] = "ownership_lock_unavailable"
                return record
            if not self.hpa.freeze_hpa(name, proposed):
                record["apply_error"] = f"hpa_freeze_failed: {self.hpa.last_note}"
                self.lock_manager.release_rl_lock(name, reason="hpa_freeze_failed")
                return record
            record["hpa_note"] = self.hpa.last_note
            if proposed != current:
                if self.hpa.scale_deployment(name, proposed):
                    record["applied"] = True
                    if proposed < current:
                        self._last_scale_down[name] = now
                    else:
                        self._last_scale_up[name] = now
                    if self.tracker is not None:
                        self.tracker.note_scale(name, 1 if proposed > current else -1, now)
                else:
                    record["apply_error"] = "scale_request_failed"
        else:
            was_rl = self.lock_manager.get_control_mode(name) == ControlMode.RL
            self.lock_manager.release_rl_lock(name, reason=",".join(reasons))
            if was_rl or (workload.hpa and workload.hpa.frozen):
                self.hpa.ensure_hpa_active(name)
                record["hpa_note"] = self.hpa.last_note
                self._last_fallback[name] = now
        return record

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _log(self, record: Dict[str, Any]) -> None:
        if self.decision_log is None:
            return
        self.decision_log.parent.mkdir(parents=True, exist_ok=True)
        with self.decision_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def _finish(self, result: StepResult) -> None:
        for ev in result.events:
            self._log(ev)
        for d in result.decisions:
            self._log(d)
        self.last_result = result
        self._write_status()

    def status(self) -> Dict[str, Any]:
        lease = None
        if self.policy.live:
            try:
                lease = self.lease.status().to_dict()
            except Exception:
                lease = None
        return {
            "app": self.policy.name,
            "namespace": self.policy.namespace,
            "requested_mode": self.policy.mode,
            "effective_mode": self.effective_mode,
            "pid": os.getpid(),
            "step": self.step_count,
            "updated_at": time.time(),
            "poll_interval_seconds": self.policy.poll_interval_seconds,
            "model": self.runtime.info() if self.runtime else None,
            "model_error": self.model_error,
            "lease": lease,
            "lease_identity": self.lease.identity,
            "last_error": self.last_error,
            "services": [d["service"] for d in (self.last_result.decisions if self.last_result else [])],
            "auto": self.arbiter is not None,
            "auto_state": self.auto_state if self.arbiter is not None else None,
        }

    def _write_status(self) -> None:
        if self.status_file is None:
            return
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.status_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.status(), default=str, indent=2), encoding="utf-8")
        tmp.replace(self.status_file)
