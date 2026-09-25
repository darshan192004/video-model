#!/usr/bin/env bash
# Consolidated in-cluster regression: re-run EVERY prior phase suite against the
# k3s-hosted stack (the project's PRIMARY test vehicle). Each suite reads
# DOMAIN/HTTPS_PORT/NO_RESOLVE (+DEX creds) from env — the only change from the
# compose/native runs is NO_RESOLVE=1 and the NodePort target.
# Usage: bash tests/k3s-regression.sh   (from system/; requires the k3s overlay up)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYS="$(cd "${HERE}/.." && pwd)"

export DOMAIN="${DOMAIN:-127.0.0.1}"
export HTTPS_PORT="${HTTPS_PORT:-30443}"
export NO_RESOLVE=1
export DEX_OIDC_ISSUER="${DEX_OIDC_ISSUER:-http://127.0.0.1:30556/dex}"
export DEX_USER_ADMIN="${DEX_USER_ADMIN:-admin@test}" DEX_PASS_ADMIN="${DEX_PASS_ADMIN:-adminpass}"
export DEX_USER_PLAIN="${DEX_USER_PLAIN:-user@test}"  DEX_PASS_PLAIN="${DEX_PASS_PLAIN:-userpass}"

fail() { echo "K3S-REGRESSION FAIL: $*" >&2; exit 1; }

echo "== k3s-regression against https://${DOMAIN}:${HTTPS_PORT} (NodePort) =="

bash "${SYS}/tests/proxy_tls.sh"                 || fail "proxy_tls (tls/ws)"
bash "${SYS}/tests/controlplane_unit.sh"          || fail "controlplane_unit"
bash "${SYS}/tests/e2e_spa.sh"                    || fail "e2e_spa (12 groups, in-cluster)"
# workflow_schema fetches /object_info INSIDE the cluster via a kubectl-run pod.
COMFY_FETCH='kubectl -n media-system run oi --rm -i --restart=Never --image=curlimages/curl -- curl -s http://comfyui:8188/object_info' \
  bash "${SYS}/tests/workflow_schema.sh"          || fail "workflow_schema"
bash "${SYS}/tests/smoke.sh"                      || fail "smoke"
bash "${SYS}/tests/gpu-smoke.sh" --validate-shape || fail "gpu-smoke --validate-shape"
bash "${SYS}/tests/k8s-smoke.sh"                  || fail "k8s-smoke"

echo "K3S-REGRESSION: ALL PASS"