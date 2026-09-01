import gymnasium as gym
import torch
import torch.nn as nn
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor


class MockExtractor(BaseFeaturesExtractor):
    """
    Mock Feature Extractor for PPO integration.
    Acts as a placeholder for the PyTorch Geometric GNN dependency encoder.
    Takes a flat observation vector and processes it via a simple MLP.
    """

    def __init__(self, observation_space: gym.Space, features_dim: int = 64):
        # We assume observation_space is a Box of shape (num_services * VECTOR_DIM, )
        super().__init__(observation_space, features_dim)
        
        # Get the input dimension from the observation space
        input_dim = observation_space.shape[0]
        
        # Simple MLP to mock a more complex encoder
        self.net = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.ReLU(),
            nn.Linear(128, features_dim),
            nn.ReLU()
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.
        
        Args:
            observations: Tensor of shape (batch_size, input_dim)
            
        Returns:
            Tensor of shape (batch_size, features_dim)
        """
        return self.net(observations)
