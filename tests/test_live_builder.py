"""
Unit and integration tests for LiveStateBuilder (Phase 3).
"""

import numpy as np
import pytest

from flexascale.data.schema import VECTOR_DIM, ServiceState
from flexascale.rl.gnn_encoder import DEFAULT_SERVICES
from flexascale.state.live_builder import LiveClusterState, LiveStateBuilder


def test_live_builder_mock_vector_shape():
    builder = LiveStateBuilder(services=DEFAULT_SERVICES, mock=True)
    cluster_state = builder.build()

    assert isinstance(cluster_state, LiveClusterState)
    assert len(cluster_state.service_states) == 4

    # 4 services * 5 dimensions = 20
    assert cluster_state.observation_vector.shape == (20,)
    assert cluster_state.observation_vector.dtype == np.float32

    for sid in DEFAULT_SERVICES:
        assert sid in cluster_state.service_states
        state = cluster_state.service_states[sid]
        assert isinstance(state, ServiceState)
        vec = state.to_vector()
        assert vec.shape == (VECTOR_DIM,)


def test_live_builder_metric_mutation():
    builder = LiveStateBuilder(services=["frontend", "orders"], mock=True)
    builder.set_mock_metric("frontend", "cpu_utilization", 85.0)
    builder.set_mock_metric("frontend", "latency_ms", 120.0)

    cluster_state = builder.build()
    assert cluster_state.observation_vector.shape == (10,)

    # Frontend CPU is at index 0
    assert cluster_state.observation_vector[0] == 85.0
    # Frontend Latency is at index 4
    assert cluster_state.observation_vector[4] == 120.0


def test_live_builder_to_dict():
    builder = LiveStateBuilder(services=DEFAULT_SERVICES, mock=True)
    cluster_state = builder.build()
    dict_repr = cluster_state.to_dict()

    assert "timestamp" in dict_repr
    assert "services" in dict_repr
    assert "observation_vector" in dict_repr
    assert len(dict_repr["observation_vector"]) == 20
    assert len(dict_repr["services"]) == 4
