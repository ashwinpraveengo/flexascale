#!/usr/bin/env python3
"""
FlexaScale Live Autoscaling Lab server (presentation dashboard + experiment API).

Usage:
    python scripts/run_lab.py                       # http://127.0.0.1:8090
    python scripts/run_lab.py --port 8090 --config config/lab.yaml

Normally started by scripts/start_review.sh, which also port-forwards Prometheus
and Grafana. Binds to 127.0.0.1 by default; exposing it on other interfaces lets
anyone who can reach the port start load tests and switch autoscaling controllers.
"""

import argparse
import logging
import sys

import uvicorn

from flexascale.lab.experiments import Lab
from flexascale.lab.server import create_lab_app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--config", default="config/lab.yaml")
    ap.add_argument("--runtime-dir", default=".runtime")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    lab = Lab(config_path=args.config, runtime_dir=args.runtime_dir)
    print(f"FlexaScale Live Autoscaling Lab: http://{args.host}:{args.port}", flush=True)
    uvicorn.run(create_lab_app(lab), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
