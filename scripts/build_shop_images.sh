#!/usr/bin/env bash
# Build every shop image (16 services + frontend) with the tag the Helm chart
# expects (charts/shopping-app/values.yaml) and load it into Minikube.
#
#   ./scripts/build_shop_images.sh [service ...]     (default: all; e.g. ./scripts/build_shop_images.sh search-service)
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE="${FLEXASCALE_MINIKUBE_PROFILE:-flexascale}"
mapfile -t IMAGES < <(.venv/bin/python - <<'PY'
import yaml
v = yaml.safe_load(open("charts/shopping-app/values.yaml"))
for s in v["services"].values():
    print(s["name"], s["image"]["repository"], s["image"]["tag"])
PY
)
for line in "${IMAGES[@]}"; do
  read -r NAME REPO TAG <<< "$line"
  if [ "$#" -gt 0 ] && [[ ! " $* " =~ " $NAME " ]]; then continue; fi
  CTX="apps/services/$NAME"; [ "$NAME" = shopping-frontend ] && CTX="apps/shopping-frontend"
  echo "== $NAME -> $REPO:$TAG"
  docker build -q -t "$REPO:$TAG" "$CTX" >/dev/null
  minikube -p "$PROFILE" image load "$REPO:$TAG"
done
echo "done; deploy with: helm upgrade --install shopping-app charts/shopping-app -n flexascale-apps && kubectl apply -f deploy/kubernetes/hpa.yaml"
