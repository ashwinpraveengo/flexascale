#!/usr/bin/env python3
"""
FlexaScale REST API & Dashboard Server.

Starts the FastAPI server with live metrics, decision logs, and React dashboard.
Usage:
    python scripts/run_api.py --port 8080
    python scripts/run_api.py --live --port 8080
"""

import argparse
import sys
import uvicorn

from flexascale.api.app import create_app
from flexascale.api.state_store import APIStateStore, set_state_store


def parse_args():
    parser = argparse.ArgumentParser(description="FlexaScale API & Dashboard Server")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host address to bind (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to listen on (default: 8080)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Connect to live cluster and Prometheus instead of mock",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    store = APIStateStore(mock=not args.live)
    set_state_store(store)
    app = create_app(mock=not args.live, state_store=store)

    print("=" * 70)
    print("FLEXASCALE REST API & DASHBOARD SERVER")
    print(f"Server URL:     http://localhost:{args.port}")
    print(f"API Docs:       http://localhost:{args.port}/docs")
    print(f"Cluster Mode:   {'LIVE (Kubernetes + Prometheus)' if args.live else 'MOCK / SIMULATED'}")
    print("=" * 70)

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
