#!/usr/bin/env bash
# Self-healing kubectl port-forward: NAMESPACE TARGET LOCAL:REMOTE
# (kept for existing callers; the supervisor is src/flexascale/lab/portforward.py)
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/review_common.sh"
cd "$ROOT" && exec "$PY" -m flexascale.lab.portforward "$@"
