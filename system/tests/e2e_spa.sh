#!/usr/bin/env bash
# E2E against a LIVE system/* stack (native or compose/k3s): control-plane +
# worker + mock ComfyUI + Postgres, reached through nginx at
# https://${OIDC_DOMAIN}:${HTTPS_PORT}. OIDC_MOCK=1 uses the in-app mock
# issuer (dev box); otherwise the real Dex code flow is driven through
# lib_login.sh. 12 groups from the P1.5 exit criteria.
#
# Native run (dev box):
#   DOMAIN=media.local HTTPS_PORT=8443 OIDC_MOCK=1 bash tests/e2e_spa.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_login.sh
source "${HERE}/lib_login.sh"

ARTIFACTS="${HERE}/artifacts"
mkdir -p "${ARTIFACTS}"
exec > >(tee -a "${ARTIFACTS}/e2e.log")
echo "=== e2e_spa starting $(date -u +%FT%TZ) base=${E2E_BASE_URL} oidc_mock=${OIDC_MOCK:-0} ==="

PASS=0
FAIL=0
FAILED_DESC=()

ok() { PASS=$((PASS + 1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL + 1)); FAILED_DESC+=("$1: $2"); echo "  FAIL - $1: $2"; }

assert_eq() { # desc got expected
  if [[ "$2" == "$3" ]]; then ok "$1 (got $2)"; else bad "$1" "got '$2', expected '$3'"; fi
}
assert_ne() { # desc got notwant
  if [[ "$2" != "$3" ]]; then ok "$1 (got $2)"; else bad "$1" "got unexpected '$2'"; fi
}
assert_contains() { # desc haystack needle
  if [[ "$2" == *"$3"* ]]; then ok "$1"; else bad "$1" "missing \"$3\" in \"$2\""; fi
}

pyj() { # <expr>  reads JSON on stdin
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))' "$1"
}

me_email() { me_fields "$1" 'd["email"]'; }
me_admin() { me_fields "$1" 'd["is_admin"]'; }

create_smoke() { # jar seed -> job_id
  api_post "$1" /api/jobs "{\"template_id\":\"smoke\",\"params\":{\"seed\":\"$2\"}}" \
    | pyj 'd["job_id"]'
}

wait_for_job() { # jar job_id [timeout_s]
  local jar="$1" job="$2" timeout="${3:-90}"
  for _ in $(seq 1 "${timeout}"); do
    api_request "${jar}" GET "/api/jobs/${job}"
    local st
    st="$(pyj 'd["status"]' <<<"${API_BODY}")"
    case "${st}" in
      success|failed|cancelled) echo "${st}"; return 0 ;;
    esac
    sleep 1
  done
  echo "TIMEOUT"
  return 1
}

echo
echo "--- 1/12 unauthenticated access ---"
t_jar="$(mktemp)"
api_request "${t_jar}" GET /api/jobs
assert_eq "unauthenticated /api/jobs is 401" "${API_STATUS}" "401"
t_body="$(api_get "${t_jar}" /)"
assert_contains "readme / renders SPA HTML" "${t_body}" "Media Studio"

echo
echo "--- 2/12 SSO start redirect ---"
s_jar="$(mktemp)"
s_headers="$(${CURL} "${CURL_COMMON[@]}" -sS -D - -o /dev/null -b "${s_jar}" -c "${s_jar}" "${E2E_BASE_URL}/api/auth/start")"
s_loc="$(sed -nE '/^[Ll]ocation:/{s/^[Ii][Rr][^:]*: *//;s/\r$//;p;q}' <<<"${s_headers}")"
assert_contains "/api/auth/start redirects with state" "${s_loc}" "state="
if [[ "${OIDC_MOCK}" == "1" ]]; then
  assert_contains "mock start redirects straight to the callback" "${s_loc}" "/api/auth/callback"
  assert_contains "mock callback carries the authorization code" "${s_loc}" "code=mock"
else
  assert_contains "redirect carries client_id=media-controlplane" "${s_loc}" "client_id=media-controlplane"
  assert_contains "redirect carries the callback redirect_uri" "${s_loc}" "redirect_uri="
fi

echo
echo "--- 3/12 admin login ---"
admin_jar="$(login_as admin@test)"
assert_eq "admin@test can log in" "$(me_email "${admin_jar}")" "admin@test"
assert_eq "admin@test is_admin via role mapping" "$(me_admin "${admin_jar}")" "True"

echo
echo "--- 4/12 templates ---"
tpl="$(api_get "${admin_jar}" /api/templates)"
tpl_n="$(pyj 'len(d["templates"])' <<<"${tpl}")"
assert_eq "template list exposes all five templates" "${tpl_n}" "5"
t2v="$(api_get "${admin_jar}" /api/templates/t2v/schema)"
t2v_kind="$(pyj 'd["kind"]' <<<"${t2v}")"
assert_eq "template schema is typed (kind)" "${t2v_kind}" "video"
t2v_types="$(pyj 'sorted({p["type"] for p in d["params"]})' <<<"${t2v}")"
assert_contains "schema params carry JSON-schema types" "${t2v_types}" "int"

echo
echo "--- 5/12 smoke job: enqueue, run, gallery copy ---"
job1="$(create_smoke "${admin_jar}" e2e-a)"
assert_ne "job1 created with a non-empty id" "${job1}" ""
st1="$(wait_for_job "${admin_jar}" "${job1}")"
assert_eq "job1 reaches success" "${st1}" "success"
api_get "${admin_jar}" "/api/jobs/${job1}"
gal_n="$(pyj 'len(d["gallery"])' <<<"${API_BODY}")"
assert_eq "successful job produced a gallery row" "${gal_n}" "1"
file_url="$(pyj 'd["gallery"][0]["file_url"]' <<<"${API_BODY}")"
media_id="$(pyj 'd["gallery"][0]["id"]' <<<"${API_BODY}")"
dl="$(mktemp)"
code="$(${CURL} "${CURL_COMMON[@]}" -b "${admin_jar}" -o "${dl}" -w '%{http_code}' "${E2E_BASE_URL}${file_url}")"
assert_eq "gallery file serves 200" "${code}" "200"
magic="$(${CURL} "${CURL_COMMON[@]}" -b "${admin_jar}" -sS "${E2E_BASE_URL}${file_url}" | head -c 8 | od -An -tx1 | tr -d ' \n')"
assert_eq "gallery file carries PNG magic bytes" "${magic}" "89504e470d0a1a0a"
rm -f "${dl}"

echo
echo "--- 6/12 FIFO ordering ---"
jobA="$(create_smoke "${admin_jar}" fifo-a)"
jobB="$(create_smoke "${admin_jar}" fifo-b)"
stA="$(wait_for_job "${admin_jar}" "${jobA}")"
stB="$(wait_for_job "${admin_jar}" "${jobB}")"
assert_eq "FIFO first job succeeds" "${stA}" "success"
assert_eq "FIFO second job succeeds" "${stB}" "success"
api_request "${admin_jar}" GET "/api/jobs/${jobA}"
sA="$(pyj 'd["started_at"]' <<<"${API_BODY}")"
api_request "${admin_jar}" GET "/api/jobs/${jobB}"
sB="$(pyj 'd["started_at"]' <<<"${API_BODY}")"
if [[ -n "${sA}" && -n "${sB}" ]]; then
  # Lexicographic ISO-8601 compare (uniform UTC): the first-submitted job must
  # have started first -> worker honours claim order.
  if [[ "${sA}" > "${sB}" ]]; then
    bad "FIFO start-order" "${sA} started after ${sB}"
  else
    ok "FIFO start-order (${sA} <= ${sB})"
  fi
else
  bad "FIFO start-order" "missing started_at ($sA/$sB)"
fi

echo
echo "--- 7/12 cancel a queued job ---"
jobC="$(create_smoke "${admin_jar}" cancel-a)"
api_request "${admin_jar}" POST "/api/jobs/${jobC}/cancel"
canc="${API_STATUS}"
case "${canc}" in
  200) ok "cancel accepted on queued job (${canc})" ;;
  409) ok "cancel raced a finished job (${canc})" ;;
  *) bad "cancel request" "unexpected status ${canc}: ${API_BODY}" ;;
esac
stC="$(wait_for_job "${admin_jar}" "${jobC}")"
assert_ne "cancelled/raced job never fails" "${stC}" "failed"

echo
echo "--- 8/12 validation + failure paths ---"
api_request "${admin_jar}" POST /api/jobs "{\"template_id\":\"i2v\",\"params\":{}}"
assert_eq "missing required image param rejects with 422" "${API_STATUS}" "422"
assert_contains "422 explains the bad parameter" "${API_BODY}" 'image'
jbad="$(create_smoke "${admin_jar}" "$(date +%s)-nominal")"
st_ok="$(wait_for_job "${admin_jar}" "${jbad}" 40)"
assert_eq "control smoke job still succeeds" "${st_ok}" "success"
if [[ -n "${MOCK_COMFY_FAIL_SUBSTR:-}" ]]; then
  jbrk="$(create_smoke "${admin_jar}" "e2e-broken-${MOCK_COMFY_FAIL_SUBSTR}")"
  st_brk="$(wait_for_job "${admin_jar}" "${jbrk}")"
  assert_eq "broken node graph lands in failed" "${st_brk}" "failed"
  api_request "${admin_jar}" GET "/api/jobs/${jbrk}"
  assert_contains "failed job carries the backend error" "${API_BODY}" "${MOCK_COMFY_FAIL_SUBSTR}"
  assert_eq "failed job writes NO gallery row" "$(pyj 'len(d["gallery"])' <<<"${API_BODY}")" "0"
else
  echo "  skip - MOCK_COMFY_FAIL_SUBSTR unset (broken-workflow fixture off)"
fi

echo
echo "--- 9/12 two-user isolation ---"
user_jar="$(login_as user@test '')"
assert_eq "user@test is not an admin" "$(me_admin "${user_jar}")" "False"
api_request "${user_jar}" GET /api/gallery
user_owns="$(python3 -c 'import json,sys
d=json.load(sys.stdin)
ids=[i["id"] for i in d["items"]]
print("yes" if {media_id} in ids else "no")' <<<"${API_BODY}")"
assert_eq "user@test gallery excludes admin media" "${user_owns}" "no"
code_u="$(${CURL} "${CURL_COMMON[@]}" -b "${user_jar}" -o /dev/null -w '%{http_code}' "${E2E_BASE_URL}${file_url}")"
assert_eq "cross-user gallery file read is 403" "${code_u}" "403"
api_request "${user_jar}" POST "/api/jobs/${job1}/cancel"
assert_eq "cross-user job cancel is 403" "${API_STATUS}" "403"

echo
echo "--- 10/12 admin moderation ---"
ujob="$(create_smoke "${user_jar}" user-moderated)"
ust="$(wait_for_job "${user_jar}" "${ujob}")"
assert_eq "user@test job succeeds for moderation fixture" "${ust}" "success"
api_request "${user_jar}" GET "/api/jobs/${ujob}"
u_file_url="$(pyj 'd["gallery"][0]["file_url"]' <<<"${API_BODY}")"
u_media_id="$(pyj 'd["gallery"][0]["id"]' <<<"${API_BODY}")"
api_request "${admin_jar}" POST "/api/admin/gallery/${u_media_id}/delete"
assert_eq "admin moderator delete succeeds" "${API_STATUS}" "200"
code_u2="$(${CURL} "${CURL_COMMON[@]}" -b "${user_jar}" -o /dev/null -w '%{http_code}' "${E2E_BASE_URL}${u_file_url}")"
assert_eq "moderated file is now 404 to the owner" "${code_u2}" "404"

echo
echo "--- 11/12 admin API access control ---"
api_request "${user_jar}" GET /api/admin/system
assert_eq "non-admin /api/admin/system is 403" "${API_STATUS}" "403"
api_request "${admin_jar}" GET /api/admin/system
assert_eq "admin /api/admin/system is 200" "${API_STATUS}" "200"
assert_contains "system view exposes versions" "${API_BODY}" "fastapi"

echo
echo "--- 12/12 logout invalidates the session ---"
api_request "${admin_jar}" POST /api/auth/logout
assert_eq "logout returns 204" "${API_STATUS}" "204"
api_request "${admin_jar}" GET /api/jobs
assert_eq "logged-out cookie no longer authenticates" "${API_STATUS}" "401"

echo
echo "=== e2e_spa: ${PASS} assertions ok, ${FAIL} failed ==="
if [[ "${FAIL}" -gt 0 ]]; then
  printf 'failed: %s\n' "${FAILED_DESC[@]}" >&2
  exit 1
fi
exit 0