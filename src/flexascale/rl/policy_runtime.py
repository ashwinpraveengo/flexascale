"""
Inference runtime for trained FlexaScale PPO + GNN policies.

A trained policy has a fixed input topology: ``K`` services (``K * 5`` floats)
and ``K`` categorical action heads. Live applications have ``N`` services.

* ``N == K``  -> ``ppo_direct``: one forward pass over all services (not for
  models whose card sets ``decision_slot``: those always use windows).
* ``N != K``  -> ``ppo_neighborhood``: the *same trained weights* are applied
  once per service on a K-node window made of that service (slot 0) and its
  nearest neighbours in the dependency graph (breadth-first, ties broken by
  name). Missing slots are padded with an idle service. Only the slot-0
  action and probability are used.

Observation versions (read from the model card next to the model):

* 1: ``[cpu%, mem%, replicas, rps, latency_ms]`` in raw units (v1-v3 models).
* 2: ``[cpu/req, mem/limit, replicas/max, rps trend, latency/SLO]``, unit-free
  (v4+, ``simulator/dependency_env.py``). Trained with "slot i calls slot
  i+1", so neighbourhood windows list callees before callers.

No untrained parameters are ever used to make a decision. The GNN encoder's
experimental ``node_policy_head`` is *not* trained by PPO and is deliberately
not used here.

Confidence is the policy's probability of the chosen (argmax) action, which
the safety layer compares with its activation/deactivation thresholds.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch

from flexascale.data.schema import VECTOR_DIM, VECTOR_FIELDS

logger = logging.getLogger(__name__)

V2_FIELDS = ("cpu_fraction", "memory_fraction", "replica_fraction", "rps_trend", "latency_slo_ratio")
"""Must match flexascale.simulator.dependency_env.FEATURE_NAMES (checked in tests)."""

IDLE_NODE = np.array([0.0, 0.0, 1.0, 0.0, 0.0], dtype=np.float32)
IDLE_NODE_V2 = np.array([0.0, 0.0, 0.1, 1.0, 0.0], dtype=np.float32)


@dataclass
class PolicyOutput:
    actions: List[int]
    confidences: List[float]
    mode: str
    """'ppo_direct' or 'ppo_neighborhood'."""
    windows: List[List[str]] = field(default_factory=list)
    """Per-service list of services fed to the policy (slot order)."""
    clipped: List[List[str]] = field(default_factory=list)
    """Per-service features clipped to the trained observation bounds."""
    probabilities: List[List[float]] = field(default_factory=list)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def neighborhood_order(
    target: str,
    services: Sequence[str],
    edges: Sequence[Tuple[str, str]],
    callees_first: bool = False,
) -> List[str]:
    """
    Breadth-first ordering of ``services`` from ``target`` over undirected edges.

    With ``callees_first`` each node's callees are visited before its callers,
    so the window follows the call chain downstream first.
    """
    callees: Dict[str, set] = {s: set() for s in services}
    callers: Dict[str, set] = {s: set() for s in services}
    for u, v in edges:
        if u in callees and v in callees and u != v:
            callees[u].add(v)
            callers[v].add(u)
    order = [target]
    seen = {target}
    queue = deque([target])
    while queue:
        node = queue.popleft()
        if callees_first:
            nexts = sorted(callees[node]) + sorted(callers[node] - callees[node])
        else:
            nexts = sorted(callees[node] | callers[node])
        for nxt in nexts:
            if nxt not in seen:
                seen.add(nxt)
                order.append(nxt)
                queue.append(nxt)
    return order


class PolicyRuntime:
    """Loads a trained SB3 PPO model and evaluates it on live observations."""

    def __init__(self, model_path: str | Path, device: str = "cpu") -> None:
        from stable_baselines3 import PPO

        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"PPO model not found: {self.model_path}")
        self.model = PPO.load(str(self.model_path), device=device)
        self.model.policy.set_training_mode(False)

        space = self.model.action_space
        if hasattr(space, "nvec"):
            self.num_slots = int(len(space.nvec))
        elif hasattr(space, "n"):
            self.num_slots = 1
        else:
            raise ValueError(f"Unsupported action space {space}")
        obs_space = self.model.observation_space
        expected = self.num_slots * VECTOR_DIM
        if obs_space.shape != (expected,):
            raise ValueError(
                f"Model observation shape {obs_space.shape} does not match {self.num_slots} services x {VECTOR_DIM}"
            )
        self.obs_low = obs_space.low.astype(np.float32)
        self.obs_high = obs_space.high.astype(np.float32)
        self.sha256 = _sha256(self.model_path)

        self.card: Optional[Dict[str, Any]] = None
        for card_path in (self.model_path.parent / "model_card.json", self.model_path.parent.parent / "model_card.json"):
            if card_path.is_file():
                self.card = json.loads(card_path.read_text())
                break
        self.extractor = type(self.model.policy.features_extractor).__name__
        obs_card = (self.card or {}).get("observation") or {}
        # Unit-free (v2) models have every feature bounded by a small constant; raw-unit
        # (v1) models have a CPU bound of 100. The bounds are stored inside the model zip,
        # so the input version is known even without a model card.
        inferred = 2 if float(self.obs_high[0]) <= 1.0 else 1
        self.observation_version = int(obs_card.get("version", inferred))
        if self.observation_version != inferred:
            raise ValueError(
                f"Model card says observation version {self.observation_version} but the model's "
                f"observation bounds indicate version {inferred}"
            )
        default_fields = V2_FIELDS if self.observation_version >= 2 else VECTOR_FIELDS
        self.field_names: List[str] = list(obs_card.get("per_service_fields") or default_fields)
        self.max_replicas = int(obs_card.get("max_replicas") or (self.card or {}).get("environment", {}).get("max_replicas") or 10)
        self.idle_node = IDLE_NODE_V2 if self.observation_version >= 2 else IDLE_NODE
        self.callees_first = self.observation_version >= 2
        # Models trained with 'focal' control have only one trained decision head (slot 0):
        # always evaluate them on per-service windows, never all heads at once.
        self.decision_slot = obs_card.get("decision_slot")
        # Replica change per action index (v6+: -2..+3; earlier models: -1, 0, +1).
        n_actions = int(space.nvec[0]) if hasattr(space, "nvec") else int(space.n)
        self.action_deltas: List[int] = [int(d) for d in ((self.card or {}).get("action") or {}).get("deltas") or [-1, 0, 1]]
        if len(self.action_deltas) != n_actions:
            raise ValueError(f"Model has {n_actions} actions per service but its card lists deltas {self.action_deltas}")

    # ------------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        card = self.card or {}
        return {
            "model_path": str(self.model_path),
            "sha256": self.sha256,
            "extractor": self.extractor,
            "trained_services": self.num_slots,
            "observation_dim": int(self.num_slots * VECTOR_DIM),
            "observation_version": self.observation_version,
            "observation_fields": list(self.field_names),
            "max_replicas": self.max_replicas,
            "decision_slot": self.decision_slot,
            "action_deltas": list(self.action_deltas),
            "num_timesteps": int(getattr(self.model, "num_timesteps", 0)),
            "model_card": bool(self.card),
            "trained_at": card.get("trained_at"),
            "units": (card.get("observation") or {}).get("units"),
            "validation": card.get("validation"),
        }

    def _clip(self, obs: np.ndarray) -> Tuple[np.ndarray, List[str]]:
        low = self.obs_low[:VECTOR_DIM]
        high = self.obs_high[:VECTOR_DIM]
        clipped = np.clip(obs, low, high)
        names = [self.field_names[i] for i in range(VECTOR_DIM) if obs[i] != clipped[i]]
        return clipped.astype(np.float32), names

    def _distribution_probs(self, batch: np.ndarray) -> List[torch.Tensor]:
        obs_tensor = torch.as_tensor(batch, dtype=torch.float32, device=self.model.device)
        with torch.no_grad():
            dist = self.model.policy.get_distribution(obs_tensor)
        inner = dist.distribution
        if isinstance(inner, list):
            return [d.probs for d in inner]
        return [inner.probs]

    def predict(
        self,
        features: Dict[str, np.ndarray],
        edges: Sequence[Tuple[str, str]] = (),
    ) -> PolicyOutput:
        """
        Args:
            features: service name -> 5-vector in this model's observation version
                      (see module docstring). Services are evaluated in sorted-name order.
            edges: (caller, callee) dependency edges between those services.
        Returns:
            PolicyOutput aligned with ``sorted(features)``.
        """
        services = sorted(features)
        if not services:
            return PolicyOutput([], [], mode="ppo_direct")
        clipped: Dict[str, Tuple[np.ndarray, List[str]]] = {
            s: self._clip(np.asarray(features[s], dtype=np.float32)) for s in services
        }
        k = self.num_slots

        if len(services) == k and self.decision_slot is None:
            order = neighborhood_order(services[0], services, edges, self.callees_first) if edges else list(services)
            order += [s for s in services if s not in order]
            row = np.concatenate([clipped[s][0] for s in order])[None, :]
            probs = self._distribution_probs(row)
            by_service: Dict[str, Tuple[int, float, List[float]]] = {}
            for slot, svc in enumerate(order):
                p = probs[slot][0]
                a = int(torch.argmax(p).item())
                by_service[svc] = (a, float(p[a].item()), [round(float(x), 4) for x in p.tolist()])
            return PolicyOutput(
                actions=[by_service[s][0] for s in services],
                confidences=[by_service[s][1] for s in services],
                mode="ppo_direct",
                windows=[order for _ in services],
                clipped=[clipped[s][1] for s in services],
                probabilities=[by_service[s][2] for s in services],
            )

        rows = []
        windows = []
        for svc in services:
            order = neighborhood_order(svc, services, edges, self.callees_first)
            if len(order) < k:
                # Fill from services outside the connected component, by name, before padding.
                order += [s for s in services if s not in order][: k - len(order)]
            window = order[:k]
            parts = [clipped[s][0] for s in window]
            parts += [self.idle_node] * (k - len(parts))
            rows.append(np.concatenate(parts))
            windows.append(window)
        probs = self._distribution_probs(np.stack(rows))[0]
        actions = torch.argmax(probs, dim=-1)
        conf = probs.gather(1, actions[:, None]).squeeze(1)
        return PolicyOutput(
            actions=[int(a) for a in actions.tolist()],
            confidences=[float(c) for c in conf.tolist()],
            mode="ppo_neighborhood",
            windows=windows,
            clipped=[clipped[s][1] for s in services],
            probabilities=[[round(float(x), 4) for x in row] for row in probs.tolist()],
        )
