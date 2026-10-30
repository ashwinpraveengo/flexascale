#!/usr/bin/env bash
# FlexaScale fast review startup.
#
#   ./scripts/start_review.sh            preflight + port-forwards + ingress access + control center
#   ./scripts/start_review.sh --demo     same, plus the demo sequence
#   ./scripts/start_review.sh --check    preflight only: start nothing, change nothing
#
# Works with the already installed cluster. It never rebuilds images, reinstalls
# charts, retrains models, downloads data or runs the test suite. It starts the
# existing Minikube profile only if it is stopped, and never creates a new one.
# Safe to run repeatedly: healthy processes it started earlier are reused.
# Same as `./fsctl start` (Windows: `fsctl start`); implementation: src/flexascale/lab/launcher.py
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/review_common.sh"
for arg in "$@"; do
  case "$arg" in
    --demo|--check) ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
launcher start "$@"
