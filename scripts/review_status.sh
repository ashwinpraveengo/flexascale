#!/usr/bin/env bash
# FlexaScale read-only status report (Minikube, pods, shop, monitoring, ownership, model, processes).
# Same as `./fsctl status` (Windows: `fsctl status`); implementation: src/flexascale/lab/launcher.py
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/review_common.sh"
launcher status
