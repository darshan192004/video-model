#!/usr/bin/env bash
# Assert the proxy surface: TLS, SPA + control-plane reachability, WS upgrade.
# Reads DOMAIN/HTTPS_PORT/NO_RESOLVE env; NO_RESOLVE=1 targets a k3s
# NodePort directly (Phase 5 regression re-runs this in-cluster).
# Prereqs: compose stack up (Task 1.3).
set -euo pipefail

DOMAIN="${DOMAIN:-media.local}"
PORT="${HTTPS_PORT:-443}"
BASE="https://${DOMAIN}:${PORT}"
if [[ "${NO_RESOLVE:-0}" == "1" ]]; then RESOLVE=""; else RESOLVE="--resolve ${DOMAIN}:${PORT}:127.0.0.1"; fi

fail() { echo "ASSERT FAIL: $*" >&2; exit 1; }

echo "[1] / (SPA through proxy) => 200"
code=$(curl -sk -o /dev/null -w '%{http_code}' $RESOLVE "$BASE/")
[ "$code" = "200" ] || fail "expected 200 got $code"
curl -sk $RESOLVE "$BASE/" | grep -q "Media System" || fail "SPA HTML not served"

echo "[2] /api/healthz via proxy => 200 JSON"
code=$(curl -sk -o /dev/null -w '%{http_code}' $RESOLVE "$BASE/api/healthz")
[ "$code" = "200" ] || fail "expected 200 got $code"
body=$(curl -sk $RESOLVE "$BASE/api/healthz")
echo "$body" | grep -q '"status"' || fail "healthz missing status: $body"

echo "[3] /ws upgrade => HTTP/1.1 101"
if command -v websocat >/dev/null 2>&1; then
  ws_code=$(websocat -E --url "wss://${DOMAIN}:${PORT}/ws" 2>&1 | head -1) || true
  echo "$ws_code" | grep -qi "101" || fail "websocat ws not 101: $ws_code"
else
  echo "[3-skip] websocat not installed; probe via openssl..."
  handshake=$(printf 'GET /ws HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhpc2lzYXRlc3RrZXk\r\nSec-WebSocket-Version: 13\r\nOrigin: https://%s\r\n\r\n' \
    "$DOMAIN" "$DOMAIN" \
    | timeout 5 openssl s_client -quiet -connect "127.0.0.1:${PORT}" -servername "$DOMAIN" -CAfile /dev/null 2>/dev/null | head -1 || true)
  echo "$handshake" | grep -q "101" || fail "ws not 101: $handshake"
fi

echo "PROXY/TLS: all assertions passed"
