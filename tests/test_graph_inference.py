"""
Unit and integration tests for LiveGraphInference (Phase 3).
"""

import pytest
import torch

from flexascale.rl.gnn_encoder import DEFAULT_EDGES, DEFAULT_SERVICES, ServiceDependencyGraph
from flexascale.state.graph_inference import LiveGraphInference


def test_graph_inference_initialization():
    infer = LiveGraphInference(
        services=DEFAULT_SERVICES,
        initial_edges=DEFAULT_EDGES,
        alpha=0.3,
        decay_rate=0.1,
        prune_threshold=0.05,
    )
    assert infer.num_nodes == 4
    assert len(infer.get_active_edges()) == len(DEFAULT_EDGES)
    assert infer.get_edge_weight("frontend", "orders") == 1.0


def test_graph_inference_ema_update():
    infer = LiveGraphInference(
        services=["frontend", "orders"],
        initial_edges=[("frontend", "orders")],
        alpha=0.5,
        initial_weight=1.0,
    )
    # Observed traffic 10.0 -> EMA: 0.5 * 10 + 0.5 * 1.0 = 5.5
    w1 = infer.observe_traffic("frontend", "orders", 10.0)
    assert pytest.approx(w1, rel=1e-3) == 5.5
    assert pytest.approx(infer.get_edge_weight("frontend", "orders"), rel=1e-3) == 5.5

    # Observed traffic 20.0 -> EMA: 0.5 * 20 + 0.5 * 5.5 = 12.75
    w2 = infer.observe_traffic("frontend", "orders", 20.0)
    assert pytest.approx(w2, rel=1e-3) == 12.75


def test_graph_inference_decay_and_pruning():
    infer = LiveGraphInference(
        services=["frontend", "orders"],
        initial_edges=[("frontend", "orders")],
        decay_rate=0.5,
        prune_threshold=0.3,
        initial_weight=1.0,
    )
    # 1 decay step: 1.0 * (1 - 0.5) = 0.5
    infer.decay_step()
    assert pytest.approx(infer.get_edge_weight("frontend", "orders"), rel=1e-3) == 0.5
    assert ("frontend", "orders") in infer.get_active_edges()

    # 2nd decay step: 0.5 * 0.5 = 0.25 < 0.3 (pruned!)
    infer.decay_step()
    assert infer.get_edge_weight("frontend", "orders") == 0.0
    assert ("frontend", "orders") not in infer.get_active_edges()


def test_graph_inference_pyg_export():
    infer = LiveGraphInference(
        services=DEFAULT_SERVICES,
        initial_edges=DEFAULT_EDGES,
    )
    edge_index = infer.get_edge_index(bidirectional=True, self_loops=True)
    assert isinstance(edge_index, torch.Tensor)
    assert edge_index.shape[0] == 2
    assert edge_index.dtype == torch.long

    # Export to ServiceDependencyGraph
    dep_graph = infer.to_service_dependency_graph(bidirectional=True, self_loops=True)
    assert isinstance(dep_graph, ServiceDependencyGraph)
    assert dep_graph.num_nodes == 4


def test_graph_inference_to_dict():
    infer = LiveGraphInference(
        services=DEFAULT_SERVICES,
        initial_edges=DEFAULT_EDGES,
    )
    payload = infer.to_dict()
    assert payload["num_nodes"] == 4
    assert len(payload["nodes"]) == 4
    assert len(payload["edges"]) == 3
    assert payload["edges"][0]["source"] == "frontend"
    assert payload["edges"][0]["target"] == "orders"
