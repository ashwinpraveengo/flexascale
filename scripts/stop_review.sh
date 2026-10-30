#!/usr/bin/env bash
# FlexaScale safe review shutdown.
#
#   ./scripts/stop_review.sh                       stop managed processes, restore HPA ownership, verify
#   ./scripts/stop_review.sh --force-release-lease also clear a controller lease left by a dead controller
#
# Stops ONLY processes recorded by the review scripts (.runtime/pids), never by
# port number. Does not stop Minikube, delete deployments, uninstall charts or
# touch volumes/database data. Idempotent: safe to run any number of times.
# Full teardown is separate: ./scripts/teardown_cluster.sh (asks for confirmation).
# Same as `./fsctl stop` (Windows: `fsctl stop`); implementation: src/flexascale/lab/launcher.py
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/review_common.sh"
for arg in "$@"; do
  case "$arg" in
    --force-release-lease) ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
launcher stop "$@"
