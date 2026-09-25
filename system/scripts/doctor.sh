#!/usr/bin/env bash
# Preflight checks. Extend per phase (Phase 4 adds nvidia-smi, Phase 5 adds kubectl).
set -uo pipefail

FAIL=0
check() {  # check <name> <command...>
  local name="$1"; shift
  if "$@"; then echo "[ok]   $name"; else echo "[FAIL] $name"; FAIL=1; fi
}

check "docker available"        command -v docker
check "docker compose"          docker compose version >/dev/null
check "port 443 free"           bash -c '! (ss -ltn 2>/dev/null | grep -q ":443 ")'
check "port 8188 free (tcp)"    bash -c '! (ss -ltn 2>/dev/null | grep -q ":8188 ")'
check "port 8000 free (tcp)"    bash -c '! (ss -ltn 2>/dev/null | grep -q ":8000 ")'

MODE="${COMFY_MODE:-gpu}"
case "$MODE" in
  gpu)
    check "nvidia container toolkit" command -v nvidia-smi
    check "nvidia-smi reports GPU"   nvidia-smi >/dev/null
    ;;
  cpu)
    echo "[info] COMFY_MODE=cpu: skipping GPU checks"
    ;;
  *)
    echo "[FAIL] unknown COMFY_MODE=${MODE} (gpu|cpu)"
    FAIL=1
    ;;
esac

check "MODELS_PATH set" bash -c '[[ -n "${MODELS_PATH:-}" ]]'
if [[ -n "${MODELS_PATH:-}" && -n "${MODELS_PATH:-}" ]]; then
  check "MODELS_PATH exists" bash -c "[[ -d '${MODELS_PATH}' ]]"
fi

exit "$FAIL"
