import os
import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.monitor import Monitor

from flexascale.rl.mock_extractor import MockExtractor


class PPOAgentManager:
    """
    Manages the Stable-Baselines3 PPO Agent for FlexaScale.
    Handles initialization with custom feature extractors, callbacks, and logging.
    """

    def __init__(self, env: gym.Env, tensorboard_log_dir: str = "./logs/tb/"):
        self.env = env
        self.tensorboard_log_dir = tensorboard_log_dir
        
        # Policy kwargs inject our custom feature extractor (MockExtractor for now, GNN later)
        policy_kwargs = dict(
            features_extractor_class=MockExtractor,
            features_extractor_kwargs=dict(features_dim=64),
            # Optional: configure the sizes of the actor and critic MLPs that come AFTER the extractor
            net_arch=dict(pi=[64, 64], vf=[64, 64])
        )

        self.model = PPO(
            "MlpPolicy",
            self.env,
            policy_kwargs=policy_kwargs,
            verbose=1,
            tensorboard_log=self.tensorboard_log_dir,
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
        )

    def train(self, total_timesteps: int = 10000, save_dir: str = "./models/"):
        os.makedirs(save_dir, exist_ok=True)
        
        # Callbacks for checkpointing and evaluation
        checkpoint_callback = CheckpointCallback(
            save_freq=5000,
            save_path=os.path.join(save_dir, "checkpoints"),
            name_prefix="ppo_flexascale"
        )
        
        # We use the same env for evaluation here (in practice, use a separate eval env)
        eval_env = self.env
        eval_callback = EvalCallback(
            eval_env,
            best_model_save_path=os.path.join(save_dir, "best_model"),
            log_path=os.path.join(save_dir, "eval_logs"),
            eval_freq=2000,
            deterministic=True,
            render=False
        )

        self.model.learn(
            total_timesteps=total_timesteps,
            callback=[checkpoint_callback, eval_callback],
            progress_bar=True
        )
        
        # Save final model
        final_path = os.path.join(save_dir, "ppo_flexascale_final")
        self.model.save(final_path)
        print(f"Final model saved to {final_path}.zip")

    @classmethod
    def load(cls, path: str, env: gym.Env):
        manager = cls(env)
        manager.model = PPO.load(path, env=env)
        return manager
