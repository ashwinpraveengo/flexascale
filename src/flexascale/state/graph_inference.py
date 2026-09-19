"""
Live Dependency Graph Inference for FlexaScale.

Infers and dynamically maintains the microservice call-graph topology
from live traffic observations using Exponential Moving Average (EMA) decay:

    W_{u,v}^{(t)} = alpha * traffic_{u,v}^{(t)} + (1 - alpha) * W_{u,v}^{(t-1)}

Supports edge decay over time, edge pruning, conversion to PyTorch Geometric
edge indices, and export to ServiceDependencyGraph for GNN convolutions.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Sequence, Tuple

import torch

from flexascale.rl.gnn_encoder import (
    DEFAULT_EDGES,
    DEFAULT_SERVICES,
    ServiceDependencyGraph,
)

logger = logging.getLogger(__name__)


class LiveGraphInference:
    """
    Online dependency graph estimator using traffic observations with EMA decay.
    Supports dynamic microservice discovery and application-agnostic graph inference.
    """

    def __init__(
        self,
        services: Optional[Sequence[str]] = None,
        initial_edges: Optional[Sequence[Tuple[str, str]]] = None,
        alpha: float = 0.3,
        decay_rate: float = 0.05,
        prune_threshold: float = 0.01,
        initial_weight: float = 1.0,
    ) -> None:
        """
        Args:
            services: Ordered collection of microservice identifiers. If None,
                      can be populated dynamically via discovery.
            initial_edges: Prior or default caller-callee directed edges.
            alpha: EMA smoothing factor in (0, 1]. Higher alpha places more
                   weight on the most recent traffic measurement.
            decay_rate: Fractional decay applied to edge weights per time step
                        when no new traffic is observed.
            prune_threshold: Minimum edge weight to be considered an active edge.
            initial_weight: Default prior weight assigned to initial edges.
        """
        if services is None:
            self.services = list(DEFAULT_SERVICES)
        else:
            self.services = list(services)

        if initial_edges is None:
            if set(self.services) == set(DEFAULT_SERVICES):
                edges_to_use = list(DEFAULT_EDGES)
            elif len(self.services) > 1:
                edges_to_use = [
                    (self.services[i], self.services[i + 1])
                    for i in range(len(self.services) - 1)
                ]
            else:
                edges_to_use = []
        else:
            edges_to_use = list(initial_edges)

        self.service_to_idx = {name: i for i, name in enumerate(self.services)}
        self.alpha = float(alpha)
        self.decay_rate = float(decay_rate)
        self.prune_threshold = float(prune_threshold)
        self.last_updated = time.time()

        # Edge weights dictionary: (caller, callee) -> float weight
        self._weights: Dict[Tuple[str, str], float] = {}
        for u, v in edges_to_use:
            if u in self.service_to_idx and v in self.service_to_idx:
                self._weights[(u, v)] = float(initial_weight)

    @property
    def num_nodes(self) -> int:
        return len(self.services)

    def add_service(self, service_id: str) -> None:
        """Dynamically registers a newly discovered microservice."""
        if service_id not in self.service_to_idx:
            self.services.append(service_id)
            self.service_to_idx[service_id] = len(self.services) - 1

    def observe_traffic(
        self,
        caller: str,
        callee: str,
        traffic_rate: float,
    ) -> float:
        """
        Record observed traffic flow from caller to callee and update edge weight via EMA.

        Args:
            caller: Calling service identifier.
            callee: Downstream callee service identifier.
            traffic_rate: Raw traffic measurement (e.g. requests per second).

        Returns:
            Updated float weight of the edge.
        """
        self.add_service(caller)
        self.add_service(callee)
        edge = (caller, callee)

        prev_weight = self._weights.get(edge, 0.0)
        # EMA update
        new_weight = self.alpha * float(traffic_rate) + (1.0 - self.alpha) * prev_weight
        self._weights[edge] = max(0.0, new_weight)
        self.last_updated = time.time()
        return self._weights[edge]

    def decay_step(self) -> None:
        """
        Applies decay to all known edges for a time-step where no traffic arrived.
        Edges with weights falling below prune_threshold are pruned.
        """
        to_prune: List[Tuple[str, str]] = []
        for edge, weight in self._weights.items():
            decayed = weight * (1.0 - self.decay_rate)
            if decayed < self.prune_threshold:
                to_prune.append(edge)
            else:
                self._weights[edge] = decayed

        for edge in to_prune:
            del self._weights[edge]

        self.last_updated = time.time()

    def get_edge_weight(self, caller: str, callee: str) -> float:
        """Return the current estimated weight for a directed edge."""
        return self._weights.get((caller, callee), 0.0)

    def get_active_edges(self, threshold: float | None = None) -> List[Tuple[str, str]]:
        """
        Returns all edges whose current EMA weight exceeds the active threshold.
        """
        thresh = self.prune_threshold if threshold is None else threshold
        return [
            edge
            for edge, weight in sorted(self._weights.items(), key=lambda x: -x[1])
            if weight >= thresh
        ]

    def update_from_cluster(
        self,
        services: Sequence[str],
        traffic_flows: Optional[Sequence[Tuple[str, str, float]]] = None,
        telemetry_rps: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Dynamically updates the graph topology for a set of discovered microservices.
        """
        for sid in services:
            self.add_service(sid)

        observed_any = False
        if traffic_flows:
            for caller, callee, rps in traffic_flows:
                if rps > 0:
                    self.observe_traffic(caller, callee, rps)
                    observed_any = True

        # If no mesh traffic flows were explicitly provided, infer correlation
        if not observed_any and telemetry_rps and len(services) > 1:
            for i in range(len(services) - 1):
                u = services[i]
                v = services[i + 1]
                rps_u = telemetry_rps.get(u, 0.0)
                rps_v = telemetry_rps.get(v, 0.0)
                if rps_u > 0 or rps_v > 0:
                    traffic = min(rps_u, rps_v) if (rps_u > 0 and rps_v > 0) else max(rps_u, rps_v) * 0.5
                    self.observe_traffic(u, v, traffic)
                    observed_any = True

        if not observed_any:
            self.decay_step()

    def to_service_dependency_graph(
        self,
        bidirectional: bool = True,
        self_loops: bool = True,
        threshold: float | None = None,
    ) -> ServiceDependencyGraph:
        """
        Converts the inferred graph into a ServiceDependencyGraph instance
        compatible with the PyG GNN feature extractor.
        """
        active_edges = self.get_active_edges(threshold=threshold)
        if not active_edges:
            if len(self.services) > 1:
                # Dynamically construct sequential chain for discovered services
                active_edges = [
                    (self.services[i], self.services[i + 1])
                    for i in range(len(self.services) - 1)
                ]
            else:
                active_edges = []

        return ServiceDependencyGraph(
            services=self.services,
            edges=active_edges,
            bidirectional=bidirectional,
            self_loops=self_loops,
        )

    def get_edge_index(
        self,
        bidirectional: bool = True,
        self_loops: bool = True,
    ) -> torch.Tensor:
        """
        Generates a PyG-compatible edge_index tensor of shape (2, num_edges).
        """
        graph = self.to_service_dependency_graph(
            bidirectional=bidirectional,
            self_loops=self_loops,
        )
        return graph.get_edge_index()

    def get_edge_weights_tensor(self) -> torch.Tensor:
        """
        Returns a 1D tensor of edge weights corresponding to get_active_edges().
        """
        active_edges = self.get_active_edges()
        weights = [self._weights[edge] for edge in active_edges]
        return torch.tensor(weights, dtype=torch.float32)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes current graph state to JSON-compatible dictionary."""
        active_edges = self.get_active_edges()
        nodes = [
            {
                "id": name,
                "index": i,
                "label": name.capitalize(),
            }
            for i, name in enumerate(self.services)
        ]
        edges = [
            {
                "source": u,
                "target": v,
                "weight": round(self._weights[(u, v)], 4),
                "active": True,
            }
            for u, v in active_edges
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "num_nodes": len(nodes),
            "num_edges": len(edges),
            "alpha": self.alpha,
            "decay_rate": self.decay_rate,
            "last_updated": self.last_updated,
        }
