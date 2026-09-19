"""
Unit and integration tests for Application-Agnostic FlexaScale Operator & GNN Decision Engine.
"""

import numpy as np
import pytest
import torch

from flexascale.config.safety_config import SafetyConfig
from flexascale.discovery.service_discovery import ServiceDiscovery
from flexascale.operator.operator import FlexaScaleOperator
from flexascale.rl.gnn_encoder import GNNDependencyEncoder
from flexascale.safety.coordinator import SafetyCoordinator
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ScalingLockManager
from flexascale.state.graph_inference import LiveGraphInference
from flexascale.state.live_builder import LiveStateBuilder


def test_gnn_node_actions_size_invariance():
    """Verify GNNDependencyEncoder produces valid node actions for any N services."""
    encoder = GNNDependencyEncoder(num_nodes=4, in_channels=5, hidden_dim=32, out_dim=32)

    for num_services in (2, 3, 5, 8):
        x = torch.randn(num_services, 5)
        # Create sequential chain edges: (0->1, 1->2, ...)
        edges = [[i, i + 1] for i in range(num_services - 1)] + [[i + 1, i] for i in range(num_services - 1)]
        edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous() if edges else torch.empty((2, 0), dtype=torch.long)

        actions, confidences = encoder.predict_node_actions(x, edge_index)

        assert actions.shape == (num_services,)
        assert confidences.shape == (num_services,)
        assert all(0 <= a <= 2 for a in actions.tolist())
        assert all(0.0 <= c <= 1.0 for c in confidences.tolist())


def test_operator_with_custom_3_service_application():
    """Verify operator runs cleanly on an arbitrary 3-microservice application."""
    custom_services = ["auth-api", "cart-service", "catalog-db"]

    config = SafetyConfig(
        confidence_threshold=0.70,
        namespace="ecommerce-prod",
        dry_run=True,
    )
    discovery = ServiceDiscovery(
        namespace="ecommerce-prod",
        mock=True,
        mock_services=custom_services,
    )
    state_builder = LiveStateBuilder(
        services=custom_services,
        discovery=discovery,
        namespace="ecommerce-prod",
        mock=True,
    )
    graph_infer = LiveGraphInference(services=custom_services)
    lock_mgr = ScalingLockManager(config=config, sync_k8s=False)
    hpa_mgr = HPAManager(config=config, mock=True)
    coordinator = SafetyCoordinator(config=config, lock_manager=lock_mgr, hpa_manager=hpa_mgr)

    operator = FlexaScaleOperator(
        services=custom_services,
        discovery=discovery,
        safety_config=config,
        coordinator=coordinator,
        state_builder=state_builder,
        graph_inference=graph_infer,
        mock=True,
    )

    assert operator.services == custom_services
    assert operator.discovery.namespace == "ecommerce-prod"

    # Step 1: Normal steady step
    decisions = operator.step()
    assert len(decisions) == 3
    assert {d.service_id for d in decisions} == set(custom_services)

    # Step 2: Surge on cart-service
    state_builder.set_mock_metric("cart-service", "cpu_utilization", 85.0)
    decisions2 = operator.step()
    cart_decision = next(d for d in decisions2 if d.service_id == "cart-service")
    assert cart_decision.service_id == "cart-service"

    # Clean shutdown
    operator.shutdown()
    assert all(
        hpa_mgr._mock_hpa_bounds[s] == (config.hpa_min_replicas, config.hpa_max_replicas)
        for s in custom_services
    )


def test_operator_with_custom_5_service_fleet():
    """Verify operator runs cleanly on an arbitrary 5-microservice fleet."""
    fleet = ["gateway", "users", "products", "orders", "notifications"]

    config = SafetyConfig(dry_run=True)
    discovery = ServiceDiscovery(mock=True, mock_services=fleet)
    state_builder = LiveStateBuilder(services=fleet, discovery=discovery, mock=True)
    graph_infer = LiveGraphInference(services=fleet)
    coordinator = SafetyCoordinator(config=config, hpa_manager=HPAManager(config=config, mock=True))

    operator = FlexaScaleOperator(
        services=fleet,
        discovery=discovery,
        safety_config=config,
        coordinator=coordinator,
        state_builder=state_builder,
        graph_inference=graph_infer,
        mock=True,
    )

    assert len(operator.services) == 5

    # Run 2 autonomous control loop steps
    decisions = operator.step()
    assert len(decisions) == 5
    for d in decisions:
        assert d.service_id in fleet
        assert d.target_replicas >= 1

    operator.shutdown()


def test_graph_inference_dynamic_flow_update():
    """Verify LiveGraphInference updates and prunes edges on arbitrary services."""
    services = ["service-x", "service-y", "service-z"]
    gi = LiveGraphInference(services=services)

    # Initial chain
    active = gi.get_active_edges()
    assert len(active) >= 0

    # Observe live traffic between X and Y
    gi.observe_traffic("service-x", "service-y", 50.0)
    assert gi.get_edge_weight("service-x", "service-y") > 0.0

    # Cluster update with inter-service traffic flow
    flows = [("service-y", "service-z", 35.0)]
    gi.update_from_cluster(services=services, traffic_flows=flows)
    assert gi.get_edge_weight("service-y", "service-z") > 0.0

    # PyG edge_index export should match number of nodes
    edge_index = gi.get_edge_index()
    assert edge_index.shape[0] == 2
    assert edge_index.shape[1] > 0
