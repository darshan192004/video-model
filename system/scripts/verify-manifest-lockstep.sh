#!/usr/bin/env bash
# verify-manifest-lockstep.sh - checks workflows/*.json against the model manifest.
#
# Every .safetensors filename the canonical graphs reference MUST exist in
# models.manifest.json (a missing weight breaks ComfyUI at runtime). Manifest
# entries that no workflow references are tolerated but reported as orphans so
# the user can decide whether to prune them.
#
# Exit 0 when every workflow-referenced filename is manifest-listed; non-zero
# otherwise. Util: NO_MANIFEST points elsewhere, WORKFLOWS_DIR overrides the
# default graph directory.
set -euo pipefail

SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${MANIFEST_PATH:-${SYS}/config/models.manifest.json}"
WORKFLOWS_DIR="${WORKFLOWS_DIR:-${SYS}/workflows}"
SHAS="$(command -v jq >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1)"

[[ -f "${MANIFEST}" ]] || { echo "verify-manifest-lockstep: manifest not found: ${MANIFEST}" >&2; exit 2; }
[[ -d "${WORKFLOWS_DIR}" ]] || { echo "verify-manifest-lockstep: workflows dir not found: ${WORKFLOWS_DIR}" >&2; exit 2; }

jq -e '.models | type == "array"' "${MANIFEST}" >/dev/null 2>&1 \
  || { echo "verify-manifest-lockstep: manifest has no models list" >&2; exit 2; }

# 1) Collect every .safetensors literal referenced by the canonical graphs.
temp="$(mktemp)"
trap 'rm -f "${temp}"' EXIT
for wf in "${WORKFLOWS_DIR}"/*.json; do
  [[ -e "${wf}" ]] || continue
  jq -r '.. | strings | select(test("\\.safetensors$"))' "${wf}" >>"${temp}" 2>/dev/null || true
done
sort -u "${temp}" -o "${temp}"

# Normalize to the manifest's filename list.
jq -r '.models[].filename' "${MANIFEST}" | sort -u > "${temp}.manifest"

missing="$(comm -23 "${temp}" "${temp}.manifest")"
orphans="$(comm -13 "${temp}" "${temp}.manifest")"

if [[ -n "${missing}" ]]; then
  echo "verify-manifest-lockstep: FAIL - workflows reference weights missing from the manifest:"
  printf '  %s\n' ${missing}
  exit 1
fi

if [[ -n "${orphans}" ]]; then
  echo "verify-manifest-lockstep: warning - manifest entries unused by any workflow:"
  printf '  %s\n' ${orphans}
fi

echo "verify-manifest-lockstep: OK ($(wc -l < <(grep . "${temp}")) workflow-referenced weights all manifest-listed)"
rm -f "${temp}.manifest"