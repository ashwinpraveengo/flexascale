"""
GNN Dependency Encoder for FlexaScale.

Encodes microservice call-graph topologies and per-service metric states
(CPU, Memory, Replicas, RPS, Latency) into a latent representation for
reinforcement learning autoscaling agents (PPO).

Architecture:
    Service Observation (B, N * 5)
                 │
                 ▼
    Batched Graph Reconstruction (B * N nodes, dynamic edge_index)
                 │
                 ▼
    Input Projection (5 → hidden_dim)
                 │
                 ▼
    PyG Graph Convolutions (GCNConv / GATConv / SAGEConv)
                 │
                 ▼
    Combined Readout (Global Mean Pooling + Per-Node State Embeddings)
                 │
                 ▼
    MLP Projection Head → Latent Features (B, features_dim)
"""

from __future__ import annotations

from typing import Any, Sequence
import gymnasium as gym
import torch
import torch.nn as nn
import torch.nn.functional as F
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from torch_geometric.nn import GATConv, GCNConv, SAGEConv, global_mean_pool

from flexascale.data.schema import VECTOR_DIM


# ---------------------------------------------------------------------------
# Dependency Graph Representation
# ---------------------------------------------------------------------------

DEFAULT_SERVICES: tuple[str, ...] = (
    "frontend",
    "orders",
    "inventory",
    "payments",
)
"""Canonical chain of microservices in the FlexaScale demo app."""

DEFAULT_EDGES: tuple[tuple[str, str], ...] = (
    ("frontend", "orders"),
    ("orders", "inventory"),
    ("inventory", "payments"),
)
"""Directed downstream request flow."""


class ServiceDependencyGraph:
    """
    Encapsulates cluster microservice topology and call-graph structure.

    Parameters
    ----------
    services : Sequence[str], optional
        List of service IDs acting as graph nodes. Defaults to the standard
        demo chain (frontend, orders, inventory, payments).
    edges : Sequence[tuple[str, str]], optional
        List of (caller, callee) directed edges.
    bidirectional : bool, default=True
        Whether to include reverse edges (callee → caller). In microservices,
        downstream bottlenecks and latency cascades propagate upstream.
    self_loops : bool, default=True
        Whether to add self-loops (node → node). Allows each service to retain
        its own local state representation during message passing.
    """

    def __init__(
        self,
        services: Sequence[str] = DEFAULT_SERVICES,
        edges: Sequence[tuple[str, str]] = DEFAULT_EDGES,
        bidirectional: bool = True,
        self_loops: bool = True,
    ) -> None:
        self.services = list(services)
        self.service_to_idx = {name: i for i, name in enumerate(self.services)}
        self.num_nodes = len(self.services)
        self.bidirectional = bidirectional
        self.self_loops = self_loops

        edge_list: set[tuple[int, int]] = set()

        # Add directed forward edges
        for u_name, v_name in edges:
            if u_name in self.service_to_idx and v_name in self.service_to_idx:
                u = self.service_to_idx[u_name]
                v = self.service_to_idx[v_name]
                edge_list.add((u, v))
                if self.bidirectional:
                    edge_list.add((v, u))

        # Add self-loops
        if self.self_loops:
            for i in range(self.num_nodes):
                edge_list.add((i, i))

        self.edges = sorted(list(edge_list))

    def get_edge_index(self, device: torch.device | None = None) -> torch.Tensor:
        """
        Returns the graph connectivity in COO format: shape ``(2, num_edges)``.
        """
        if not self.edges:
            return torch.empty((2, 0), dtype=torch.long, device=device)

        src = [e[0] for e in self.edges]
        dst = [e[1] for e in self.edges]
        return torch.tensor([src, dst], dtype=torch.long, device=device)


# ---------------------------------------------------------------------------
# Core PyTorch Geometric GNN Module
# ---------------------------------------------------------------------------

class GNNDependencyEncoder(nn.Module):
    """
    PyTorch Geometric Graph Neural Network that processes node feature vectors
    over a microservice call graph.

    Parameters
    ----------
    num_nodes : int
        Number of microservices in the cluster graph.
    in_channels : int
        Dimensionality of per-node features (default=VECTOR_DIM=5).
    hidden_dim : int
        Dimensionality of latent GNN node embeddings.
    out_dim : int
        Dimensionality of final output feature vector.
    conv_type : {"gcn", "gat", "sage"}
        Type of graph convolution layer to use.
    num_layers : int
        Number of graph convolutional message-passing layers.
    heads : int
        Number of attention heads (only used when conv_type="gat").
    dropout : float
        Dropout probability.
    use_layer_norm : bool
        Whether to apply LayerNorm across node embeddings.
    """

    def __init__(
        self,
        num_nodes: int = 4,
        in_channels: int = VECTOR_DIM,
        hidden_dim: int = 64,
        out_dim: int = 64,
        conv_type: str = "gcn",
        num_layers: int = 2,
        heads: int = 2,
        dropout: float = 0.0,
        use_layer_norm: bool = True,
    ) -> None:
        super().__init__()
        self.num_nodes = num_nodes
        self.in_channels = in_channels
        self.hidden_dim = hidden_dim
        self.out_dim = out_dim
        self.conv_type = conv_type.lower()
        self.num_layers = num_layers
        self.dropout = dropout
        self.use_layer_norm = use_layer_norm

        # 1. Input projection
        self.input_proj = nn.Linear(in_channels, hidden_dim)

        # 2. Graph convolutional layers
        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList() if use_layer_norm else None

        for _ in range(num_layers):
            if self.conv_type == "gcn":
                conv = GCNConv(hidden_dim, hidden_dim)
            elif self.conv_type == "gat":
                conv = GATConv(hidden_dim, hidden_dim, heads=heads, concat=False)
            elif self.conv_type == "sage":
                conv = SAGEConv(hidden_dim, hidden_dim)
            else:
                raise ValueError(
                    f"Unsupported conv_type '{conv_type}'. Expected 'gcn', 'gat', or 'sage'."
                )
            self.convs.append(conv)
            if self.use_layer_norm:
                self.norms.append(nn.LayerNorm(hidden_dim))

        # 3. Readout and output projection head
        # Readout combines:
        # - Global pooled graph embedding: (B, hidden_dim)
        # - Flattened per-node embeddings: (B, num_nodes * hidden_dim)
        combined_dim = hidden_dim + (num_nodes * hidden_dim)
        self.head = nn.Sequential(
            nn.Linear(combined_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(p=dropout) if dropout > 0.0 else nn.Identity(),
            nn.Linear(hidden_dim, out_dim),
        )

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        batch_idx: torch.Tensor,
        batch_size: int,
    ) -> torch.Tensor:
        """
        Forward pass.

        Parameters
        ----------
        x : torch.Tensor
            Batched node features of shape ``(batch_size * num_nodes, in_channels)``.
        edge_index : torch.Tensor
            Batched edge index of shape ``(2, num_batched_edges)``.
        batch_idx : torch.Tensor
            Graph assignment vector of shape ``(batch_size * num_nodes,)``.
        batch_size : int
            Number of graphs in this batch.

        Returns
        -------
        torch.Tensor
            Latent representation of shape ``(batch_size, out_dim)``.
        """
        # Project node features
        h = F.relu(self.input_proj(x))

        # Message passing layers
        for i, conv in enumerate(self.convs):
            h_new = conv(h, edge_index)
            if self.norms is not None:
                h_new = self.norms[i](h_new)
            h = F.relu(h_new)
            if self.dropout > 0.0 and self.training:
                h = F.dropout(h, p=self.dropout, training=self.training)

        # Global graph pooling
        global_repr = global_mean_pool(h, batch_idx)  # (batch_size, hidden_dim)

        # Per-service node representations
        node_repr = h.view(batch_size, self.num_nodes * self.hidden_dim)

        # Concatenate global cluster context with individual service representations
        combined = torch.cat([global_repr, node_repr], dim=-1)

        # Final projection to output latent dimension
        return self.head(combined)


# ---------------------------------------------------------------------------
# Stable-Baselines3 Features Extractor Wrapper
# ---------------------------------------------------------------------------

class GNNExtractor(BaseFeaturesExtractor):
    """
    Stable-Baselines3 feature extractor wrapper using PyTorch Geometric GNN.

    Converts flat SB3 observation vectors into batched graph structures,
    propagates representations over the service call graph, and returns
    latent features for the PPO policy and value heads.

    Parameters
    ----------
    observation_space : gym.Space
        Gymnasium observation space (Box of size ``num_nodes * VECTOR_DIM``).
    features_dim : int
        Target dimension of the extracted feature vector (fed to PPO actor-critic).
    dependency_graph : ServiceDependencyGraph, optional
        Microservice call graph. If not specified, uses the default 4-service chain.
    hidden_dim : int
        Internal hidden dimension of the GNN layers.
    conv_type : {"gcn", "gat", "sage"}
        GNN layer type.
    num_layers : int
        Number of GNN layers.
    dropout : float
        Dropout probability.
    """

    def __init__(
        self,
        observation_space: gym.Space,
        features_dim: int = 64,
        dependency_graph: ServiceDependencyGraph | None = None,
        hidden_dim: int = 64,
        conv_type: str = "gcn",
        num_layers: int = 2,
        dropout: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(observation_space, features_dim)

        self.graph = dependency_graph or ServiceDependencyGraph()
        self.num_nodes = self.graph.num_nodes
        self.node_features_dim = VECTOR_DIM

        # Register edge_index as buffer so it moves with model to CPU/GPU
        base_edges = self.graph.get_edge_index()
        self.register_buffer("base_edge_index", base_edges)

        # Initialize core GNN encoder
        self.encoder = GNNDependencyEncoder(
            num_nodes=self.num_nodes,
            in_channels=self.node_features_dim,
            hidden_dim=hidden_dim,
            out_dim=features_dim,
            conv_type=conv_type,
            num_layers=num_layers,
            dropout=dropout,
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        """
        Processes a batch of flat observation vectors from SB3.

        Parameters
        ----------
        observations : torch.Tensor
            Observation batch of shape ``(B, num_nodes * node_features_dim)``.

        Returns
        -------
        torch.Tensor
            Latent features of shape ``(B, features_dim)``.
        """
        batch_size = observations.shape[0]
        device = observations.device
        expected_dim = self.num_nodes * self.node_features_dim

        # If observation is single-service (e.g. VECTOR_DIM), repeat/pad for full graph
        if observations.shape[1] != expected_dim:
            if observations.shape[1] == self.node_features_dim:
                # Expand single service observation to all nodes for compatibility
                observations = observations.repeat(1, self.num_nodes)
            else:
                raise ValueError(
                    f"Observation dimension {observations.shape[1]} does not match "
                    f"expected {expected_dim} ({self.num_nodes} nodes * {self.node_features_dim} features)."
                )

        # Reshape to disjoint graph node tensor: (B * num_nodes, node_features_dim)
        x = observations.view(batch_size * self.num_nodes, self.node_features_dim)

        # Dynamic batched edge index construction
        # For batch b, edge indices are offset by b * num_nodes
        offsets = (
            torch.arange(batch_size, device=device, dtype=self.base_edge_index.dtype)
            * self.num_nodes
        ).view(batch_size, 1, 1)

        # (2, E) -> (B, 2, E) + (B, 1, 1) -> (B, 2, E) -> (2, B, E) -> (2, B * E)
        batched_edges = (
            (self.base_edge_index.unsqueeze(0) + offsets)
            .permute(1, 0, 2)
            .reshape(2, -1)
        )

        # Graph indicator vector for global pooling: [0, 0, 0, 0, 1, 1, 1, 1, ...]
        batch_idx = torch.arange(batch_size, device=device).repeat_interleave(
            self.num_nodes
        )

        return self.encoder(
            x=x,
            edge_index=batched_edges,
            batch_idx=batch_idx,
            batch_size=batch_size,
        )
