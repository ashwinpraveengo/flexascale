import sys
import argparse
import numpy as np
from pathlib import Path

# Ensure the src/ and root directory are importable
_root = Path(__file__).resolve().parent.parent
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from flexascale.config.env_config import EnvConfig
from flexascale.simulator.flexascale_env import FlexaScaleEnv
from flexascale.rl.ppo_agent import PPOAgentManager
from flexascale.rl.confidence_proxy import predict_with_fallback

# Baseline policy from sanity simulation
from scripts.run_sanity_simulation import heuristic_policy


def run_episode(env, model, seed=42, use_rl=False, confidence_threshold=0.8):
    obs, info = env.reset(seed=seed)
    
    steps = 0
    total_reward = 0.0
    slo_violations = 0
    fallbacks = 0
    
    terminated = False
    truncated = False
    
    while not terminated and not truncated:
        if use_rl and model is not None:
            action, num_fallbacks = predict_with_fallback(
                model=model.model, # Get the underlying PPO model
                obs=obs,
                fallback_policy=heuristic_policy,
                confidence_threshold=confidence_threshold,
                cpu_target=env.config.cpu_target_pct
            )
            fallbacks += num_fallbacks
        else:
            # Baseline policy needs to be applied to each service individually
            actions = []
            obs_flat = obs.flatten()
            vector_dim = 5
            for i in range(env.num_services):
                service_obs = obs_flat[i * vector_dim : (i + 1) * vector_dim]
                a = heuristic_policy(service_obs, env.config.cpu_target_pct)
                actions.append(a)
            action = np.array(actions, dtype=np.int64)
            
        obs, reward, terminated, truncated, info = env.step(action)
        
        steps += 1
        total_reward += reward
        if info.get("slo_violated"):
            slo_violations += 1
            
    return {
        "steps": steps,
        "total_reward": total_reward,
        "slo_violations": slo_violations,
        "fallbacks": fallbacks
    }

def main():
    parser = argparse.ArgumentParser(description="Evaluate RL with Confidence Proxy vs Baseline")
    parser.add_argument("--model-path", type=str, default="models/ppo_flexascale_final.zip", help="Path to trained PPO model")
    parser.add_argument("--episodes", type=int, default=3, help="Number of episodes to run")
    parser.add_argument("--threshold", type=float, default=0.8, help="Confidence threshold for RL agent")
    args = parser.parse_args()

    config = EnvConfig()
    env = FlexaScaleEnv(config=config)
    env.config = config # Attach config for the heuristic policy target
    
    print("Loading RL Model...")
    try:
        model = PPOAgentManager.load(args.model_path, env=env)
        print("Model loaded successfully.")
    except Exception as e:
        print(f"Warning: Could not load model at {args.model_path}. Evaluation will run but RL performance might be random/fail. Error: {e}")
        model = None

    print(f"\nEvaluating over {args.episodes} episodes...")
    
    baseline_stats = []
    rl_stats = []
    
    for ep in range(args.episodes):
        seed = 42 + ep
        # Run Baseline
        b_stat = run_episode(env, None, seed=seed, use_rl=False)
        baseline_stats.append(b_stat)
        
        # Run RL with Confidence Proxy
        r_stat = run_episode(env, model, seed=seed, use_rl=True, confidence_threshold=args.threshold)
        rl_stats.append(r_stat)
        
    # Print Comparison Table
    print("\n" + "="*80)
    print("EVALUATION COMPARISON: BASELINE (HPA Heuristic) vs RL (PPO + Confidence Proxy)")
    print("="*80)
    print(f"{'Metric':<25} | {'Baseline (Heuristic)':<25} | {'RL + Proxy':<25}")
    print("-" * 80)
    
    def avg(key, stats):
        return sum(s[key] for s in stats) / len(stats)
        
    print(f"{'Avg Total Reward':<25} | {avg('total_reward', baseline_stats):<25.3f} | {avg('total_reward', rl_stats):<25.3f}")
    
    b_slo_rate = (sum(s['slo_violations'] for s in baseline_stats) / sum(s['steps'] for s in baseline_stats)) * 100
    r_slo_rate = (sum(s['slo_violations'] for s in rl_stats) / sum(s['steps'] for s in rl_stats)) * 100
    
    print(f"{'SLO Violation Rate':<25} | {b_slo_rate:<24.2f}% | {r_slo_rate:<24.2f}%")
    print(f"{'Avg Fallbacks (per ep)':<25} | {'N/A':<25} | {avg('fallbacks', rl_stats):<25.1f}")
    print("="*80)
    
    env.close()

if __name__ == "__main__":
    main()
