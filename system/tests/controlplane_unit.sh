#!/usr/bin/env bash
# Control-plane unit/API assertions. Boots the FastAPI app in-process against
# sqlite with the OIDC mock issuer: no containers, no database server, no GPU,
# no model weights. Phase 1.5.5/1.5.6 extend this with the job API, mock
# ComfyUI, worker, and gallery assertions.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CP_DIR="$(cd "${HERE}/../controlplane" && pwd)"
PY="${CP_DIR}/.venv/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "FAIL: native venv missing at ${CP_DIR}/.venv" >&2
  echo "FAIL: create it and install ${CP_DIR}/requirements.txt first" >&2
  exit 1
fi

missing="$("${PY}" -c 'import importlib.util as u, sys
mods = ("fastapi", "sqlalchemy", "authlib", "httpx", "itsdangerous", "pydantic_settings", "aiosqlite")
print(",".join(m for m in mods if u.find_spec(m) is None))')"
if [[ -n "${missing}" ]]; then
  echo "FAIL: missing python deps (${missing})" >&2
  echo "FAIL: run ${PY} -m pip install -r ${CP_DIR}/requirements.txt" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

export OIDC_MOCK=1
export OIDC_CLIENT_ID=media-controlplane
export OIDC_CLIENT_SECRET=mock-secret
export OIDC_REDIRECT_URI=https://media.local/api/auth/callback
export SESSION_SECRET=unit-test-session-secret
export ADMIN_GROUPS=media-admins
export DATABASE_URL="sqlite+aiosqlite:///${WORK}/controlplane_unit.db"
export GALLERY_ROOT="${WORK}/galleries"
export UPLOAD_ROOT="${WORK}/uploads"
export AUTO_MIGRATE=1
export SPA_STATIC="${CP_DIR}/../spa/public"
export PYTHONDONTWRITEBYTECODE=1

echo "controlplane_unit: running in-process assertions (sqlite, OIDC_MOCK=1)"
"${PY}" "${CP_DIR}/unit/run.py"
