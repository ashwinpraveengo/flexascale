"""
Kubernetes Operator for FlexaScale.

Autonomous control daemon that coordinates live telemetry aggregation,
GNN + PPO policy inference, confidence estimation, and safety execution
via mutual-exclusion locking and HPA conflict freezing.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch
from stable_baselines3 import PPO

from flexascale.config.safety_config import SafetyConfig
from flexascale.discovery.service_discovery import ServiceDiscovery
from flexascale.rl.gnn_encoder import DEFAULT_SERVICES
from flexascale.safety.coordinator import SafetyCoordinator, SafetyDecision
from flexascale.safety.lock import ControlMode
from flexascale.state.graph_inference import LiveGraphInference
from flexascale.state.live_builder import LiveClusterState, LiveStateBuilder

logger = logging.getLogger(__name__)


def default_hpa_heuristic(service_obs: np.ndarray, cpu_target: float = 70.0) -> int:
    """
    Standard heuristic fallback policy mimicking HorizontalPodAutoscaler.
    service_obs: [cpu, mem, reps, rps, lat]
    Returns action: 0 (Scale Down), 1 (Maintain), 2 (Scale Up)
    """
    cpu = float(service_obs[0])
    tolerance = 0.10 * cpu_target
    if cpu > (cpu_target + tolerance):
        return 2  # Scale Up
    elif cpu < (cpu_target - tolerance):
        return 0  # Scale Down
    return 1  # Maintain


class FlexaScaleOperator:
    """
    Autonomous Kubernetes Operator for FlexaScale.

    Periodically observes cluster telemetry, estimates dependency graph structure,
    computes RL scaling actions and confidence scores, and executes safe updates
    under mutual-exclusion guarantees.
    """

    def __init__(
        self,
        services: Optional[Sequence[str]] = None,
        discovery: Optional[ServiceDiscovery] = None,
        safety_config: Optional[SafetyConfig] = None,
        coordinator: Optional[SafetyCoordinator] = None,
        state_builder: Optional[LiveStateBuilder] = None,
        graph_inference: Optional[LiveGraphInference] = None,
        model_path: Optional[str] = "models/best_model/best_model.zip",
        poll_interval_seconds: float = 5.0,
        mock: bool = False,
    ) -> None:
        self.config = safety_config or SafetyConfig()
        self.mock = mock
        self.poll_interval = poll_interval_seconds
        self.model_path = model_path

        self.discovery = discovery or ServiceDiscovery(
            namespace=self.config.namespace,
            mock=self.mock,
            mock_services=services,
        )

        if services is not None:
            self.services = list(services)
        else:
            discovered = self.discovery.discover()
            self.services = list(discovered) if discovered else list(DEFAULT_SERVICES)

        self.coordinator = coordinator or SafetyCoordinator(
            config=self.config,
        )
        self.state_builder = state_builder or LiveStateBuilder(
            services=self.services,
            discovery=self.discovery,
            namespace=self.config.namespace,
            mock=self.mock,
        )
        self.graph_inference = graph_inference or LiveGraphInference(
            services=self.services,
        )

        self.model: Optional[PPO] = None
        self._running = False
        self._step_count = 0
        self.recent_decisions: List[SafetyDecision] = []
        self._max_history = 100

        self._load_policy()
        self._setup_signals()

    def _setup_signals(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self._handle_shutdown_signal)
            signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        except (ValueError, AttributeError):
            # Signal handling might not be supported in some thread environments
            pass

    def _handle_shutdown_signal(self, signum: int, frame: Any) -> None:
        logger.warning(
            "[OPERATOR] Received shutdown signal (%d). Restoring all services to dynamic HPA...",
            signum,
        )
        self.shutdown()
        sys.exit(0)

    def _load_policy(self) -> None:
        """Attempt to load trained PPO policy model."""
        if self.model_path and os.path.exists(self.model_path):
            try:
                self.model = PPO.load(self.model_path)
                logger.info(
                    "[OPERATOR] Successfully loaded trained PPO model from '%s'",
                    self.model_path,
                )
                return
            except Exception as exc:
                logger.warning(
                    "[OPERATOR] Failed to load PPO model from '%s': %s. Falling back to heuristic policy.",
                    self.model_path,
                    exc,
                )
        else:
            logger.info(
                "[OPERATOR] No trained model found at '%s'. Using heuristic policy.",
                self.model_path,
            )
        self.model = None

    def predict_action_and_confidence(
        self,
        obs: np.ndarray,
    ) -> Tuple[List[int], List[float]]:
        """
        Evaluate actions and confidence scores per service.

        Returns:
            (actions, confidences): List of action ints and list of float confidences.
        """
        num_services = len(self.services)

        if self.model is not None:
            try:
                # 1. If service count matches PPO multi-discrete space, use standard PPO forward
                obs_tensor, _ = self.model.policy.obs_to_tensor(obs)
                expected_act_dim = (
                    len(self.model.action_space.nvec)
                    if hasattr(self.model.action_space, "nvec")
                    else (1 if hasattr(self.model.action_space, "n") else None)
                )

                if expected_act_dim == num_services:
                    rl_action, _ = self.model.predict(obs, deterministic=True)
                    actions_list = (
                        np.asarray(rl_action).flatten().tolist()
                        if hasattr(rl_action, "__iter__")
                        else [int(rl_action)] * num_services
                    )

                    with torch.no_grad():
                        distribution = self.model.policy.get_distribution(obs_tensor)

                    confidences: List[float] = []
                    action_tensor = (
                        torch.tensor(actions_list, device=obs_tensor.device).unsqueeze(0)
                    )

                    if hasattr(distribution, "distribution") and isinstance(
                        distribution.distribution, list
                    ):
                        for i in range(num_services):
                            cat_dist = distribution.distribution[i]
                            act_i = action_tensor[:, i]
                            prob = torch.exp(cat_dist.log_prob(act_i)).item()
                            confidences.append(float(np.clip(prob, 0.0, 1.0)))
                    else:
                        confidences = [0.85] * num_services

                    return actions_list, confidences

                # 2. For variable/arbitrary N services: evaluate GNN node-level policy head
                features_extractor = getattr(self.model.policy, "features_extractor", None)
                gnn_encoder = getattr(features_extractor, "encoder", None)
                if gnn_encoder is not None and hasattr(gnn_encoder, "predict_node_actions"):
                    with torch.no_grad():
                        x = obs_tensor.view(-1, 5)
                        edge_index = self.graph_inference.get_edge_index().to(obs_tensor.device)
                        node_acts, node_confs = gnn_encoder.predict_node_actions(x, edge_index)
                        return node_acts.tolist(), node_confs.tolist()

            except Exception as exc:
                logger.debug(
                    "[OPERATOR] Policy inference fallback: %s. Using heuristic.", exc
                )

        # Heuristic fallback calculation (size-invariant for any N services)
        obs_flat = obs.flatten()
        actions = []
        confidences = []
        for i, sid in enumerate(self.services):
            service_obs = obs_flat[i * 5 : (i + 1) * 5]
            if len(service_obs) < 5:
                service_obs = np.array([25.0, 30.0, 1.0, 10.0, 20.0], dtype=np.float32)
            action = default_hpa_heuristic(
                service_obs, cpu_target=self.config.target_cpu_utilization
            )
            actions.append(action)
            cpu = float(service_obs[0])
            conf = 0.85 if 20.0 <= cpu <= 80.0 else 0.55
            confidences.append(conf)

        return actions, confidences

    def step(self) -> List[SafetyDecision]:
        """
        Executes one autonomous control loop step:
        1. Gather live cluster telemetry and vector schema.
        2. Dynamically update services and infer dependency graph traffic.
        3. Predict actions and confidence scores across all workloads.
        4. Execute safety coordinator decisions (mutual exclusion + HPA freeze).
        """
        self._step_count += 1

        # 1. Telemetry and vector assembly
        cluster_state: LiveClusterState = self.state_builder.build()
        obs = cluster_state.observation_vector

        # Refresh service list if discovery identified new workloads
        if set(self.state_builder.services) != set(self.services):
            self.services = list(self.state_builder.services)

        # 2. Dependency graph traffic update
        telemetry_rps = {
            sid: state.request_rate
            for sid, state in cluster_state.service_states.items()
        }
        traffic_flows = None
        if not self.mock and hasattr(self.state_builder.metrics_client, "query_inter_service_traffic"):
            traffic_flows = self.state_builder.metrics_client.query_inter_service_traffic(
                namespace=self.config.namespace
            )

        self.graph_inference.update_from_cluster(
            services=self.services,
            traffic_flows=traffic_flows,
            telemetry_rps=telemetry_rps,
        )

        # 3. Model inference & confidence estimation
        actions, confidences = self.predict_action_and_confidence(obs)

        # 4. Safety execution
        decisions: List[SafetyDecision] = []
        for i, sid in enumerate(self.services):
            act = actions[i] if i < len(actions) else 1
            conf = confidences[i] if i < len(confidences) else 0.0

            # Current replicas
            state = cluster_state.service_states.get(sid)
            current_reps = state.replica_count if state else None

            decision = self.coordinator.evaluate_and_execute(
                service_id=sid,
                action=act,
                confidence=conf,
                current_replicas=current_reps,
            )
            decisions.append(decision)

        # Store recent decisions for API/Dashboard audit
        self.recent_decisions = (decisions + self.recent_decisions)[
            : self._max_history
        ]
        return decisions

    def run_loop(
        self,
        max_steps: Optional[int] = None,
        poll_interval: Optional[float] = None,
    ) -> None:
        """
        Runs the autonomous operator loop indefinitely or up to max_steps.
        """
        self._running = True
        interval = poll_interval or self.poll_interval
        logger.info(
            "[OPERATOR] FlexaScale Operator started. Polling every %.1fs (max_steps=%s, mock=%s)",
            interval,
            max_steps,
            self.mock,
        )

        try:
            steps = 0
            while self._running:
                decisions = self.step()
                steps += 1
                logger.debug(
                    "[OPERATOR] Step %d completed with %d decisions",
                    steps,
                    len(decisions),
                )

                if max_steps and steps >= max_steps:
                    logger.info(
                        "[OPERATOR] Reached max_steps (%d). Terminating loop.",
                        max_steps,
                    )
                    break

                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("[OPERATOR] Interrupted by user. Shutting down cleanly...")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """
        Cleanly stops operator and guarantees all workloads return to dynamic HPA.
        """
        self._running = False
        logger.info(
            "[OPERATOR] Shutting down operator. Restoring all services to native HPA..."
        )
        try:
            self.coordinator.fallback_all_to_hpa(reason="operator_shutdown", services=self.services)
            logger.info("[OPERATOR] All services safely restored to native HPA.")
        except Exception as exc:
            logger.error(
                "[OPERATOR] Error during shutdown HPA restoration: %s", exc
            )

    def get_status(self) -> Dict[str, Any]:
        """Summarizes operator health, active modes, and cluster telemetry."""
        cluster_state = self.state_builder.build()
        modes = {
            sid: self.coordinator.lock_manager.get_control_mode(sid).value
            for sid in self.services
        }
        return {
            "running": self._running,
            "step_count": self._step_count,
            "poll_interval": self.poll_interval,
            "model_loaded": self.model is not None,
            "modes": modes,
            "services": {
                sid: state.to_dict()
                for sid, state in cluster_state.service_states.items()
            },
            "timestamp": time.time(),
        }

    def get_recent_decisions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return serialized list of recent safety decisions."""
        return [
            {
                "service_id": d.service_id,
                "chosen_mode": d.chosen_mode.value,
                "confidence": round(d.confidence, 4) if d.confidence is not None else None,
                "target_replicas": d.target_replicas,
                "action_applied": d.action_applied,
                "lock_acquired": d.lock_acquired,
                "hpa_frozen": d.hpa_frozen,
                "hpa_active": d.hpa_active,
                "reason": d.reason,
            }
            for d in self.recent_decisions[:limit]
        ]
