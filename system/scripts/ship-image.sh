#!/usr/bin/env bash
# Ship the four stack images + the system/ subtree to the 3090 box.
#
#   DRY_RUN=1 SSH_ALIAS=<alias> bash scripts/ship-image.sh
#   DRY_RUN=0 SSH_ALIAS=<alias> bash scripts/ship-image.sh
#
# DRY_RUN=1 (validated on this machine): only `docker save`s each image into a
# local stage dir and reports. DRY_RUN=0 (the box, [DEFERRED-REAL]): streams
# each archive over SSH with `docker load -i /dev/stdin`, then rsyncs the
# system/ subtree (without heavyweight dev artifacts) to ~/media-system.
set -euo pipefail

ALIAS="${SSH_ALIAS:-media3090}"
IMAGES=("comfyui-media:0.1.0" "controlplane-media:0.1.0" "postgres:16-alpine" "nginx:1.27-alpine")
STAGE="$(mktemp -d)"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for img in "${IMAGES[@]}"; do
  docker image inspect "$img" >/dev/null || { echo "image $img missing" >&2; exit 1; }
done

echo "[1] save each image"
for img in "${IMAGES[@]}"; do
  tag="${img//[:\/]/_}"
  docker save -o "$STAGE/$tag.tar" "$img"
  ls -lh "$STAGE/$tag.tar"
done

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY_RUN: tar archives created; skipping ssh/rsync (stage: $STAGE)"
  exit 0
fi

echo "[2] ssh load (4 archives)"
for img in "${IMAGES[@]}"; do
  tag="${img//[:\/]/_}"
  ssh "$ALIAS" "docker load -i /dev/stdin" < "$STAGE/$tag.tar"
done

echo "[3] rsync system subtree -> ~/media-system on the box"
# Heavyweight dev artifacts (venvs, SPA build tree) are already baked into the
# images; shipping them wastes SSH time and box disk. Certs/secrets never ship.
rsync -az --delete \
  --exclude '.env' --exclude '.gitignore' \
  --exclude '.venv/' --exclude 'node_modules' --exclude 'spa/.nuxt' \
  --exclude 'spa/dist' --exclude 'spa/public' \
  --exclude 'deploy/secrets' --exclude 'deploy/certs' \
  --exclude 'models' --exclude 'tests/artifacts' \
  "$ROOT/" "$ALIAS:media-system/"
rm -rf "$STAGE"
echo "ship-image: done"