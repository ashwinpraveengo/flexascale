"""
FlexaScale Gymnasium Environment for Kubernetes autoscaling simulation.

Replays Alibaba cloud trace data for multiple microservices simultaneously,
simulating the effect of horizontal pod autoscaling decisions on CPU,
memory utilization, response latency, and SLO compliance.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

from flexascale.config.env_config import EnvConfig
from flexascale.data.preprocessing import split_service_state_dataset
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
    Gymnasium environment that replays the Alibaba trace for the cluster
    and simulates the impact of scaling decisions.
    """

    metadata: dict[str, Any] = {"render_modes": ["human"]}

    def __init__(self, config: EnvConfig | None = None) -> None:
        super().__init__()
        self.config = config or EnvConfig()
        self._df = self._load_dataset(self.config.dataset_path)

        # Apply dataset partition / split if requested
        if self.config.split in ("train", "val", "test"):
            dataset_stem = Path(self.config.dataset_path).stem
            if not dataset_stem.endswith(f"_{self.config.split}"):
                train_df, val_df, test_df = split_service_state_dataset(
                    self._df,
                    train_ratio=self.config.train_ratio,
                    val_ratio=self.config.val_ratio,
                    test_ratio=self.config.test_ratio,
                    method=self.config.split_method,
                )
                split_map = {
                    "train": train_df,
                    "val": val_df,
                    "test": test_df,
                }
                self._df = split_map[self.config.split]
        elif self.config.split != "all":
            raise ValueError(
                f"Unknown split '{self.config.split}'. Choose from 'all', 'train', 'val', 'test'."
            )

        self._all_timestamps: np.ndarray = np.sort(self._df["timestamp"].unique())

        # Determine services to simulate:
        if self.config.service_id is not None:
            # Single-service mode
            if self.config.service_id in self._df["service_id"].values:
                self._all_service_ids = [self.config.service_id]
            else:
                available = self._df["service_id"].unique().tolist()
                logger.warning(
                    "Configured service_id '%s' not found. Falling back to '%s'",
                    self.config.service_id,
                    available[0],
                )
                self._all_service_ids = [available[0]]
            self._single_service_mode = True
        else:
            # Multi-service cluster mode: start from the most frequent services
            service_counts = self._df["service_id"].value_counts()
            self._all_service_ids = service_counts.head(self.config.num_services).index.tolist()
            self._single_service_mode = False

        if self.config.service_sampling not in ("top_frequency", "random"):
            raise ValueError(f"Unknown service_sampling '{self.config.service_sampling}'.")
        if self.config.demand_model not in ("trace", "normalized"):
            raise ValueError(f"Unknown demand_model '{self.config.demand_model}'.")

        # Candidate pool for random sampling: services observed at every timestamp
        # with non-zero CPU demand, so sampled episodes have no missing rows.
        self._sampling_pool: list[str] = []
        if self.config.service_sampling == "random" and not self._single_service_mode:
            n_ts = self._df["timestamp"].nunique()
            per_service = self._df.groupby("service_id").agg(
                n=("timestamp", "nunique"), cpu=("cpu_utilization", "max")
            )
            self._sampling_pool = sorted(
                per_service[(per_service["n"] == n_ts) & (per_service["cpu"] > 0)].index
            )
            if len(self._sampling_pool) < self.config.num_services:
                raise ValueError("Not enough complete services in split for random sampling.")

        self._demand_scale: dict[str, float] = {}
        self._select_services(self._all_service_ids)

        num_services = len(self._all_service_ids)
        logger.info(
            "Loaded dataset: %d rows, %d timestamps, %d services (single_mode=%s)",
            len(self._df_filtered),
            len(self._all_timestamps),
            num_services,
            self._single_service_mode,
        )

        obs_dim = num_services * VECTOR_DIM
        low = np.array(
            [0.0, 0.0, float(self.config.min_replicas), 0.0, 0.0] * num_services,
            dtype=np.float32,
        )
        high = np.array(
            [
                100.0,
                100.0,
                float(self.config.max_replicas),
                self.config.obs_max_rps,
                self.config.obs_max_latency,
            ] * num_services,
            dtype=np.float32,
        )
        self.observation_space = spaces.Box(
            low=low, high=high, shape=(obs_dim,), dtype=np.float32
        )

        if self._single_service_mode:
            self.action_space = spaces.Discrete(NUM_ACTIONS)
        else:
            self.action_space = spaces.MultiDiscrete([NUM_ACTIONS] * num_services)

        self._step_idx: int = 0
        self._simulated_replicas: dict[str, int] = {}
        self._prev_replicas: dict[str, int] = {}
        self._is_initialised: bool = False

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)

        self._step_idx = 0
        self._simulated_replicas = {}
        self._prev_replicas = {}

        if self._sampling_pool:
            idx = self.np_random.choice(
                len(self._sampling_pool), size=self.config.num_services, replace=False
            )
            self._select_services([self._sampling_pool[i] for i in sorted(idx)])

        if self.config.demand_model == "normalized":
            self._compute_demand_scales()

        first_step = self._sequence[0]
        for sid in self._all_service_ids:
            if sid not in first_step:
                initial_replicas = self.config.min_replicas
            elif self.config.demand_model == "normalized":
                row = first_step[sid]
                demand = self._scaled_demand(sid, row)
                initial_replicas = int(np.ceil(demand / self.config.cpu_target_pct))
            else:
                initial_replicas = int(first_step[sid]["replica_count"])
            if self.config.randomize_initial_replicas:
                initial_replicas = int(
                    self.np_random.integers(self.config.min_replicas, self.config.max_replicas + 1)
                )

            self._simulated_replicas[sid] = int(
                np.clip(
                    initial_replicas,
                    self.config.min_replicas,
                    self.config.max_replicas,
                )
            )
            self._prev_replicas[sid] = self._simulated_replicas[sid]

        self._is_initialised = True
        obs = self._build_observation()
        info = self._build_info(reward_components=None)
        return obs, info

    def step(
        self, action: Any
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if not self._is_initialised:
            self.reset()

        num_services = len(self._all_service_ids)

        # Normalize action input (support scalar int, list, or ndarray)
        if isinstance(action, (int, np.integer)):
            actions_list = [int(action)] * num_services
        elif isinstance(action, (list, tuple, np.ndarray)):
            act_flat = np.asarray(action).flatten().tolist()
            if len(act_flat) == 1 and num_services > 1:
                actions_list = [int(act_flat[0])] * num_services
            else:
                actions_list = [int(a) for a in act_flat]
        else:
            actions_list = [ACTION_MAINTAIN] * num_services

        # Apply scaling action per service
        for i, sid in enumerate(self._all_service_ids):
            self._prev_replicas[sid] = self._simulated_replicas[sid]
            act_val = actions_list[i] if i < len(actions_list) else ACTION_MAINTAIN
            delta = act_val - 1  # 0 -> -1, 1 -> 0, 2 -> +1
            new_replicas = self._simulated_replicas[sid] + delta
            self._simulated_replicas[sid] = int(
                np.clip(
                    new_replicas,
                    self.config.min_replicas,
                    self.config.max_replicas,
                )
            )

        self._step_idx += 1
        terminated = self._step_idx >= len(self._sequence)

        if terminated:
            self._step_idx = len(self._sequence) - 1
            obs = self._build_observation()
            info = self._build_info(reward_components=None)
            return obs, 0.0, True, False, info

        obs = self._build_observation()
        reward, components = self._compute_reward(obs)
        info = self._build_info(reward_components=components)

        return obs, reward, False, False, info

    def render(self) -> None:
        if not self._is_initialised:
            print("Not initialised. Call reset() first.")
            return

        print(f"Step {self._step_idx}/{len(self._sequence)}:")
        for sid in self._all_service_ids:
            reps = self._simulated_replicas.get(sid, 1)
            print(f"  Service {sid[:12]}: replicas={reps}")

    def close(self) -> None:
        self._is_initialised = False

    @staticmethod
    def _load_dataset(path: str) -> pd.DataFrame:
        csv_path = Path(path)
        if not csv_path.is_file():
            raise FileNotFoundError(
                f"Processed dataset not found at '{csv_path.resolve()}'."
            )
        df = pd.read_csv(csv_path)
        required = {"timestamp", "service_id"} | set(VECTOR_FIELDS)
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")
        return df

    def _select_services(self, service_ids: Sequence[str]) -> None:
        """Restrict the replayed sequence to ``service_ids`` (in that order)."""
        self._all_service_ids = list(service_ids)
        self._df_filtered = self._df[self._df["service_id"].isin(self._all_service_ids)]
        self._sequence = []
        for _, group in self._df_filtered.groupby("timestamp"):
            self._sequence.append({row["service_id"]: row for _, row in group.iterrows()})
        if not self._sequence:
            raise ValueError("No matching sequence data found for simulated services.")

    def _compute_demand_scales(self) -> None:
        """Pick a per-service scale so peak demand needs a random replica count."""
        self._demand_scale = {}
        for sid in self._all_service_ids:
            peak = max(
                float(step[sid]["cpu_utilization"]) * max(1, int(step[sid]["replica_count"]))
                for step in self._sequence
                if sid in step
            )
            peak_replicas = self.np_random.integers(
                self.config.peak_replicas_low, self.config.peak_replicas_high + 1
            )
            target = float(peak_replicas) * self.config.cpu_target_pct
            self._demand_scale[sid] = target / peak if peak > 0 else 0.0

    def _scaled_demand(self, sid: str, row: Any) -> float:
        """CPU demand in replica-percent units after per-episode rescaling."""
        trace_demand = float(row["cpu_utilization"]) * max(1, int(row["replica_count"]))
        return trace_demand * self._demand_scale.get(sid, 0.0)

    def _normalized_service_obs(self, sid: str, row: Any) -> tuple[float, float, float, float]:
        """(cpu, mem, rps, latency) under the 'normalized' demand model."""
        sim_reps = max(1, self._simulated_replicas.get(sid, 1))
        rho = self._scaled_demand(sid, row) / (sim_reps * 100.0)
        rho_trace = min(float(row["cpu_utilization"]) / 100.0, 0.95)
        congestion = (1.0 - rho_trace) / (1.0 - min(rho, 0.98))
        if rho > 1.0:
            congestion *= rho  # backlog grows when demand exceeds capacity
        sim_cpu = min(rho, 1.0) * 100.0
        sim_mem = float(row["memory_utilization"])
        sim_rps = (
            float(row["request_rate"])
            * max(1, int(row["replica_count"]))
            * self._demand_scale.get(sid, 0.0)
        )
        sim_latency = float(row["latency_ms"]) * congestion
        return sim_cpu, sim_mem, sim_rps, sim_latency

    def _build_observation(self) -> np.ndarray:
        current_step = self._sequence[self._step_idx]
        obs_parts = []

        for sid in self._all_service_ids:
            if sid in current_step and self.config.demand_model == "normalized":
                sim_cpu, sim_mem, sim_rps, sim_latency = self._normalized_service_obs(
                    sid, current_step[sid]
                )
            elif sid in current_step:
                row = current_step[sid]
                trace_replicas = max(1, int(row["replica_count"]))
                sim_reps = max(1, self._simulated_replicas.get(sid, 1))
                ratio = trace_replicas / sim_reps

                sim_cpu = float(row["cpu_utilization"]) * ratio
                sim_mem = float(row["memory_utilization"]) * ratio
                sim_latency = float(row["latency_ms"]) * (ratio ** 0.5)
                sim_rps = float(row["request_rate"])
            else:
                sim_cpu, sim_mem, sim_latency, sim_rps = 0.0, 0.0, 0.0, 0.0

            sim_reps = float(self._simulated_replicas.get(sid, 1))
            obs_part = np.array(
                [
                    np.clip(sim_cpu, 0.0, 100.0),
                    np.clip(sim_mem, 0.0, 100.0),
                    sim_reps,
                    np.clip(sim_rps, 0.0, self.config.obs_max_rps),
                    np.clip(sim_latency, 0.0, self.config.obs_max_latency),
                ],
                dtype=np.float32,
            )
            obs_part = np.nan_to_num(obs_part, nan=0.0, posinf=0.0, neginf=0.0)
            obs_parts.append(obs_part)

        return np.concatenate(obs_parts)

    def _compute_reward(
        self, obs: np.ndarray
    ) -> tuple[float, dict[str, float]]:
        w = self.config.reward_weights
        total_reward = 0.0
        agg_components = {"slo": 0.0, "efficiency": 0.0, "stability": 0.0, "cost": 0.0}

        for i, sid in enumerate(self._all_service_ids):
            base_idx = i * VECTOR_DIM
            cpu = float(obs[base_idx + 0])
            latency = float(obs[base_idx + 4])
            delta_replicas = abs(
                self._simulated_replicas[sid] - self._prev_replicas[sid]
            )

            if latency <= self.config.latency_target_ms:
                slo_reward = 1.0
            else:
                slo_reward = -(latency / self.config.latency_target_ms - 1.0)
                slo_reward = max(slo_reward, -10.0)

            efficiency_reward = -abs(cpu - self.config.cpu_target_pct) / 100.0
            stability_penalty = -float(delta_replicas)
            cost_penalty = -float(self._simulated_replicas[sid]) / float(self.config.max_replicas)

            reward = (
                w.get("slo", 1.0) * slo_reward
                + w.get("efficiency", 0.3) * efficiency_reward
                + w.get("stability", 0.1) * stability_penalty
                + w.get("cost", 0.0) * cost_penalty
            )

            total_reward += reward
            agg_components["slo"] += slo_reward
            agg_components["efficiency"] += efficiency_reward
            agg_components["stability"] += stability_penalty
            agg_components["cost"] += cost_penalty

        num_services = len(self._all_service_ids)
        total_reward /= num_services
        for k in agg_components:
            agg_components[k] /= num_services

        return float(total_reward), agg_components

    def _build_info(
        self,
        reward_components: dict[str, float] | None,
    ) -> dict[str, Any]:
        primary_sid = self._all_service_ids[0] if self._all_service_ids else "unknown"
        first_reps = self._simulated_replicas.get(primary_sid, 1)

        info: dict[str, Any] = {
            "step_idx": self._step_idx,
            "timestep": self._step_idx,
            "service_id": primary_sid,
            "service_ids": list(self._all_service_ids),
            "simulated_replicas": first_reps if self._single_service_mode else self._simulated_replicas.copy(),
            "replicas_dict": self._simulated_replicas.copy(),
            "slo_violated": False,
        }

        obs = self._build_observation()
        for i, sid in enumerate(self._all_service_ids):
            base_idx = i * VECTOR_DIM
            latency = float(obs[base_idx + 4])
            if latency > self.config.latency_target_ms:
                info["slo_violated"] = True
                break

        if reward_components is not None:
            info["reward_components"] = reward_components

        return info

    @property
    def num_services(self) -> int:
        return len(self._all_service_ids)

    @property
    def num_timestamps(self) -> int:
        return len(self._all_timestamps)

    @property
    def episode_length(self) -> int:
        return len(self._sequence)
