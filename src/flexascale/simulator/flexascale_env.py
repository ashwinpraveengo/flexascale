"""
FlexaScale Gymnasium simulation environment.

Replays the processed Alibaba trace and exposes the shared
``ServiceState`` vector as the RL observation.  A simple but
transparent capacity model simulates the effect of the agent's
scaling decisions on CPU, memory, and latency.

Intended consumers:
    - GNN dependency encoder
    - PPO actor-critic (via Stable-Baselines3)
    - Confidence / training loop
    - Eventually the live-state pipeline

Example::

    from flexascale.simulator.flexascale_env import FlexaScaleEnv

    env = FlexaScaleEnv()
    obs, info = env.reset(seed=42)

    for _ in range(100):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            obs, info = env.reset()

Vector layout (index → field) — identical to ``schema.VECTOR_FIELDS``:
    0  cpu_utilization    (float, %)
    1  memory_utilization (float, %)
    2  replica_count      (float, cast from int)
    3  request_rate       (float, req/s)
    4  latency_ms         (float, ms)

Action semantics (``Discrete(3)``):
    0  scale down   (−1 replica)
    1  maintain     (no-op)
    2  scale up     (+1 replica)

Reward components:
    slo_reward        +1.0 when latency ≤ target, else −(latency/target − 1)
    efficiency_reward −|cpu − cpu_target| / 100
    stability_penalty −0.1 × |Δreplicas|
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

from flexascale.config.env_config import EnvConfig
from flexascale.data.schema import VECTOR_DIM, VECTOR_FIELDS

logger = logging.getLogger(__name__)


# ── Action constants ──────────────────────────────────────────────────

ACTION_SCALE_DOWN: int = 0
ACTION_MAINTAIN: int = 1
ACTION_SCALE_UP: int = 2
NUM_ACTIONS: int = 3

_ACTION_LABELS: dict[int, str] = {
    ACTION_SCALE_DOWN: "scale_down",
    ACTION_MAINTAIN: "maintain",
    ACTION_SCALE_UP: "scale_up",
}


class FlexaScaleEnv(gym.Env):
    """
    Gymnasium environment that replays the Alibaba trace for a single
    service and simulates the impact of scaling decisions.

    Parameters
    ----------
    config : EnvConfig, optional
        All tuneable knobs.  See :class:`~flexascale.config.env_config.EnvConfig`.
    """

    metadata: dict[str, Any] = {"render_modes": ["human"]}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, config: EnvConfig | None = None) -> None:
        super().__init__()

        self.config = config or EnvConfig()

        # ── Load dataset once ─────────────────────────────────────────
        self._df = self._load_dataset(self.config.dataset_path)

        # Pre-compute sorted unique timestamps and service IDs.
        self._all_timestamps: np.ndarray = np.sort(
            self._df["timestamp"].unique()
        )
        self._all_service_ids: list[str] = sorted(
            self._df["service_id"].unique().tolist()
        )

        logger.info(
            "Loaded dataset: %d rows, %d timestamps, %d services",
            len(self._df),
            len(self._all_timestamps),
            len(self._all_service_ids),
        )

        # ── Gymnasium spaces ──────────────────────────────────────────
        # Observation: matches VECTOR_FIELDS exactly.
        low = np.array(
            [0.0, 0.0, float(self.config.min_replicas), 0.0, 0.0],
            dtype=np.float32,
        )
        high = np.array(
            [
                100.0,
                100.0,
                float(self.config.max_replicas),
                self.config.obs_max_rps,
                self.config.obs_max_latency,
            ],
            dtype=np.float32,
        )
        self.observation_space = spaces.Box(
            low=low, high=high, shape=(VECTOR_DIM,), dtype=np.float32
        )

        # Action: discrete {scale_down, maintain, scale_up}
        self.action_space = spaces.Discrete(NUM_ACTIONS)

        # ── Episode state (set properly in reset()) ───────────────────
        self._service_id: str = ""
        self._service_trace: pd.DataFrame = pd.DataFrame()
        self._trace_timestamps: np.ndarray = np.array([])
        self._step_idx: int = 0
        self._simulated_replicas: int = 1
        self._prev_replicas: int = 1

    # ------------------------------------------------------------------
    # Gymnasium API
    # ------------------------------------------------------------------

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """
        Reset the environment to the start of a new episode.

        Parameters
        ----------
        seed : int, optional
            Seed for the internal PRNG (Gymnasium convention).
        options : dict, optional
            Currently unused; reserved for future extensions.

        Returns
        -------
        observation : np.ndarray
            Initial state vector of shape ``(VECTOR_DIM,)``.
        info : dict
            Diagnostic information about the initial state.
        """
        super().reset(seed=seed)

        # ── Select service ────────────────────────────────────────────
        if self.config.service_id is not None:
            self._service_id = self.config.service_id
        else:
            idx = self.np_random.integers(0, len(self._all_service_ids))
            self._service_id = self._all_service_ids[int(idx)]

        # ── Extract & sort this service's trace ───────────────────────
        self._service_trace = (
            self._df[self._df["service_id"] == self._service_id]
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        if self._service_trace.empty:
            raise ValueError(
                f"No trace data found for service '{self._service_id}'"
            )

        self._trace_timestamps = self._service_trace["timestamp"].values
        self._step_idx = 0

        # ── Initialise simulated replicas from trace ──────────────────
        initial_replicas = int(
            self._service_trace.iloc[0]["replica_count"]
        )
        self._simulated_replicas = np.clip(
            initial_replicas,
            self.config.min_replicas,
            self.config.max_replicas,
        )
        self._prev_replicas = self._simulated_replicas

        logger.debug(
            "reset: service=%s, timesteps=%d, initial_replicas=%d",
            self._service_id,
            len(self._trace_timestamps),
            self._simulated_replicas,
        )

        obs = self._build_observation()
        info = self._build_info(reward_components=None)
        return obs, info

    def step(
        self, action: int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """
        Execute one simulation step.

        Parameters
        ----------
        action : int
            One of ``{0: scale_down, 1: maintain, 2: scale_up}``.

        Returns
        -------
        observation : np.ndarray
        reward : float
        terminated : bool
            ``True`` when the trace is exhausted.
        truncated : bool
            Always ``False`` (no time-limit truncation in this env).
        info : dict
        """
        assert self.action_space.contains(action), (
            f"Invalid action {action!r}; expected one of "
            f"{{0, 1, 2}} (scale_down, maintain, scale_up)"
        )

        # ── 1. Apply scaling action ───────────────────────────────────
        self._prev_replicas = self._simulated_replicas
        delta = action - 1  # maps {0,1,2} → {-1, 0, +1}
        new_replicas = self._simulated_replicas + delta
        self._simulated_replicas = int(
            np.clip(
                new_replicas,
                self.config.min_replicas,
                self.config.max_replicas,
            )
        )

        # ── 2. Advance trace ─────────────────────────────────────────
        self._step_idx += 1
        terminated = self._step_idx >= len(self._service_trace)

        if terminated:
            # Return the last valid observation with a zero reward.
            self._step_idx = len(self._service_trace) - 1
            obs = self._build_observation()
            info = self._build_info(reward_components=None)
            return obs, 0.0, True, False, info

        # ── 3. Build observation & reward ─────────────────────────────
        obs = self._build_observation()
        reward, components = self._compute_reward(obs)
        info = self._build_info(reward_components=components)

        return obs, reward, False, False, info

    def render(self) -> None:
        """Print a human-readable summary of the current state."""
        if self._service_trace.empty:
            print("[FlexaScaleEnv] Not initialised — call reset() first.")
            return

        row = self._service_trace.iloc[self._step_idx]
        obs = self._build_observation()
        print(
            f"[t={int(row['timestamp']):>8d}] "
            f"service={self._service_id[:12]}... "
            f"replicas={self._simulated_replicas:>3d} "
            f"cpu={obs[0]:.2f}% "
            f"mem={obs[1]:.2f}% "
            f"rps={obs[3]:.1f} "
            f"latency={obs[4]:.1f}ms"
        )

    def close(self) -> None:
        """Release resources (no-op for this environment)."""
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_dataset(path: str) -> pd.DataFrame:
        """
        Load the processed CSV.  Validates required columns exist.

        The file is treated as **read-only** — no in-place mutation.
        """
        csv_path = Path(path)
        if not csv_path.is_file():
            raise FileNotFoundError(
                f"Processed dataset not found at '{csv_path.resolve()}'. "
                "Run the Phase 1 build_dataset.py pipeline first."
            )

        df = pd.read_csv(csv_path)

        required = {"timestamp", "service_id"} | set(VECTOR_FIELDS)
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"Dataset is missing required columns: {sorted(missing)}"
            )

        return df

    def _build_observation(self) -> np.ndarray:
        """
        Construct the Gymnasium observation from the current trace row
        and the simulated replica count.

        The capacity model applies a simple ratio-based adjustment:
        if the agent is running *more* replicas than the trace recorded,
        per-replica CPU and memory decrease, and latency improves
        (sub-linearly).
        """
        row = self._service_trace.iloc[self._step_idx]

        trace_replicas = max(1, int(row["replica_count"]))
        ratio = trace_replicas / max(1, self._simulated_replicas)

        # ── Simulated metrics ─────────────────────────────────────────
        sim_cpu = float(row["cpu_utilization"]) * ratio
        sim_mem = float(row["memory_utilization"]) * ratio
        sim_latency = float(row["latency_ms"]) * (ratio ** 0.5)
        sim_rps = float(row["request_rate"])  # workload is exogenous

        # ── Clip to valid ranges & sanitise ───────────────────────────
        obs = np.array(
            [
                np.clip(sim_cpu, 0.0, 100.0),
                np.clip(sim_mem, 0.0, 100.0),
                float(self._simulated_replicas),
                np.clip(sim_rps, 0.0, self.config.obs_max_rps),
                np.clip(sim_latency, 0.0, self.config.obs_max_latency),
            ],
            dtype=np.float32,
        )

        # Guard against NaN / Inf from degenerate trace data.
        obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)

        return obs

    def _compute_reward(
        self, obs: np.ndarray
    ) -> tuple[float, dict[str, float]]:
        """
        Multi-objective reward function.

        Returns the scalar reward and a dict of named components for
        debugging / logging.
        """
        w = self.config.reward_weights
        cpu = float(obs[0])
        latency = float(obs[4])
        delta_replicas = abs(self._simulated_replicas - self._prev_replicas)

        # ── SLO compliance ────────────────────────────────────────────
        # +1 when latency ≤ target, linearly decreasing when exceeded.
        if latency <= self.config.latency_target_ms:
            slo_reward = 1.0
        else:
            slo_reward = -(
                latency / self.config.latency_target_ms - 1.0
            )
            # Floor at -10 to prevent extreme negative rewards from
            # outlier latency values.
            slo_reward = max(slo_reward, -10.0)

        # ── Resource efficiency ───────────────────────────────────────
        # Penalise deviation from the CPU target.
        efficiency_reward = -abs(cpu - self.config.cpu_target_pct) / 100.0

        # ── Stability ─────────────────────────────────────────────────
        # Penalise every replica change to discourage oscillation.
        stability_penalty = -float(delta_replicas)

        # ── Composite reward ──────────────────────────────────────────
        components = {
            "slo": slo_reward,
            "efficiency": efficiency_reward,
            "stability": stability_penalty,
        }

        reward = (
            w.get("slo", 1.0) * slo_reward
            + w.get("efficiency", 0.3) * efficiency_reward
            + w.get("stability", 0.1) * stability_penalty
        )

        return float(reward), components

    def _build_info(
        self,
        reward_components: dict[str, float] | None,
    ) -> dict[str, Any]:
        """
        Assemble the ``info`` dict returned by ``reset()`` / ``step()``.
        """
        row = self._service_trace.iloc[self._step_idx]
        obs = self._build_observation()

        info: dict[str, Any] = {
            "service_id": self._service_id,
            "timestep": int(row["timestamp"]),
            "step_idx": self._step_idx,
            "simulated_replicas": self._simulated_replicas,
            "trace_replicas": int(row["replica_count"]),
            "trace_cpu": float(row["cpu_utilization"]),
            "trace_memory": float(row["memory_utilization"]),
            "trace_latency": float(row["latency_ms"]),
            "trace_rps": float(row["request_rate"]),
            "sim_cpu": float(obs[0]),
            "sim_latency": float(obs[4]),
            "slo_violated": float(obs[4]) > self.config.latency_target_ms,
        }

        if reward_components is not None:
            info["reward_components"] = reward_components

        return info

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def current_service_id(self) -> str:
        """Service ID being simulated in the current episode."""
        return self._service_id

    @property
    def num_services(self) -> int:
        """Total number of unique services in the loaded dataset."""
        return len(self._all_service_ids)

    @property
    def num_timestamps(self) -> int:
        """Total number of unique timestamps in the loaded dataset."""
        return len(self._all_timestamps)

    @property
    def episode_length(self) -> int:
        """Number of trace rows for the current service."""
        return len(self._service_trace)
