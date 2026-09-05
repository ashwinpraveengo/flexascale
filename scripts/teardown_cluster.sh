#!/usr/bin/env bash
# FlexaScale - Cluster Teardown / Stop Script (Linux / macOS)

set -euo pipefail

PROFILE=${1:-"flexascale"}
DELETE_FLAG=${2:-""}

echo "=========================================================="
echo " FlexaScale - Cluster Teardown / Stop"
echo "=========================================================="

if [ "$DELETE_FLAG" == "--delete" ] || [ "$DELETE_FLAG" == "-d" ]; then
    echo "Deleting Minikube profile '$PROFILE' completely..."
    minikube delete -p "$PROFILE"
    echo "Cluster profile '$PROFILE' deleted."
else
    echo "Stopping Minikube cluster '$PROFILE' (use --delete to delete)..."
    minikube stop -p "$PROFILE"
    echo "Cluster '$PROFILE' stopped."
fi

echo "=========================================================="
