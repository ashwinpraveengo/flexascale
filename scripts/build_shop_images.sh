#!/usr/bin/env bash
# Build every shop image (16 services + frontend) with the tag the Helm chart
# expects (charts/shopping-app/values.yaml) and make it available to Minikube.
#
#   ./scripts/build_shop_images.sh [service ...]          build inside Minikube's Docker daemon (default)
#   ./scripts/build_shop_images.sh --load [service ...]   build with the host Docker, then `minikube image load`
#
# Default: all images; e.g. ./scripts/build_shop_images.sh search-service.
# Works on Linux and in Git Bash on Windows (the venv's python is .venv/bin or .venv/Scripts).
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE="${FLEXASCALE_MINIKUBE_PROFILE:-flexascale}"
LOAD=0
if [ "${1:-}" = "--load" ]; then LOAD=1; shift; fi
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python.exe
[ -x "$PY" ] || { echo "virtualenv missing (.venv)"; exit 1; }
if [ "$LOAD" = 0 ]; then
  # Images built in the node's own daemon need no copy; imagePullPolicy IfNotPresent then uses them.
  eval "$(minikube -p "$PROFILE" docker-env --shell bash)"
fi
mapfile -t IMAGES < <("$PY" - <<'PY'
import yaml
v = yaml.safe_load(open("charts/shopping-app/values.yaml"))
for s in v["services"].values():
    print(s["name"], s["image"]["repository"], s["image"]["tag"])
PY
)
[ "${#IMAGES[@]}" -gt 0 ] || { echo "could not read the image list from charts/shopping-app/values.yaml (is pyyaml installed?)"; exit 1; }
for line in "${IMAGES[@]}"; do
  read -r NAME REPO TAG <<< "${line//$'\r'/}"
  if [ "$#" -gt 0 ] && [[ ! " $* " =~ " $NAME " ]]; then continue; fi
  CTX="apps/services/$NAME"; [ "$NAME" = shopping-frontend ] && CTX="apps/shopping-frontend"
  echo "== $NAME -> $REPO:$TAG"
  docker build -q -t "$REPO:$TAG" "$CTX" >/dev/null
  [ "$LOAD" = 1 ] && minikube -p "$PROFILE" image load "$REPO:$TAG"
done
echo "done; deploy with: helm upgrade --install shopping-app charts/shopping-app -n flexascale-apps && kubectl apply -f deploy/kubernetes/hpa.yaml"
