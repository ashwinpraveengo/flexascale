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
    Gymnasium environment that replays the Alibaba trace for the entire cluster
    (all services simultaneously) and simulates the impact of scaling decisions.
    """

    metadata: dict[str, Any] = {"render_modes": ["human"]}

    def __init__(self, config: EnvConfig | None = None) -> None:
        super().__init__()
        self.config = config or EnvConfig()
        self._df = self._load_dataset(self.config.dataset_path)

        self._all_timestamps: np.ndarray = np.sort(self._df["timestamp"].unique())
        
        # The Alibaba dataset uses SHA hashes for service IDs.
        # We simulate a 4-node cluster by picking the 4 most frequent services
        # to ensure we have the most overlapping trace data.
        service_counts = self._df["service_id"].value_counts()
        self._all_service_ids = service_counts.head(4).index.tolist()
        
        # Precompute sequential data
        self._sequence = []
        for ts, group in self._df.groupby("timestamp"):
            ts_dict = {row["service_id"]: row for _, row in group.iterrows()}
            self._sequence.append(ts_dict)

        num_services = len(self._all_service_ids)
        logger.info(
            "Loaded dataset: %d rows, %d timestamps, %d services",
            len(self._df),
            len(self._all_timestamps),
            num_services,
        )

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
            low=low, high=high, shape=(num_services * VECTOR_DIM,), dtype=np.float32
        )

        self.action_space = spaces.MultiDiscrete([NUM_ACTIONS] * num_services)

        self._step_idx: int = 0
        self._simulated_replicas: dict[str, int] = {}
        self._prev_replicas: dict[str, int] = {}

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
        
        first_step = self._sequence[0]
        for sid in self._all_service_ids:
            if sid in first_step:
                initial_replicas = int(first_step[sid]["replica_count"])
            else:
                initial_replicas = self.config.min_replicas
                
            self._simulated_replicas[sid] = int(np.clip(
                initial_replicas,
                self.config.min_replicas,
                self.config.max_replicas,
            ))
            self._prev_replicas[sid] = self._simulated_replicas[sid]

        obs = self._build_observation()
        info = self._build_info(reward_components=None)
        return obs, info

    def step(
        self, action: np.ndarray
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        
        for i, sid in enumerate(self._all_service_ids):
            self._prev_replicas[sid] = self._simulated_replicas[sid]
            delta = action[i] - 1
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
        pass

    def close(self) -> None:
        pass

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

    def _build_observation(self) -> np.ndarray:
        current_step = self._sequence[self._step_idx]
        obs_parts = []
        
        for sid in self._all_service_ids:
            if sid in current_step:
                row = current_step[sid]
                trace_replicas = max(1, int(row["replica_count"]))
                ratio = trace_replicas / max(1, self._simulated_replicas[sid])

                sim_cpu = float(row["cpu_utilization"]) * ratio
                sim_mem = float(row["memory_utilization"]) * ratio
                sim_latency = float(row["latency_ms"]) * (ratio ** 0.5)
                sim_rps = float(row["request_rate"])
            else:
                sim_cpu, sim_mem, sim_latency, sim_rps = 0.0, 0.0, 0.0, 0.0
                
            obs_part = np.array(
                [
                    np.clip(sim_cpu, 0.0, 100.0),
                    np.clip(sim_mem, 0.0, 100.0),
                    float(self._simulated_replicas[sid]),
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
        
        agg_components = {"slo": 0.0, "efficiency": 0.0, "stability": 0.0}
        
        for i, sid in enumerate(self._all_service_ids):
            base_idx = i * VECTOR_DIM
            cpu = float(obs[base_idx + 0])
            latency = float(obs[base_idx + 4])
            delta_replicas = abs(self._simulated_replicas[sid] - self._prev_replicas[sid])

            if latency <= self.config.latency_target_ms:
                slo_reward = 1.0
            else:
                slo_reward = -(latency / self.config.latency_target_ms - 1.0)
                slo_reward = max(slo_reward, -10.0)

            efficiency_reward = -abs(cpu - self.config.cpu_target_pct) / 100.0
            stability_penalty = -float(delta_replicas)

            reward = (
                w.get("slo", 1.0) * slo_reward
                + w.get("efficiency", 0.3) * efficiency_reward
                + w.get("stability", 0.1) * stability_penalty
            )
            
            total_reward += reward
            agg_components["slo"] += slo_reward
            agg_components["efficiency"] += efficiency_reward
            agg_components["stability"] += stability_penalty
            
        num_services = len(self._all_service_ids)
        total_reward /= num_services
        for k in agg_components:
            agg_components[k] /= num_services
            
        return float(total_reward), agg_components

    def _build_info(
        self,
        reward_components: dict[str, float] | None,
    ) -> dict[str, Any]:
        info: dict[str, Any] = {
            "step_idx": self._step_idx,
            "simulated_replicas": self._simulated_replicas.copy(),
            "slo_violated": False
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
