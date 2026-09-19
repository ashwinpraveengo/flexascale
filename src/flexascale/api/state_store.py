"""
Shared State Store for FlexaScale REST API.

Provides unified thread-safe access to operator decisions, live telemetry,
historical time-series metrics for charts, dynamic configuration, and emergency actions.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Dict, List, Optional

from flexascale.config.safety_config import SafetyConfig
from flexascale.operator.operator import FlexaScaleOperator
from flexascale.rl.gnn_encoder import DEFAULT_SERVICES
from flexascale.safety.coordinator import SafetyCoordinator
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ControlMode, ScalingLockManager
from flexascale.state.graph_inference import LiveGraphInference
from flexascale.state.live_builder import LiveClusterState, LiveStateBuilder

logger = logging.getLogger(__name__)


class APIStateStore:
    """
    Central state store for the REST API and Dashboard.
    """

    def __init__(
        self,
        operator: Optional[FlexaScaleOperator] = None,
        config: Optional[SafetyConfig] = None,
        mock: bool = True,
    ) -> None:
        self.mock = mock
        self.config = config or SafetyConfig(dry_run=mock)
        self.slo_latency_target_ms = 100.0

        if operator is not None:
            self.operator = operator
            self.coordinator = operator.coordinator
            self.state_builder = operator.state_builder
            self.graph_inference = operator.graph_inference
        else:
            self.coordinator = SafetyCoordinator(
                config=self.config,
                lock_manager=ScalingLockManager(config=self.config, sync_k8s=not mock),
                hpa_manager=HPAManager(config=self.config, mock=mock),
            )
            from flexascale.discovery.service_discovery import ServiceDiscovery
            discovery = ServiceDiscovery(
                namespace=self.config.namespace,
                mock=mock,
                mock_services=self.config.service_names if self.config.service_names else None,
            )
            discovered = discovery.discover()
            services = list(discovered) if discovered else list(DEFAULT_SERVICES)
            self.state_builder = LiveStateBuilder(
                services=services,
                discovery=discovery,
                namespace=self.config.namespace,
                mock=mock,
            )
            self.graph_inference = LiveGraphInference(
                services=services,
            )
            self.operator = FlexaScaleOperator(
                services=services,
                discovery=discovery,
                safety_config=self.config,
                coordinator=self.coordinator,
                state_builder=self.state_builder,
                graph_inference=self.graph_inference,
                mock=mock,
            )

        # Ring buffer for live charts telemetry history (last 50 points)
        self.history: deque[Dict[str, Any]] = deque(maxlen=60)
        self._seed_initial_history()

    def _seed_initial_history(self) -> None:
        """Seed a few realistic historical points so charts have data immediately."""
        now = time.time()
        for i in range(15, 0, -1):
            t = now - (i * 3)
            self.history.append({
                "timestamp": t,
                "cpu_utilization": 22.0 + (i % 5) * 1.5,
                "latency_ms": 18.0 + (i % 4) * 2.0,
                "request_rate": 12.0 + (i % 6) * 3.0,
                "total_replicas": 4,
                "slo_latency_target_ms": self.slo_latency_target_ms,
            })

    def record_metrics_point(self, cluster_state: LiveClusterState) -> None:
        """Appends latest cluster-level telemetry to the history buffer."""
        now = time.time()
        states = cluster_state.service_states.values()
        if not states:
            return

        avg_cpu = sum(s.cpu_utilization for s in states) / len(states)
        max_lat = max(s.latency_ms for s in states)
        tot_rps = sum(s.request_rate for s in states)
        tot_reps = sum(s.replica_count for s in states)

        self.history.append({
            "timestamp": now,
            "cpu_utilization": round(avg_cpu, 2),
            "latency_ms": round(max_lat, 2),
            "request_rate": round(tot_rps, 2),
            "total_replicas": tot_reps,
            "slo_latency_target_ms": self.slo_latency_target_ms,
        })

    def get_system_status(self) -> Dict[str, Any]:
        """Returns overall system health, modes, and active replicas."""
        cluster_state = self.state_builder.build()
        self.record_metrics_point(cluster_state)

        modes = {
            sid: self.coordinator.lock_manager.get_control_mode(sid).value
            for sid in self.operator.services
        }
        replicas = {
            sid: cluster_state.service_states[sid].replica_count
            for sid in self.operator.services
            if sid in cluster_state.service_states
        }
        return {
            "status": "healthy",
            "operator_running": self.operator._running,
            "is_live_cluster": not self.mock,
            "modes": modes,
            "replicas": replicas,
            "timestamp": time.time(),
        }

    def get_service_metrics(self) -> List[Dict[str, Any]]:
        """Returns validated telemetry per microservice."""
        cluster_state = self.state_builder.build()
        self.record_metrics_point(cluster_state)

        result = []
        for sid in self.operator.services:
            state = cluster_state.service_states.get(sid)
            if state:
                slo_ok = state.latency_ms <= self.slo_latency_target_ms
                result.append({
                    "service_id": sid,
                    "cpu_utilization": round(state.cpu_utilization, 2),
                    "memory_utilization": round(state.memory_utilization, 2),
                    "replica_count": state.replica_count,
                    "request_rate": round(state.request_rate, 2),
                    "latency_ms": round(state.latency_ms, 2),
                    "error_rate": round(state.error_rate, 2),
                    "slo_satisfied": slo_ok,
                })
        return result

    def get_decisions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns recent safety scaling decisions."""
        return self.operator.get_recent_decisions(limit=limit)

    def get_graph(self) -> Dict[str, Any]:
        """Returns inferred dependency graph with EMA weights."""
        return self.graph_inference.to_dict()

    def get_config(self) -> Dict[str, Any]:
        """Returns current dynamic configuration."""
        return {
            "target_cpu_utilization": self.config.target_cpu_utilization,
            "slo_latency_target_ms": self.slo_latency_target_ms,
            "confidence_threshold": self.config.confidence_threshold,
            "deactivation_threshold": self.config.deactivation_threshold,
            "cooldown_seconds": self.config.cooldown_seconds,
            "hpa_min_replicas": self.config.hpa_min_replicas,
            "hpa_max_replicas": self.config.hpa_max_replicas,
        }

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Updates configuration parameters dynamically."""
        from dataclasses import replace

        config_updates = {}
        if "target_cpu_utilization" in updates and updates["target_cpu_utilization"] is not None:
            config_updates["target_cpu_utilization"] = int(updates["target_cpu_utilization"])
        if "confidence_threshold" in updates and updates["confidence_threshold"] is not None:
            config_updates["confidence_threshold"] = float(updates["confidence_threshold"])
        if "deactivation_threshold" in updates and updates["deactivation_threshold"] is not None:
            config_updates["deactivation_threshold"] = float(updates["deactivation_threshold"])
        if "cooldown_seconds" in updates and updates["cooldown_seconds"] is not None:
            config_updates["cooldown_seconds"] = float(updates["cooldown_seconds"])

        if config_updates:
            self.config = replace(self.config, **config_updates)
            self.coordinator.config = self.config
            self.coordinator.lock_manager.config = self.config
            self.coordinator.hpa_manager.config = self.config
            self.operator.config = self.config

        if "slo_latency_target_ms" in updates and updates["slo_latency_target_ms"] is not None:
            self.slo_latency_target_ms = float(updates["slo_latency_target_ms"])

        return self.get_config()

    def emergency_fallback(self) -> Dict[str, Any]:
        """Releases all scaling locks and falls back to dynamic HPA immediately."""
        self.coordinator.fallback_all_to_hpa(reason="emergency_api_trigger")
        return {
            "status": "fallback_executed",
            "reason": "emergency_api_trigger",
            "modes": {
                sid: self.coordinator.lock_manager.get_control_mode(sid).value
                for sid in self.operator.services
            },
            "timestamp": time.time(),
        }

    def step(self) -> List[Dict[str, Any]]:
        """Executes a single step through the operator."""
        decisions = self.operator.step()
        cluster_state = self.state_builder.build()
        self.record_metrics_point(cluster_state)
        return [
            {
                "service_id": d.service_id,
                "chosen_mode": d.chosen_mode.value,
                "confidence": round(d.confidence, 4) if d.confidence is not None else None,
                "target_replicas": d.target_replicas,
                "action_applied": d.action_applied,
                "lock_acquired": d.lock_acquired,
                "hpa_frozen": d.hpa_frozen,
                "hpa_active": d.hpa_active,
                "reason": d.reason,
            }
            for d in decisions
        ]


# Global state store instance
_state_store: Optional[APIStateStore] = None


def get_state_store(mock: bool = True) -> APIStateStore:
    global _state_store
    if _state_store is None:
        _state_store = APIStateStore(mock=mock)
    return _state_store


def set_state_store(store: APIStateStore) -> None:
    global _state_store
    _state_store = store
