#!/usr/bin/env bash
# One-shot prep to make the k3s dev overlay renderable/appliable on this box:
#   * stage the Phase-1 dev certs inside overlays/k3s/certs (secretGenerator
#     file sources must stay within the kustomization root)
#   * create overlays/k3s/secrets.env from secrets.env.example if missing
# Re-run after cert regeneration. Does NOT apply anything to a cluster.
set -euo pipefail

SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVER="$SYS/deploy/k8s/overlays/k3s"

mkdir -p "$OVER/certs"
if [[ ! -f "$OVER/certs/fullchain.pem" || ! -f "$OVER/certs/privkey.pem" ]]; then
  if [[ ! -f "$SYS/deploy/certs/fullchain.pem" || ! -f "$SYS/deploy/certs/privkey.pem" ]]; then
    echo "deploy/certs missing — generate with scripts/gen-certs.sh first" >&2
    exit 1
  fi
  cp "$SYS/deploy/certs/fullchain.pem" "$SYS/deploy/certs/privkey.pem" "$OVER/certs/"
  echo "[k3s-prep] staged dev certs into overlays/k3s/certs"
fi

if [[ ! -f "$OVER/secrets.env" ]]; then
  sed -e "s/^SESSION_SECRET=$/SESSION_SECRET=$(openssl rand -hex 32)/" \
      -e "s/^POSTGRES_PASSWORD=$/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" \
      "$OVER/secrets.env.example" > "$OVER/secrets.env"
  chmod 600 "$OVER/secrets.env"
  echo "[k3s-prep] created overlays/k3s/secrets.env (edit if needed)"
fi

echo "[k3s-prep] remember to substitute NODE_IP in overlays/k3s/patches/controlplane-env-cm.yaml and config-dex.yaml"