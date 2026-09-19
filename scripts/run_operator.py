#!/usr/bin/env python3
"""
FlexaScale Operator CLI Runner.

Launches the autonomous scaling loop over the Kubernetes cluster or in mock mode.
Usage:
    python scripts/run_operator.py --demo
    python scripts/run_operator.py --live --interval 5.0
"""

import argparse
import logging
import sys

from flexascale.config.safety_config import SafetyConfig
from flexascale.operator.operator import FlexaScaleOperator
from flexascale.safety.coordinator import SafetyCoordinator
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lock import ScalingLockManager
from flexascale.state.graph_inference import LiveGraphInference
from flexascale.state.live_builder import LiveStateBuilder


def parse_args():
    parser = argparse.ArgumentParser(description="FlexaScale Autonomous Operator")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Connect to live Kubernetes cluster and Prometheus instead of mock",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run 3 demonstration steps and display formatted decision diagnostics",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Polling loop interval in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="RL activation confidence threshold (default: 0.70)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum loop iterations before exiting (default: infinite)",
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="flexascale-apps",
        help="Kubernetes namespace containing microservices to manage (default: flexascale-apps)",
    )
    parser.add_argument(
        "--label-selector",
        type=str,
        default="",
        help="Optional Kubernetes label selector for workload discovery (e.g. 'app.kubernetes.io/part-of=ecommerce')",
    )
    parser.add_argument(
        "--custom-app",
        action="store_true",
        help="Run demo against an arbitrary custom microservice application (auth-api, cart-service, catalog-db)",
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
    logger = logging.getLogger("flexascale.operator.cli")

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

    state_builder = LiveStateBuilder(
        services=custom_services,
        namespace=args.namespace,
        mock=dry_run,
    )
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

    print("=" * 80)
    print("FLEXASCALE AUTONOMOUS OPERATOR")
    print(f"Mode: {'LIVE KUBERNETES' if is_live else 'MOCK / DEMO'}")
    print(f"Target Workloads:     {app_desc}")
    print(f"Target Namespace:     {args.namespace}")
    print(f"Confidence Threshold: {config.confidence_threshold:.2f}")
    print(f"Hysteresis Floor:     {config.deactivation_threshold:.2f}")
    print(f"Poll Interval:        {args.interval:.1f}s")
    print("=" * 80)

    if args.demo:
        surge_service = operator.services[0]
        print(f"\n[*] Running 3 autonomous operator control steps on '{app_desc}' in demo mode...\n")
        # Step 1: Normal steady traffic
        print("--- Step 1: Normal Traffic ---")
        decisions1 = operator.step()
        _print_decisions(decisions1)

        # Step 2: Simulate traffic spike on first service
        print(f"\n--- Step 2: Traffic & CPU Surge on '{surge_service}' ---")
        state_builder.set_mock_metric(surge_service, "cpu_utilization", 88.0)
        state_builder.set_mock_metric(surge_service, "request_rate", 60.0)
        state_builder.set_mock_metric(surge_service, "latency_ms", 95.0)
        decisions2 = operator.step()
        _print_decisions(decisions2)

        # Step 3: Traffic subsides
        print(f"\n--- Step 3: Normal Load Restoration ---")
        state_builder.set_mock_metric(surge_service, "cpu_utilization", 25.0)
        decisions3 = operator.step()
        _print_decisions(decisions3)

        operator.shutdown()
        print("\n[SUCCESS] Operator demo completed successfully!")
        return 0

    operator.run_loop(max_steps=args.max_steps)
    return 0


def _print_decisions(decisions):
    print(f"{'Service':<12} | {'Mode':<6} | {'Conf':<6} | {'Target':<6} | {'Action':<7} | {'Lock':<5} | {'HPA Frozen':<10} | {'Reason'}")
    print("-" * 80)
    for d in decisions:
        conf_str = f"{d.confidence:.2f}" if d.confidence is not None else "N/A"
        act_str = f"{d.action_applied:+d}" if d.action_applied is not None else "None"
        print(
            f"{d.service_id:<12} | {d.chosen_mode.value:<6} | {conf_str:<6} | "
            f"{d.target_replicas:<6} | {act_str:<7} | {str(d.lock_acquired):<5} | "
            f"{str(d.hpa_frozen):<10} | {d.reason}"
        )


if __name__ == "__main__":
    sys.exit(main())
