#!/usr/bin/env bash
# FlexaScale - Cluster Teardown / Stop Script (Linux / macOS)

set -euo pipefail

PROFILE=${1:-"flexascale"}
DELETE_FLAG=${2:-""}

echo "=========================================================="
echo " FlexaScale - Cluster Teardown / Stop"
echo "=========================================================="

if [ "$DELETE_FLAG" == "--delete" ] || [ "$DELETE_FLAG" == "-d" ]; then
    echo "WARNING: this deletes the Minikube profile '$PROFILE', including every deployment,"
    echo "the PostgreSQL volume (all shop data) and the monitoring stack. It cannot be undone."
    if [ "${FLEXASCALE_CONFIRM_DELETE:-}" != "$PROFILE" ]; then
        read -r -p "Type the profile name '$PROFILE' to confirm deletion: " answer
        if [ "$answer" != "$PROFILE" ]; then
            echo "Aborted: nothing was deleted."
            exit 1
        fi
    fi
    echo "Deleting Minikube profile '$PROFILE' completely..."
    minikube delete -p "$PROFILE"
    echo "Cluster profile '$PROFILE' deleted."
else
    echo "Stopping Minikube cluster '$PROFILE' (use --delete to delete)..."
    minikube stop -p "$PROFILE"
    echo "Cluster '$PROFILE' stopped."
fi

echo "=========================================================="
