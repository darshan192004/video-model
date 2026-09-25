#!/usr/bin/env bash
# Liveness/probe for the ComfyUI image: start in CPU mode, wait for /system_stats.
set -euo pipefail

IMAGE="${1:-comfyui-media:0.1.0}"
NAME="liveness-test-$RANDOM"
PORT=18188

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -p "${PORT}:8188" \
  -e COMFY_MODE=cpu \
  "$IMAGE"

# Wait up to 120s for readiness.
for i in $(seq 1 120); do
  if code=$(curl -s -o /tmp/stats_body.$$ -w '%{http_code}' "http://127.0.0.1:${PORT}/system_stats" \
      2>/dev/null) && [ "$code" = "200" ]; then
    echo "liveness: HTTP 200 after ${i}s"
    cat /tmp/stats_body.$$
    rm -f /tmp/stats_body.$$
    exit 0
  fi
  sleep 1
done

echo "liveness: FAILED - /system_stats not 200 within 120s"
docker logs "$NAME" 2>&1 | tail -40 || true
rm -f /tmp/stats_body.$$
exit 1
