"""
Live State Builder for FlexaScale.

Constructs schema-validated ServiceState instances from Prometheus telemetry
and projects them into the exact multi-service concatenated observation vector
expected by the trained PPO + GNN reinforcement learning policy.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from flexascale.data.schema import (
    VECTOR_DIM,
    VECTOR_FIELDS,
    ServiceState,
    StateSource,
)
from flexascale.discovery.service_discovery import ServiceDiscovery
from flexascale.metrics.client import MetricsClient
from flexascale.rl.gnn_encoder import DEFAULT_SERVICES

logger = logging.getLogger(__name__)


@dataclass
class LiveClusterState:
    """Aggregated live cluster state across all monitored microservices."""

    timestamp: float
    service_states: Dict[str, ServiceState]
    observation_vector: np.ndarray
    is_live: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "is_live": self.is_live,
            "services": {
                sid: state.to_dict() for sid, state in self.service_states.items()
            },
            "observation_vector": self.observation_vector.tolist(),
            "metadata": self.metadata,
        }


class LiveStateBuilder:
    """
    Builds the observation vector and structured telemetry states for all
    target microservices matching the training policy's schema contract.
    Supports dynamic workload auto-discovery.
    """

    def __init__(
        self,
        services: Optional[Sequence[str]] = None,
        discovery: Optional[ServiceDiscovery] = None,
        metrics_client: Optional[MetricsClient] = None,
        namespace: str = "flexascale-apps",
        mock: bool = False,
    ) -> None:
        self.namespace = namespace
        self.mock = mock
        self.metrics_client = metrics_client or MetricsClient()
        self.discovery = discovery or ServiceDiscovery(
            namespace=namespace,
            mock=mock,
            mock_services=services,
        )

        if services is not None:
            self.services = list(services)
        else:
            discovered = self.discovery.discover()
            self.services = list(discovered) if discovered else list(DEFAULT_SERVICES)

        # In-memory mock storage for local testing & demos
        self._mock_states: Dict[str, Dict[str, Any]] = {}
        for sid in self.services:
            self._init_mock_state(sid)

    def _init_mock_state(self, service_id: str) -> None:
        """Initialize mock telemetry values for a service."""
        if service_id not in self._mock_states:
            self._mock_states[service_id] = {
                "cpu_utilization": 25.0,
                "memory_utilization": 30.0,
                "replica_count": 2,
                "request_rate": 15.0,
                "latency_ms": 20.0,
            }

    def update_services(self, services: Sequence[str]) -> None:
        """Dynamically updates the active monitored service list."""
        self.services = list(services)
        for sid in self.services:
            self._init_mock_state(sid)

    def set_mock_metric(self, service_id: str, metric: str, value: float) -> None:
        """Sets a mock telemetry value for testing without Prometheus."""
        if service_id not in self._mock_states:
            self._mock_states[service_id] = {
                "cpu_utilization": 10.0,
                "memory_utilization": 20.0,
                "replica_count": 1,
                "request_rate": 5.0,
                "latency_ms": 15.0,
            }
        self._mock_states[service_id][metric] = value

    def _build_fallback_state(self, service_id: str) -> ServiceState:
        """Constructs a safe zero/default fallback state if metric scraping fails."""
        current_ts = int(time.time())
        data: Dict[str, Any] = {
            "timestamp": current_ts,
            "service_id": service_id,
            "cpu_utilization": 0.0,
            "memory_utilization": 0.0,
            "replica_count": 1,
            "request_rate": 0.0,
            "latency_ms": 0.0,
            "source": StateSource.LIVE,
        }
        return ServiceState.from_dict(data, source=StateSource.LIVE)

    def _build_mock_state(self, service_id: str) -> ServiceState:
        """Constructs a mock ServiceState using the in-memory telemetry table."""
        current_ts = int(time.time())
        params = self._mock_states.get(
            service_id,
            {
                "cpu_utilization": 20.0,
                "memory_utilization": 25.0,
                "replica_count": 1,
                "request_rate": 10.0,
                "latency_ms": 15.0,
            },
        )
        data: Dict[str, Any] = {
            "timestamp": current_ts,
            "service_id": service_id,
            "cpu_utilization": float(params.get("cpu_utilization", 20.0)),
            "memory_utilization": float(params.get("memory_utilization", 25.0)),
            "replica_count": int(params.get("replica_count", 1)),
            "request_rate": float(params.get("request_rate", 10.0)),
            "latency_ms": float(params.get("latency_ms", 15.0)),
            "successful_requests": float(params.get("request_rate", 10.0)),
            "failed_requests": 0.0,
            "source": StateSource.LIVE,
        }
        return ServiceState.from_dict(data, source=StateSource.LIVE)

    def get_service_state(self, service_id: str) -> ServiceState:
        """Retrieves and validates a single service state."""
        if self.mock:
            return self._build_mock_state(service_id)

        try:
            return self.metrics_client.get_service_state(
                service_id=service_id,
                namespace=self.namespace,
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch live telemetry for '%s' from Prometheus: %s. Using fallback state.",
                service_id,
                exc,
            )
            return self._build_fallback_state(service_id)

    def build(self) -> LiveClusterState:
        """
        Gathers live states for all configured services and builds the
        concatenated float32 observation vector.

        Returns:
            LiveClusterState with observation_vector of shape (num_services * 5,).
        """
        now = time.time()
        service_states: Dict[str, ServiceState] = {}
        vector_parts: List[np.ndarray] = []

        for sid in self.services:
            state = self.get_service_state(sid)
            service_states[sid] = state
            vec = state.to_vector()
            vector_parts.append(vec)

        if vector_parts:
            obs_vector = np.concatenate(vector_parts).astype(np.float32)
        else:
            obs_vector = np.empty((0,), dtype=np.float32)

        expected_dim = len(self.services) * VECTOR_DIM
        if obs_vector.shape != (expected_dim,):
            raise ValueError(
                f"Observation vector shape mismatch! Expected ({expected_dim},), got {obs_vector.shape}"
            )

        return LiveClusterState(
            timestamp=now,
            service_states=service_states,
            observation_vector=obs_vector,
            is_live=not self.mock,
            metadata={
                "num_services": len(self.services),
                "services": self.services,
                "vector_dim": expected_dim,
                "fields": list(VECTOR_FIELDS),
            },
        )
