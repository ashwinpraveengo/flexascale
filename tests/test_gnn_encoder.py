"""
Unit and integration tests for the PyTorch Geometric GNN Dependency Encoder.

Covers:
1. ServiceDependencyGraph construction, edge indices, bidirectional propagation, and self-loops.
2. GNNDependencyEncoder forward pass, output shape, and gradient flow.
3. Multi-layer GNN support with various convolution backends (GCN, GAT, GraphSAGE).
4. GNNExtractor integration with Gymnasium observation spaces.
5. End-to-end integration with Stable-Baselines3 PPO policy and training loop.
"""

import gymnasium as gym
import numpy as np
import pytest
import torch
from gymnasium import spaces

from flexascale.data.schema import VECTOR_DIM
from flexascale.rl.gnn_encoder import (
    DEFAULT_EDGES,
    DEFAULT_SERVICES,
    GNNDependencyEncoder,
    GNNExtractor,
    ServiceDependencyGraph,
)
from flexascale.rl.ppo_agent import PPOAgentManager
from flexascale.simulator.mock_env import MockClusterEnv


# ---------------------------------------------------------------------------
# 1. ServiceDependencyGraph Tests
# ---------------------------------------------------------------------------

class TestServiceDependencyGraph:

    def test_default_graph(self):
        graph = ServiceDependencyGraph()
        assert graph.num_nodes == 4
        assert graph.services == list(DEFAULT_SERVICES)
        assert graph.bidirectional is True
        assert graph.self_loops is True

        edge_index = graph.get_edge_index()
        assert isinstance(edge_index, torch.Tensor)
        assert edge_index.shape[0] == 2
        assert edge_index.dtype == torch.long

        # Default edges: 3 forward edges + 3 backward edges + 4 self-loops = 10 unique edges
        assert edge_index.shape[1] == 10

    def test_directed_graph_without_self_loops(self):
        graph = ServiceDependencyGraph(bidirectional=False, self_loops=False)
        edge_index = graph.get_edge_index()
        # 3 directed edges
        assert edge_index.shape == (2, 3)
        src = edge_index[0].tolist()
        dst = edge_index[1].tolist()
        assert list(zip(src, dst)) == [(0, 1), (1, 2), (2, 3)]

    def test_custom_graph(self):
        services = ["svc_a", "svc_b", "svc_c"]
        edges = [("svc_a", "svc_b"), ("svc_b", "svc_c")]
        graph = ServiceDependencyGraph(
            services=services, edges=edges, bidirectional=False, self_loops=True
        )
        assert graph.num_nodes == 3
        edge_index = graph.get_edge_index()
        # 2 directed edges + 3 self loops = 5 edges
        assert edge_index.shape == (2, 5)


# ---------------------------------------------------------------------------
# 2. GNNDependencyEncoder Tests
# ---------------------------------------------------------------------------

class TestGNNDependencyEncoder:

    @pytest.mark.parametrize("conv_type", ["gcn", "gat", "sage"])
    def test_forward_pass_convolutions(self, conv_type):
        num_nodes = 4
        in_channels = 5
        hidden_dim = 32
        out_dim = 16
        batch_size = 4

        encoder = GNNDependencyEncoder(
            num_nodes=num_nodes,
            in_channels=in_channels,
            hidden_dim=hidden_dim,
            out_dim=out_dim,
            conv_type=conv_type,
        )

        graph = ServiceDependencyGraph()
        base_edges = graph.get_edge_index()

        # Create batched graph
        offsets = (torch.arange(batch_size) * num_nodes).view(batch_size, 1, 1)
        batched_edges = (base_edges.unsqueeze(0) + offsets).permute(1, 0, 2).reshape(2, -1)
        batch_idx = torch.arange(batch_size).repeat_interleave(num_nodes)
        x = torch.randn(batch_size * num_nodes, in_channels)

        out = encoder(x, batched_edges, batch_idx, batch_size=batch_size)
        assert out.shape == (batch_size, out_dim)
        assert not torch.isnan(out).any()

    def test_gradient_flow(self):
        encoder = GNNDependencyEncoder(
            num_nodes=4,
            in_channels=5,
            hidden_dim=32,
            out_dim=16,
            conv_type="gcn",
        )
        graph = ServiceDependencyGraph()
        base_edges = graph.get_edge_index()

        batch_size = 2
        offsets = (torch.arange(batch_size) * 4).view(batch_size, 1, 1)
        batched_edges = (base_edges.unsqueeze(0) + offsets).permute(1, 0, 2).reshape(2, -1)
        batch_idx = torch.arange(batch_size).repeat_interleave(4)
        x = torch.randn(batch_size * 4, 5, requires_grad=True)

        out = encoder(x, batched_edges, batch_idx, batch_size=batch_size)
        loss = out.sum()
        loss.backward()

        # Check gradients exist for weights
        assert encoder.input_proj.weight.grad is not None
        assert encoder.head[0].weight.grad is not None
        assert x.grad is not None

    def test_invalid_conv_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported conv_type"):
            GNNDependencyEncoder(conv_type="invalid_conv")


# ---------------------------------------------------------------------------
# 3. GNNExtractor SB3 Integration Tests
# ---------------------------------------------------------------------------

class TestGNNExtractor:

    def test_extractor_single_sample(self):
        num_services = 4
        obs_dim = num_services * VECTOR_DIM
        obs_space = spaces.Box(low=0.0, high=100.0, shape=(obs_dim,), dtype=np.float32)

        extractor = GNNExtractor(obs_space, features_dim=64, conv_type="gcn")
        assert extractor.features_dim == 64

        sample_obs = torch.randn(1, obs_dim)
        out = extractor(sample_obs)
        assert out.shape == (1, 64)
        assert not torch.isnan(out).any()

    def test_extractor_batched_samples(self):
        num_services = 4
        obs_dim = num_services * VECTOR_DIM
        obs_space = spaces.Box(low=0.0, high=100.0, shape=(obs_dim,), dtype=np.float32)

        extractor = GNNExtractor(obs_space, features_dim=32, conv_type="sage")
        batch_size = 16
        sample_obs = torch.randn(batch_size, obs_dim)
        out = extractor(sample_obs)
        assert out.shape == (batch_size, 32)

    def test_single_service_obs_auto_expansion(self):
        # Single service observation space (e.g. 5)
        obs_space = spaces.Box(low=0.0, high=100.0, shape=(VECTOR_DIM,), dtype=np.float32)
        extractor = GNNExtractor(obs_space, features_dim=32)

        sample_obs = torch.randn(4, VECTOR_DIM)
        out = extractor(sample_obs)
        assert out.shape == (4, 32)


# ---------------------------------------------------------------------------
# 4. End-to-End PPO Agent Training Loop
# ---------------------------------------------------------------------------

class TestPPOIntegration:

    def test_ppo_predict_and_learn_step(self, tmp_path):
        env = MockClusterEnv(num_services=4)

        agent_manager = PPOAgentManager(
            env=env,
            tensorboard_log_dir=str(tmp_path / "tb"),
            features_extractor_class=GNNExtractor,
            features_extractor_kwargs=dict(
                features_dim=32,
                hidden_dim=32,
                conv_type="gcn",
            ),
            n_steps=32,
            batch_size=16,
            n_epochs=2,
        )

        obs, _ = env.reset()
        action, _ = agent_manager.model.predict(obs, deterministic=True)
        assert env.action_space.contains(action)

        # Run a short learning step
        agent_manager.model.learn(total_timesteps=64)
