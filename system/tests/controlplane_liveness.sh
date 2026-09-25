#!/usr/bin/env bash
# Liveness/probe for the control-plane image: start, wait for /api/healthz.
set -euo pipefail

IMAGE="${1:-controlplane-media:0.1.0}"
NAME="controlplane-liveness-test-$RANDOM"
PORT=18199

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -p "${PORT}:8000" \
  "$IMAGE"

# Wait up to 120s for readiness.
for i in $(seq 1 120); do
  if code=$(curl -s -o /tmp/health_body.$$ -w '%{http_code}' "http://127.0.0.1:${PORT}/api/healthz" \
      2>/dev/null) && [ "$code" = "200" ]; then
    echo "liveness: HTTP 200 after ${i}s"
    cat /tmp/health_body.$$
    rm -f /tmp/health_body.$$
    if spa_body=$(curl -fsS "http://127.0.0.1:${PORT}/"); then
      printf '%s\n' "$spa_body"
      if [[ "$spa_body" == *"Media System"* ]]; then
        exit 0
      fi
    fi
    echo "liveness: FAILED - / did not contain Media System"
    exit 1
  fi
  sleep 1
done

echo "liveness: FAILED - /api/healthz not 200 within 120s"
docker logs "$NAME" 2>&1 | tail -40 || true
rm -f /tmp/health_body.$$
exit 1
