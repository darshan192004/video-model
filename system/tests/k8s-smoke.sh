#!/usr/bin/env bash
# In-cluster control-plane roundtrip against the k3s overlay (NodePort 30443).
# Stage [1] is a light liveness probe; stage [2] hands the FULL curve to the
# Phase-3 smoke.sh (login -> submission -> FIFO -> cancel -> failure ->
# two-user isolation), re-pointed at the NodePort via the exported env.
# Usage: bash tests/k8s-smoke.sh   (from system/; requires the k3s overlay up)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYS="$(cd "${HERE}/.." && pwd)"

DOMAIN="${DOMAIN:-127.0.0.1}"
HTTPS_PORT="${HTTPS_PORT:-30443}"
export DOMAIN HTTPS_PORT
export NO_RESOLVE=1

# In-cluster Dex reachability (both legs via the NodePort): the pod dials
# $NODE_IP:30556, the test host 127.0.0.1:30556. If DEX_OIDC_ISSUER is already
# set (regression passes the pod address), keep it.
export DEX_OIDC_ISSUER="${DEX_OIDC_ISSUER:-http://127.0.0.1:30556/dex}"
export DEX_USER_ADMIN="${DEX_USER_ADMIN:-admin@test}" DEX_PASS_ADMIN="${DEX_PASS_ADMIN:-adminpass}"
export DEX_USER_PLAIN="${DEX_USER_PLAIN:-user@test}"  DEX_PASS_PLAIN="${DEX_PASS_PLAIN:-userpass}"

BASE="https://${DOMAIN}:${HTTPS_PORT}"
fail() { echo "K8S SMOKE FAIL: $*" >&2; exit 1; }

echo "[1] nginx serving SPA + healthz in-cluster"
code="$(curl -sk -o /dev/null -w '%{http_code}' "${BASE}/")"
[ "$code" = "200" ] || fail "SPA not served: $code"
code="$(curl -sk -o /dev/null -w '%{http_code}' "${BASE}/api/healthz")"
[ "$code" = "200" ] || fail "healthz: $code"

echo "[2] full control-plane e2e in-cluster (login -> cohort = smoke.sh)"
bash "${SYS}/tests/smoke.sh" || fail "control-plane smoke in-cluster ($?)"

echo "[3] cleanup: leave the stack up for the regression"
echo "K8S SMOKE: ALL PASS"