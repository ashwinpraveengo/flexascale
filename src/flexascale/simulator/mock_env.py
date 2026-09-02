import gymnasium as gym
import numpy as np
from gymnasium import spaces

from flexascale.data.schema import VECTOR_DIM


class MockClusterEnv(gym.Env):
    """
    Mock Gym environment for FlexaScale PPO integration.
    Emits synthetic observations following the ServiceState vector schema.
    """

    def __init__(self, num_services: int = 4):
        super().__init__()
        self.num_services = num_services
        
        # Observation space: Flat vector of size (num_services * VECTOR_DIM)
        # Assuming typical bounds for the schema:
        # cpu, mem [0, 100], replicas [1, 100], rps [0, inf], latency [0, inf]
        low_obs = np.zeros(self.num_services * VECTOR_DIM, dtype=np.float32)
        high_obs = np.inf * np.ones(self.num_services * VECTOR_DIM, dtype=np.float32)
        self.observation_space = spaces.Box(
            low=low_obs, high=high_obs, dtype=np.float32
        )

        # Action space: Target replica count per service, e.g. [1, 10]
        self.action_space = spaces.Box(
            low=1.0, high=10.0, shape=(self.num_services,), dtype=np.float32
        )

        self.current_step = 0
        self.max_steps = 200

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        obs = self._generate_mock_obs()
        return obs, {}

    def step(self, action):
        self.current_step += 1
        
        # Generate new state (simulating the cluster's response to the action)
        obs = self._generate_mock_obs()
        
        # Dummy reward: e.g., slightly negative if action is high to encourage minimizing replicas
        # while keeping latency/cpu within some bounds.
        # Here we just use a placeholder reward.
        reward = -np.sum(action) * 0.1 + np.random.normal(0, 1)
        
        terminated = False
        truncated = self.current_step >= self.max_steps
        
        return obs, float(reward), terminated, truncated, {}

    def _generate_mock_obs(self) -> np.ndarray:
        # Generates a vector matching the layout in schema.py for each service
        obs = np.zeros(self.num_services * VECTOR_DIM, dtype=np.float32)
        for i in range(self.num_services):
            offset = i * VECTOR_DIM
            obs[offset + 0] = np.random.uniform(10.0, 90.0)  # cpu_utilization
            obs[offset + 1] = np.random.uniform(20.0, 80.0)  # memory_utilization
            obs[offset + 2] = float(np.random.randint(1, 6)) # replica_count
            obs[offset + 3] = np.random.uniform(10.0, 500.0) # request_rate
            obs[offset + 4] = np.random.uniform(5.0, 100.0)  # latency_ms
        return obs
