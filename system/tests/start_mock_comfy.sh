#!/usr/bin/env bash
# Dev helper: (re)start the native-stack MockComfy HTTP server used by the
# P1.5 e2e suite. Collocates scratch output with the native control-plane's
# COMFY_OUTPUT_DIR so the worker can copy generated files into galleries.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CP_DIR="$(cd "${HERE}/../controlplane" && pwd)"
PY="${CP_DIR}/.venv/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "FAIL: native venv missing at ${CP_DIR}/.venv" >&2
  exit 1
fi

: "${MOCK_COMFY_OUTPUT_DIR:=/tmp/comfy-output}"
: "${COMFY_MOCK_PORT:=8999}"
: "${COMFY_MOCK_FAIL_SUBSTR:=}"

mkdir -p "${MOCK_COMFY_OUTPUT_DIR}"

exec env \
  COMFY_OUTPUT_DIR="${MOCK_COMFY_OUTPUT_DIR}" \
  COMFY_MOCK_PORT="${COMFY_MOCK_PORT}" \
  MOCK_COMFY_FAIL_SUBSTR="${COMFY_MOCK_FAIL_SUBSTR}" \
  "${PY}" -m unit.comfy_server