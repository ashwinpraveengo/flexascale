#!/usr/bin/env python3
"""
FlexaScale End-to-End Closed-Loop Controller Runner.

Wires the complete closed-loop architecture:
Telemetry Scraping -> Live State Builder -> EMA Graph Inference ->
PPO Policy Inference -> Confidence Proxy -> Safety Coordinator ->
Mutual-Exclusion Lock -> Dynamic Scaling / HPA Freeze -> Performance Diagnostics.

Usage:
    python scripts/run_closed_loop.py --demo
    python scripts/run_closed_loop.py --live --interval 5.0
"""

import argparse
import logging
import sys
import time

import numpy as np

from flexascale.config.safety_config import SafetyConfig
from flexascale.operator.operator import FlexaScaleOperator
from flexascale.rl.gnn_encoder import DEFAULT_SERVICES
from flexascale.safety.coordinator import SafetyCoordinator
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ScalingLockManager
from flexascale.state.graph_inference import LiveGraphInference
from flexascale.state.live_builder import LiveStateBuilder


def parse_args():
    parser = argparse.ArgumentParser(description="FlexaScale End-to-End Closed-Loop Controller")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Connect to live Minikube Kubernetes cluster and Prometheus telemetry",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Execute 5 automated closed-loop steps with dynamic simulated load variations",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=10,
        help="Number of closed-loop iterations to execute (default: 10)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Closed-loop control step interval in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="RL activation confidence threshold (default: 0.70)",
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="flexascale-apps",
        help="Target Kubernetes namespace (default: flexascale-apps)",
    )
    parser.add_argument(
        "--custom-app",
        action="store_true",
        help="Run against an arbitrary custom microservice application (auth-api, cart-service, catalog-db)",
    )
    parser.add_argument(
        "--label-selector",
        type=str,
        default="",
        help="Optional Kubernetes label selector for workload discovery",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default="models/best_model/best_model.zip",
        help="Path to trained PPO policy zip file",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("flexascale.closed_loop")

    is_live = args.live
    dry_run = not is_live

    custom_services = ["auth-api", "cart-service", "catalog-db"] if args.custom_app else None

    config = SafetyConfig(
        confidence_threshold=args.threshold,
        namespace=args.namespace,
        label_selector=args.label_selector,
        dry_run=dry_run,
    )

    lock_mgr = ScalingLockManager(config=config, sync_k8s=is_live)
    hpa_mgr = HPAManager(config=config, mock=dry_run)
    coordinator = SafetyCoordinator(
        config=config,
        lock_manager=lock_mgr,
        hpa_manager=hpa_mgr,
    )

    state_builder = LiveStateBuilder(services=custom_services, namespace=args.namespace, mock=dry_run)
    graph_infer = LiveGraphInference(services=custom_services)

    operator = FlexaScaleOperator(
        services=custom_services,
        safety_config=config,
        coordinator=coordinator,
        state_builder=state_builder,
        graph_inference=graph_infer,
        model_path=args.model_path,
        poll_interval_seconds=args.interval,
        mock=dry_run,
    )

    app_desc = "CUSTOM APP (auth-api, cart-service, catalog-db)" if args.custom_app else f"DISCOVERED FLEET ({', '.join(operator.services)})"

    print("=" * 88)
    print("FLEXASCALE END-TO-END CLOSED-LOOP EXECUTION")
    print(f"Execution Target:      {'Live Kubernetes Cluster' if is_live else 'Simulated Mock Environment'}")
    print(f"Target Workloads:      {app_desc}")
    print(f"Target Namespace:      {args.namespace}")
    print(f"Policy Model:          {args.model_path}")
    print(f"Confidence Threshold:  {config.confidence_threshold:.2f}")
    print(f"Hysteresis Floor:      {config.deactivation_threshold:.2f}")
    print(f"Step Interval:         {args.interval:.1f}s")
    print("=" * 88)

    num_steps = 5 if args.demo else args.steps

    # Simulated traffic scenario perturbations for demo
    scenarios = [
        {"desc": "Normal Baseline Traffic", "cpu": 25.0, "rps": 15.0, "lat": 18.0},
        {"desc": "Incoming Lunch Rush Spike", "cpu": 82.0, "rps": 75.0, "lat": 92.0},
        {"desc": "Peak Sustained Burst", "cpu": 91.0, "rps": 110.0, "lat": 135.0},
        {"desc": "Traffic Stabilizing (RL Scale Effect)", "cpu": 55.0, "rps": 85.0, "lat": 42.0},
        {"desc": "Night Valley Taper Off", "cpu": 18.0, "rps": 10.0, "lat": 14.0},
    ]

    try:
        for s_idx in range(num_steps):
            scenario = scenarios[s_idx % len(scenarios)] if not is_live else None
            if scenario and not is_live:
                # Inject mock load across active services
                for sid in operator.services:
                    state_builder.set_mock_metric(sid, "cpu_utilization", scenario["cpu"] * np.random.uniform(0.9, 1.1))
                    state_builder.set_mock_metric(sid, "request_rate", scenario["rps"] * np.random.uniform(0.9, 1.1))
                    state_builder.set_mock_metric(sid, "latency_ms", scenario["lat"] * np.random.uniform(0.9, 1.1))

            print(f"\n[Closed-Loop Step {s_idx + 1}/{num_steps}] {scenario['desc'] if scenario else 'Cluster Telemetry Query'}")
            decisions = operator.step()

            # Inspect cluster state
            cluster_state = state_builder.build()
            avg_cpu = np.mean([st.cpu_utilization for st in cluster_state.service_states.values()])
            avg_lat = np.mean([st.latency_ms for st in cluster_state.service_states.values()])
            tot_rps = np.sum([st.request_rate for st in cluster_state.service_states.values()])
            tot_reps = np.sum([st.replica_count for st in cluster_state.service_states.values()])

            print(f"Cluster Metrics -> Avg CPU: {avg_cpu:.1f}% | Avg Latency: {avg_lat:.1f}ms | Total RPS: {tot_rps:.1f} | Total Replicas: {tot_reps}")
            print(f"{'Service':<12} | {'Mode':<6} | {'Confidence':<10} | {'Action':<15} | {'Target Replicas':<15} | {'Reason'}")
            print("-" * 88)
            for d in decisions:
                conf_s = f"{d.confidence:.2f}" if d.confidence is not None else "N/A"
                act_s = f"{d.action_applied:+d} (Apply RL)" if d.action_applied is not None else "Maintain (HPA)"
                print(f"{d.service_id:<12} | {d.chosen_mode.value:<6} | {conf_s:<10} | {act_s:<15} | {d.target_replicas:<15} | {d.reason}")

            if s_idx < num_steps - 1:
                time.sleep(args.interval)

    finally:
        operator.shutdown()
        print("\n" + "=" * 88)
        print("[SUCCESS] Closed-loop execution completed. All services safely restored to native HPA.")
        print("=" * 88)

    return 0


if __name__ == "__main__":
    sys.exit(main())
