#!/usr/bin/env bash
# Entrypoint for the ComfyUI container.
# Bridges env vars to ComfyUI CLI flags; runs as non-root inside the image.
# COMFY_DRYRUN=1 prints the computed args and exits (used by unit tests
# on this machine where no GPU exists).
set -euo pipefail

LISTEN="${COMFY_LISTEN:-0.0.0.0}"
PORT="${COMFY_PORT:-8188}"
MODE="${COMFY_MODE:-gpu}"
VRAM="${COMFY_VRAM:-}"
EXTRA="${COMFY_EXTRA_ARGS:-}"

ARGS=(--listen "$LISTEN" --port "$PORT")

if [[ "$MODE" == "cpu" ]]; then
  ARGS+=(--cpu)
fi

case "$VRAM" in
  lowvram) ARGS+=(--lowvram) ;;
  gpu-only) ARGS+=(--gpu-only) ;;
  ""|auto) ;;   # let ComfyUI decide
  *)
    echo "ERROR: unknown COMFY_VRAM '$VRAM' (expected: empty|auto|lowvram|gpu-only)" >&2
    exit 1
    ;;
esac

if [[ -n "$EXTRA" ]]; then
  # Trusted operator-supplied extra flags (e.g. --cpu-vae); word-split on purpose.
  # shellcheck disable=SC2206
  ARGS+=($EXTRA)
fi

echo "[entrypoint] launching: python main.py ${ARGS[*]}" >&2

if [[ "${COMFY_DRYRUN:-0}" == "1" ]]; then
  echo "DRYRUN: ${ARGS[*]}"
  exit 0
fi

exec python main.py "${ARGS[@]}"
