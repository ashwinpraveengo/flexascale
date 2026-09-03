import torch
import numpy as np
import gymnasium as gym
from stable_baselines3 import PPO

# Dummy env with MultiDiscrete
env = gym.make("CartPole-v1") # Just need something
env.action_space = gym.spaces.MultiDiscrete([3, 3, 3, 3])
env.observation_space = gym.spaces.Box(low=0, high=1, shape=(20,))

model = PPO("MlpPolicy", env)
obs = np.random.rand(20).astype(np.float32)

obs_tensor, _ = model.policy.obs_to_tensor(obs)
with torch.no_grad():
    dist = model.policy.get_distribution(obs_tensor)
    action = dist.get_actions()
    print("Action:", action)
    print("Joint log_prob:", dist.log_prob(action))
    
    print("Has attr distribution?", hasattr(dist, "distribution"))
    if hasattr(dist, "distribution"):
        print("Type:", type(dist.distribution))
        if isinstance(dist.distribution, list):
            for i, d in enumerate(dist.distribution):
                print(f"Dim {i} prob:", torch.exp(d.log_prob(action[:, i])))
