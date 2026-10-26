"""
Graph actor-critic for PPO (FlexaScale v7): one decision per service from message passing
over the application's call graph (docs/POLICY_V7.md §4).

The observation is ``features_v3.pack``: node features, the caller->callee adjacency and a
node mask, padded to ``n_max`` services. Two rounds of message passing combine each
service's own features with the mean of its callees' and the mean of its callers'
embeddings (separate weights per direction), so a decision can use where load comes
from and where it goes. A shared per-node head turns each embedding into logits over
replica changes; padded nodes get a fixed "hold" distribution, which contributes nothing
to the log-probability or the entropy. The critic reads the masked mean of the
embeddings. ``use_graph=False`` drops the messages (the no-graph ablation): the same
network then decides from each service's own features only.

Every parameter that produces a decision is trained by PPO.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type

import torch
from gymnasium import spaces
from stable_baselines3.common.policies import ActorCriticPolicy
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from torch import nn

from flexascale.rl.features_v3 import F as N_FEATURES


def _unpack(obs: torch.Tensor, n_max: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    b = obs.shape[0]
    x = obs[:, : n_max * N_FEATURES].reshape(b, n_max, N_FEATURES)
    adj = obs[:, n_max * N_FEATURES: n_max * N_FEATURES + n_max * n_max].reshape(b, n_max, n_max)
    mask = obs[:, n_max * N_FEATURES + n_max * n_max:]
    return x, adj, mask


class GraphExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space: spaces.Box, n_max: int, hidden: int = 64, rounds: int = 2,
                 use_graph: bool = True) -> None:
        super().__init__(observation_space, features_dim=n_max * hidden + n_max + hidden)
        self.n_max, self.hidden, self.rounds, self.use_graph = n_max, hidden, rounds, use_graph
        self.inp = nn.Linear(N_FEATURES, hidden)
        self.self_w = nn.ModuleList([nn.Linear(hidden, hidden) for _ in range(rounds)])
        self.callee_w = nn.ModuleList([nn.Linear(hidden, hidden, bias=False) for _ in range(rounds)])
        self.caller_w = nn.ModuleList([nn.Linear(hidden, hidden, bias=False) for _ in range(rounds)])
        self.norm = nn.ModuleList([nn.LayerNorm(hidden) for _ in range(rounds)])

    def embed(self, obs: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Node embeddings (B, N, H), node mask (B, N) and the masked mean embedding (B, H)."""
        x, adj, mask = _unpack(obs, self.n_max)
        m = mask.unsqueeze(-1)
        h = torch.relu(self.inp(x)) * m
        if self.use_graph:
            deg_out = adj.sum(-1, keepdim=True).clamp(min=1.0)
            deg_in = adj.sum(-2).unsqueeze(-1).clamp(min=1.0)
        for k in range(self.rounds):
            z = self.self_w[k](h)
            if self.use_graph:
                z = z + self.callee_w[k](torch.bmm(adj, h) / deg_out) + self.caller_w[k](torch.bmm(adj.transpose(1, 2), h) / deg_in)
            h = (h + torch.relu(self.norm[k](z))) * m
        pooled = (h * m).sum(1) / m.sum(1).clamp(min=1.0)
        return h, mask, pooled

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        h, mask, pooled = self.embed(obs)
        return torch.cat([h.reshape(h.shape[0], -1), mask, pooled], dim=1)


class GraphFocalExtractor(GraphExtractor):
    """
    Per-service decisions with per-service credit (amendment 2): the observation is the packed application
    plus a one-hot of the deciding ("focal") service. Features = that service's embedding after message
    passing over the call graph, and the mean embedding of the application.
    """

    def __init__(self, observation_space: spaces.Box, n_max: int, hidden: int = 64, rounds: int = 2,
                 use_graph: bool = True) -> None:
        super().__init__(observation_space, n_max, hidden, rounds, use_graph)
        self._features_dim = 2 * hidden

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        graph, focal = obs[:, :-self.n_max], obs[:, -self.n_max:]
        h, _, pooled = self.embed(graph)
        own = (h * focal.unsqueeze(-1)).sum(1)
        return torch.cat([own, pooled], dim=1)


class _Split(nn.Module):
    """Actor gets node embeddings + mask; critic gets the pooled embedding."""

    def __init__(self, n_max: int, hidden: int) -> None:
        super().__init__()
        self.cut = n_max * hidden + n_max
        self.latent_dim_pi = self.cut
        self.latent_dim_vf = hidden

    def forward(self, f: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        return self.forward_actor(f), self.forward_critic(f)

    def forward_actor(self, f: torch.Tensor) -> torch.Tensor:
        return f[:, : self.cut]

    def forward_critic(self, f: torch.Tensor) -> torch.Tensor:
        return f[:, self.cut:]


class PerNodeHead(nn.Module):
    def __init__(self, n_max: int, hidden: int, n_actions: int, hold_index: int, hold_bias: float = 0.0) -> None:
        super().__init__()
        self.n_max, self.hidden, self.n_actions = n_max, hidden, n_actions
        self.lin = nn.Linear(hidden, n_actions)
        nn.init.orthogonal_(self.lin.weight, gain=0.01)
        nn.init.zeros_(self.lin.bias)
        with torch.no_grad():  # start near "hold": with deltas -1..+3, uniform exploration drifts upward by +1 per decision
            self.lin.bias[hold_index] = hold_bias
        hold = torch.full((n_actions,), -30.0)
        hold[hold_index] = 30.0
        self.register_buffer("hold", hold)

    def forward(self, latent: torch.Tensor) -> torch.Tensor:
        b = latent.shape[0]
        h = latent[:, : self.n_max * self.hidden].reshape(b, self.n_max, self.hidden)
        mask = latent[:, self.n_max * self.hidden:].unsqueeze(-1)
        logits = self.lin(h)
        logits = torch.where(mask > 0.5, logits, self.hold.expand_as(logits))
        return logits.reshape(b, self.n_max * self.n_actions)


class GraphPolicy(ActorCriticPolicy):
    def __init__(self, observation_space: spaces.Space, action_space: spaces.MultiDiscrete, lr_schedule,
                 n_max: int = 20, hidden: int = 64, rounds: int = 2, use_graph: bool = True, hold_index: int = 1,
                 hold_bias: float = 0.0, **kwargs: Any) -> None:
        self._n_max, self._hidden, self._hold, self._hold_bias = n_max, hidden, hold_index, hold_bias
        kwargs.setdefault("ortho_init", False)
        super().__init__(observation_space, action_space, lr_schedule,
                         features_extractor_class=GraphExtractor,
                         features_extractor_kwargs={"n_max": n_max, "hidden": hidden, "rounds": rounds, "use_graph": use_graph},
                         share_features_extractor=True, **kwargs)

    def _build_mlp_extractor(self) -> None:
        self.mlp_extractor = _Split(self._n_max, self._hidden)

    def _build(self, lr_schedule) -> None:
        super()._build(lr_schedule)
        n_actions = int(self.action_space.nvec[0])
        self.action_net = PerNodeHead(self._n_max, self._hidden, n_actions, self._hold, self._hold_bias)
        self.optimizer = self.optimizer_class(self.parameters(), lr=lr_schedule(1), **self.optimizer_kwargs)

    def _get_constructor_parameters(self) -> Dict[str, Any]:
        data = super()._get_constructor_parameters()
        fe = data.pop("features_extractor_kwargs", {})
        for k in ("features_extractor_class", "share_features_extractor", "net_arch"):
            data.pop(k, None)
        data.update(n_max=fe.get("n_max", self._n_max), hidden=fe.get("hidden", self._hidden),
                    rounds=fe.get("rounds", 2), use_graph=fe.get("use_graph", True), hold_index=self._hold,
                    hold_bias=self._hold_bias)
        return data
