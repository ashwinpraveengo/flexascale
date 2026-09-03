import torch
import numpy as np
from stable_baselines3 import PPO

def predict_with_fallback(
    model: PPO,
    obs: np.ndarray,
    fallback_policy: callable,
    confidence_threshold: float = 0.8,
    cpu_target: float = 70.0,
    num_services: int = 4
) -> tuple[np.ndarray, int]:
    """
    Predicts the MultiDiscrete action array using the PPO model. Evaluates the 
    confidence of the action *per service*. If the probability for a specific service's
    action is below the threshold, it falls back to the baseline heuristic for that service.
    
    Args:
        model: Trained SB3 PPO model.
        obs: Current concatenated observation vector shape (num_services * 5,).
        fallback_policy: A callable that takes (service_obs, cpu_target) and returns an action.
        confidence_threshold: The minimum probability required to trust the RL agent.
        cpu_target: CPU target to pass to the fallback policy if needed.
        num_services: Number of microservices being simulated.
        
    Returns:
        (action_array, num_fallbacks): Final chosen MultiDiscrete action array and the number of fallbacks triggered.
    """
    # 1. Get deterministic action from the model
    rl_action, _ = model.predict(obs, deterministic=True)
    
    # 2. Convert to tensors to evaluate probability
    obs_tensor, _ = model.policy.obs_to_tensor(obs)
    action_tensor = torch.tensor(rl_action).unsqueeze(0).to(obs_tensor.device) # Add batch dim
    
    # 3. Get the action distribution
    with torch.no_grad():
        distribution = model.policy.get_distribution(obs_tensor)
        
    final_actions = []
    num_fallbacks = 0
    obs_flat = obs.flatten()
    vector_dim = 5 # VECTOR_DIM from schema
    
    # Evaluate confidence per service (MultiCategoricalDistribution has a list of distributions)
    if hasattr(distribution, "distribution") and isinstance(distribution.distribution, list):
        for i in range(num_services):
            cat_dist = distribution.distribution[i]
            action_i = action_tensor[:, i]
            prob = torch.exp(cat_dist.log_prob(action_i)).item()
            
            if prob >= confidence_threshold:
                final_actions.append(rl_action[i])
            else:
                # Fallback to heuristic for this specific service
                service_obs = obs_flat[i * vector_dim : (i + 1) * vector_dim]
                hpa_action = fallback_policy(service_obs, cpu_target)
                final_actions.append(hpa_action)
                num_fallbacks += 1
    else:
        # Fallback if distribution type is unexpected (should not happen with MultiDiscrete)
        for i in range(num_services):
            service_obs = obs_flat[i * vector_dim : (i + 1) * vector_dim]
            final_actions.append(fallback_policy(service_obs, cpu_target))
            num_fallbacks += 1
            
    return np.array(final_actions, dtype=np.int64), num_fallbacks
