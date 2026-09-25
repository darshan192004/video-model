#!/usr/bin/env bash
# smoke.sh - control-plane smoke (CPU): OIDC login, FIFO queue, cancel,
# validation-failure, job-failure, two-user gallery isolation.
#
# Everything goes through the control-plane API (https://${DOMAIN}:${HTTPS_PORT})
# via lib_login.sh - no test ever talks to ComfyUI directly, and ComfyUI is
# reachable only through the private network. The `broken` template ships via
# the TEMPLATE_FIXTURES_DIR registry (see controlplane_unit.sh).
#
# Native run (final consolidated pass, mock comfy + real Dex):
#   DOMAIN=media.local HTTPS_PORT=8443 NO_RESOLVE=0 \
#   DEX_USER_ADMIN=admin@test DEX_PASS_ADMIN=adminpass \
#   DEX_USER_PLAIN=user@test DEX_PASS_PLAIN=userpass bash tests/smoke.sh
# In-k3s (Phase 5): same script with NO_RESOLVE=1 against the NodePort.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYS="$(cd "${HERE}/.." && pwd)"

OIDC_DOMAIN="${DOMAIN:-${OIDC_DOMAIN:-media.local}}"
export OIDC_DOMAIN
export HTTPS_PORT="${HTTPS_PORT:-443}"
export NO_RESOLVE="${NO_RESOLVE:-0}"
export DEX_USER="${DEX_USER:-${DEX_USER_ADMIN:-admin@test}}"
export DEX_PASS="${DEX_PASS:-${DEX_PASS_ADMIN:-adminpass}}"

ADMIN_EMAIL="${DEX_USER_ADMIN:-admin@test}"
USER_EMAIL="${DEX_USER_PLAIN:-user@test}"
USER_PASS="${DEX_PASS_PLAIN:-userpass}"

source "${HERE}/lib_login.sh"

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

echo "[1] login admin@test and user@test -> session cookies"
admin_jar="$(login_as "${ADMIN_EMAIL}")"
user_jar="$(login_as "${USER_EMAIL}" '' "${USER_PASS}")"

echo "[2] submit smoke template as admin -> 201 job_id"
api_request "${admin_jar}" POST /api/jobs '{"template_id":"smoke","params":{}}'
[[ "${API_STATUS}" == "201" ]] || fail "create job1: ${API_STATUS}: ${API_BODY}"
job1="$(jq -r '.job_id // empty' <<<"${API_BODY}")"
[[ -n "${job1}" ]] || fail "no job_id in ${API_BODY}"

echo "[3] second job while first running -> FIFO claim (queued behind job1)"
api_request "${admin_jar}" POST /api/jobs '{"template_id":"smoke","params":{}}'
[[ "${API_STATUS}" == "201" ]] || fail "create job2: ${API_STATUS}: ${API_BODY}"
job2="$(jq -r '.job_id // empty' <<<"${API_BODY}")"
api_request "${admin_jar}" GET "/api/jobs/${job2}"
st2="$(jq -r .status <<<"${API_BODY}")"
case "${st2}" in
  queued|running|success) ;;
  *) fail "job2 unexpected status ${st2}: ${API_BODY}" ;;
esac
echo "  job2 initial status: ${st2}"

echo "[4] wait for job1 success; cancel job2 if it did not already finish"
st1=""
for _ in $(seq 1 60); do
  api_request "${admin_jar}" GET "/api/jobs/${job1}"
  st1="$(jq -r .status <<<"${API_BODY}")"
  [[ "${st1}" == "success" ]] && break
  [[ "${st1}" == "failed" ]] && fail "job1 failed: ${API_BODY}"
  sleep 1
done
[[ "${st1}" == "success" ]] || fail "job1 not success within 60s (${st1})"

api_request "${admin_jar}" GET "/api/jobs/${job2}"
st2="$(jq -r .status <<<"${API_BODY}")"
if [[ "${st2}" == "success" ]]; then
  echo "  job2 completed before cancel (fast smoke path)"
else
  api_request "${admin_jar}" POST "/api/jobs/${job2}/cancel"
  [[ "${API_STATUS}" == "200" ]] || fail "cancel job2: ${API_STATUS}: ${API_BODY}"
  st2=""
  for _ in $(seq 1 30); do
    api_request "${admin_jar}" GET "/api/jobs/${job2}"
    st2="$(jq -r .status <<<"${API_BODY}")"
    [[ "${st2}" == "cancelled" ]] && break
    sleep 1
  done
  [[ "${st2}" == "cancelled" ]] || fail "job2 not cancelled after cancel: ${st2}"
  echo "  queued/running job2 cancelled"
fi

echo "[5] job1 gallery row + PNG file download"
api_get "${admin_jar}" "/api/jobs/${job1}" >/dev/null
gal="$(jq -r '.gallery[0].id // empty' <<<"${API_BODY}")"
[[ -n "${gal}" ]] || fail "no gallery row for job1: ${API_BODY}"
dl="$(mktemp)"
trap 'rm -f "${dl}"' EXIT
code="$(${CURL} "${CURL_COMMON[@]}" -b "${admin_jar}" -o "${dl}" -w '%{http_code}' \
  "${E2E_BASE_URL}/api/gallery/${gal}/file")"
[[ "${code}" == "200" ]] || fail "gallery file status ${code}"
magic="$(od -An -tx1 -N8 "${dl}" | tr -d ' \n')"
[[ "${magic}" == "89504e470d0a1a0a" ]] || fail "gallery file is not a PNG"
echo "  gallery item ${gal} downloads as PNG"

echo "[6] validation failure: qwen-t2i without required prompt -> 422"
api_request "${admin_jar}" POST /api/jobs '{"template_id":"qwen-t2i","params":{}}'
[[ "${API_STATUS}" == "422" ]] || fail "expected 422 got ${API_STATUS}: ${API_BODY}"

echo "[7] job failure: broken fixture template -> failed with no gallery"
api_request "${admin_jar}" POST /api/jobs '{"template_id":"broken","params":{}}'
[[ "${API_STATUS}" == "201" ]] || fail "broken job not accepted: ${API_STATUS}: ${API_BODY}"
fb="$(jq -r '.job_id // empty' <<<"${API_BODY}")"
stf=""
for _ in $(seq 1 30); do
  api_request "${admin_jar}" GET "/api/jobs/${fb}"
  stf="$(jq -r .status <<<"${API_BODY}")"
  [[ "${stf}" == "failed" ]] && break
  sleep 1
done
[[ "${stf}" == "failed" ]] || fail "broken job did not fail (${stf})"
api_request "${admin_jar}" GET "/api/jobs/${fb}"
gal_f="$(jq -r '.gallery | length' <<<"${API_BODY}")"
[[ "${gal_f}" == "0" ]] || fail "failed job has gallery rows"

echo "[8] two-user isolation: user@test cannot see/read/cancel admin items"
api_get "${admin_jar}" /api/gallery >/dev/null
[[ -n "$(jq -r --arg g "${gal}" '.items[] | select(.id == $g) | .id' <<<"${API_BODY}")" ]] \
  || fail "admin gallery does not contain job1 media ${gal}"
api_get "${user_jar}" /api/gallery >/dev/null
u_ids="$(jq -r '.items[].id' <<<"${API_BODY}")"
if grep -qx "${gal}" <<<"${u_ids}"; then
  fail "user@test gallery leaks admin media ${gal}"
fi
code_u="$(${CURL} "${CURL_COMMON[@]}" -b "${user_jar}" -o /dev/null -w '%{http_code}' \
  "${E2E_BASE_URL}/api/gallery/${gal}/file")"
[[ "${code_u}" == "403" ]] || fail "user@test reads admin gallery file: ${code_u}"
api_request "${user_jar}" POST "/api/jobs/${job1}/cancel"
[[ "${API_STATUS}" == "403" ]] || fail "user@test cancels admin job: ${API_STATUS}: ${API_BODY}"

echo "SMOKE: ALL PASS"