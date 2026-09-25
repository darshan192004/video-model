#!/usr/bin/env bash
# link-models.sh - map a user's weight tree (MODELS_PATH) into ComfyUI's
# models/ layout as a symlink forest under system/models/.
#
# Contract (Phase 3):
#   * Every entry in the manifest (models.manifest.json) is discovered under
#     MODELS_PATH, sha256-verified when the manifest pins a real hash, and
#     linked as $TARGET/<dir>/<filename>.
#   * Placeholder hashes (all zeros / empty) mean "HASH pending": the file is
#     linked without verification.
#   * --write-hashes [path]  records the computed sha256 of every linked file
#     into the manifest (in place, or into [path]) so the real weights get
#     pinned without manual editing.
#   * Refuses to follow candidates whose real path escapes MODELS_PATH
#     (defense-in-depth against symlink-based traversal).
#   * Idempotent: re-running re-links and re-verifies without duplicates.
#
# Exit 0 only when every manifest entry was linked. Required entries missing /
# hash-mismatching fail the run; missing entries are listed.
set -euo pipefail

SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${MODELS_PATH:-/srv/media-weights}"
TARGET="${LINKED_MODELS:-${SYS}/models}"
MANIFEST="${MANIFEST_PATH:-${SYS}/config/models.manifest.json}"

WRITE_HASHES=""
WRITE_TO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --write-hashes)
      WRITE_HASHES=1
      WRITE_TO="${2-}"
      if [[ -n "${WRITE_TO}" && "$2" != --* ]]; then shift; fi
      ;;
    *) echo "usage: link-models.sh [--write-hashes [manifest-path]]" >&2; exit 2 ;;
  esac
  shift
done
[[ -n "${WRITE_TO}" ]] || WRITE_TO="${MANIFEST}"

[[ -f "${MANIFEST}" ]] || { echo "link-models: manifest not found: ${MANIFEST}" >&2; exit 2; }

is_placeholder() { # <sha256>
  local sha="$1"
  [[ -z "$sha" || "$sha" =~ ^0+$ ]]
}

report_error() {
  echo "ERROR: $*" >&2
  FAILED=1
}

linked=0
pending=0
verified=0
missing=0
mismatch=0
FAILED=0
declare -A NEW_HASHES
declare -a missing_list
declare -a mismatch_list

if [[ ! -d "${SRC}" ]]; then
  echo "link-models: MODELS_PATH is not a directory: ${SRC}" >&2
  exit 2
fi

src_root="$(realpath -m "${SRC}")"
mkdir -p "${TARGET}"

while read -r id dir filename pinned; do
  [[ -n "${id}" ]] || continue
  candidate="$(find -L "${src_root}" -maxdepth 4 -type f -name "${filename}" -print -quit 2>/dev/null)"
  if [[ -z "${candidate}" ]]; then
    report_error "missing: ${id} (${dir}/${filename})"
    missing=$((missing + 1))
    missing_list+=("${dir}/${filename}")
    continue
  fi
  resolved="$(realpath "${candidate}")"  # resolves any symlink hops
  if [[ "${resolved}" != "${src_root}"/* ]]; then
    report_error "refused: ${id} resolves outside MODELS_PATH: ${resolved}"
    missing=$((missing + 1))
    missing_list+=("${resolved}")
    continue
  fi
  actual="$(sha256sum "${resolved}" | cut -d' ' -f1)"
  if ! is_placeholder "${pinned}"; then
    if [[ "${actual}" != "${pinned}" ]]; then
      report_error "hash mismatch: ${id} pinned ${pinned} != actual ${actual}"
      mismatch=$((mismatch + 1))
      mismatch_list+=("${dir}/${filename}")
      continue
    fi
    verified=$((verified + 1))
    state="VERIFIED"
  else
    pending=$((pending + 1))
    state="HASH pending"
  fi
  NEW_HASHES["${id}"]="${actual}"
  link="${TARGET}/${dir}/${filename}"
  mkdir -p "$(dirname "${link}")"
  ln -sfn "${resolved}" "${link}"
  linked=$((linked + 1))
  printf '%.6s  %-16s %-20s %s\n' "$state" "${id}" "${dir}" "${state}"
done < <(jq -r '.models[] | [.id, .dir, .filename, (.sha256 // "")] | @tsv' "${MANIFEST}")

if [[ -n "${WRITE_HASHES}" && "${#NEW_HASHES[@]}" -gt 0 ]]; then
  tsv="$(mktemp)"
  trap 'rm -f "${tsv}" "${tsv}.json"' EXIT
  for id in "${!NEW_HASHES[@]}"; do
    printf '%s\t%s\n' "${id}" "${NEW_HASHES[$id]}"
  done > "${tsv}"
  hash_object="$(awk -F'\t' '{printf "  \"%s\": \"%s\",\n", $1, $2}' "${tsv}" | sed '/^$/d')"
  [[ -n "${hash_object}" ]] && hash_object="$(printf '%s' "${hash_object}" | sed '${/,$/s/,$//}')"
  {
    printf '{\n%s\n}\n' "${hash_object}"
  } > "${tsv}.json"
  jq --argjson hashes "$(<"${tsv}.json")" \
    '.models |= map(if ($hashes[.id]?) then (.sha256 = $hashes[.id]) else . end)' \
    "${MANIFEST}" > "${WRITE_TO}"
  echo "write-hashes: ${#NEW_HASHES[@]} sha256 values recorded to ${WRITE_TO}"
fi

echo "link-models: linked=${linked} verified=${verified} pending=${pending} missing=${missing} mismatch=${mismatch}"

if [[ "${missing}" -gt 0 ]]; then
  printf 'missing: %s\n' "${missing_list[@]}" >&2
fi
if [[ "${mismatch}" -gt 0 ]]; then
  printf 'hash mismatch: %s\n' "${mismatch_list[@]}" >&2
fi
exit "${FAILED}"