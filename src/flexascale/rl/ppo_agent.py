import os
import logging
from typing import Any, Type
import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

from flexascale.rl.gnn_encoder import GNNExtractor
from flexascale.rl.mock_extractor import MockExtractor

logger = logging.getLogger(__name__)

# Check for tensorboard availability
try:
    from torch.utils.tensorboard import SummaryWriter  # noqa: F401
    _HAS_TENSORBOARD = True
except ImportError:
    _HAS_TENSORBOARD = False

# Check for progress bar dependencies (tqdm, rich)
try:
    import tqdm  # noqa: F401
    import rich  # noqa: F401
    _HAS_PROGRESS_BAR = True
except ImportError:
    _HAS_PROGRESS_BAR = False


class PPOAgentManager:
    """
    Manages the Stable-Baselines3 PPO Agent for FlexaScale.
    Handles initialization with GNN or Mock feature extractors, callbacks, and logging.
    """

    def __init__(
        self,
        env: gym.Env,
        tensorboard_log_dir: str | None = "./logs/tb/",
        features_extractor_class: Type[BaseFeaturesExtractor] = GNNExtractor,
        features_extractor_kwargs: dict[str, Any] | None = None,
        learning_rate: float = 3e-4,
        n_steps: int = 2048,
        batch_size: int = 64,
        n_epochs: int = 10,
        gamma: float = 0.99,
        net_arch: dict[str, list[int]] | None = None,
    ):
        self.env = env
        if tensorboard_log_dir and not _HAS_TENSORBOARD:
            logger.warning(
                "Tensorboard is not installed; disabling tensorboard logging."
            )
            self.tensorboard_log_dir = None
        else:
            self.tensorboard_log_dir = tensorboard_log_dir

        if features_extractor_kwargs is None:
            features_extractor_kwargs = dict(features_dim=64)

        if net_arch is None:
            net_arch = dict(pi=[64, 64], vf=[64, 64])

        policy_kwargs = dict(
            features_extractor_class=features_extractor_class,
            features_extractor_kwargs=features_extractor_kwargs,
            net_arch=net_arch,
        )

        self.model = PPO(
            "MlpPolicy",
            self.env,
            policy_kwargs=policy_kwargs,
            verbose=1,
            tensorboard_log=self.tensorboard_log_dir,
            learning_rate=learning_rate,
            n_steps=n_steps,
            batch_size=batch_size,
            n_epochs=n_epochs,
            gamma=gamma,
        )

    def train(
        self,
        total_timesteps: int = 10000,
        save_dir: str = "./models/",
        progress_bar: bool = False,
    ):
        os.makedirs(save_dir, exist_ok=True)

        # Callbacks for checkpointing and evaluation
        eval_freq = max(1000, total_timesteps // 5)
        checkpoint_callback = CheckpointCallback(
            save_freq=eval_freq,
            save_path=os.path.join(save_dir, "checkpoints"),
            name_prefix="ppo_flexascale",
        )

        eval_env = self.env
        eval_callback = EvalCallback(
            eval_env,
            best_model_save_path=os.path.join(save_dir, "best_model"),
            log_path=os.path.join(save_dir, "eval_logs"),
            eval_freq=eval_freq,
            deterministic=True,
            render=False,
        )

        use_progress_bar = progress_bar and _HAS_PROGRESS_BAR

        self.model.learn(
            total_timesteps=total_timesteps,
            callback=[checkpoint_callback, eval_callback],
            progress_bar=use_progress_bar,
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
