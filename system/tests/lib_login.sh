#!/usr/bin/env bash
# lib_login.sh - browserless OIDC login, shared verbatim by every e2e stage
# (P1.5 SPA suite, P3 smoke, P4 GPU smoke, P5 k8s smoke).
#
#   source tests/lib_login.sh
#   login_as admin@test          # asserts the full code flow, sets LOGIN_JAR
#   login_as user@test ''        # second arg groups; '' == NO groups
#   api_request "$jar" GET /api/auth/me    # -> API_STATUS / API_BODY
#
# Modes:
#   * OIDC_MOCK=1  in-app mock identity (dev/native stack; no issuer needed)
#   * otherwise    real OIDC code flow against $DEX_OIDC_ISSUER (test Dex),
#                  posting to the Dex password form with $DEX_USER/$DEX_PASS.
#
# Parameterization (all defaulted): E2E_BASE_URL, OIDC_DOMAIN, HTTPS_PORT,
# NO_RESOLVE, OIDC_MOCK, DEX_OIDC_ISSUER, DEX_USER, DEX_PASS, CURL.
set -euo pipefail

: "${OIDC_DOMAIN:=media.local}"
: "${OIDC_SCHEME:=https}"
: "${HTTPS_PORT:=443}"
: "${OIDC_MOCK:=}"
: "${DEX_OIDC_ISSUER:=http://host.docker.internal:5556/dex}"
: "${DEX_USER:=admin@test}"
: "${DEX_PASS:=}"
export OIDC_DOMAIN OIDC_SCHEME HTTPS_PORT OIDC_MOCK DEX_OIDC_ISSUER DEX_USER DEX_PASS

E2E_BASE_URL="${E2E_BASE_URL:-${OIDC_SCHEME}://${OIDC_DOMAIN}:${HTTPS_PORT}}"
export E2E_BASE_URL
CURL="${CURL:-curl}"

declare -a CURL_COMMON
CURL_COMMON=(-sS --insecure --max-time 90 --connect-timeout 15)
if [[ "${NO_RESOLVE:-}" != "1" ]]; then
  # Native stack: the test host reaches media.local only via 127.0.0.1.
  CURL_COMMON+=(--resolve "${OIDC_DOMAIN}:${HTTPS_PORT}:127.0.0.1")
fi

API_STATUS=000
API_BODY=""

csrf_from() { # <cookie-jar> -> csrf token
  awk -F'\t' '$6 == "media_csrf" { print $7; exit }' "$1"
}

api_request() { # <jar> <METHOD> <path> [json-body]
  local jar="$1" method="$2" path="$3" payload="${4-}"
  local out
  out="$(mktemp)"
  local -a args=("${CURL_COMMON[@]}" -o "$out" -w '%{http_code}')
  args+=(-b "$jar" -c "$jar" -H 'Accept: application/json' -X "$method")
  if [[ "${method}" != "GET" && "${method}" != "HEAD" ]]; then
    args+=(-H "X-CSRF: $(csrf_from "$jar")")
  fi
  if [[ -n "${payload}" ]]; then
    args+=(-H 'Content-Type: application/json' --data-binary "${payload}")
  fi
  API_STATUS="$(${CURL} "${args[@]}" "${E2E_BASE_URL}${path}")"
  API_BODY="$(<"${out}")"
  rm -f "${out}"
}

api_get() { # <jar> <path> -> body, asserts 2xx
  api_request "$1" GET "$2"
  [[ "${API_STATUS}" == 2* ]] || { echo "api_get FAIL (${API_STATUS}): $2 :: ${API_BODY}" >&2; return 1; }
  cat <<<"${API_BODY}"
}

api_post() { # <jar> <path> [json] -> body, asserts 2xx
  api_request "$1" POST "$2" "${3-}"
  [[ "${API_STATUS}" == 2* ]] || { echo "api_post FAIL (${API_STATUS}): $2 :: ${API_BODY}" >&2; return 1; }
  cat <<<"${API_BODY}"
}

login_as() { # <email> [groups]   groups unset/default->admin claim; ''->none
  local email="$1"
  local groups="${2-__ADMIN_DEFAULT__}"
  local jar
  jar="$(mktemp)"

  local -a start_args=("${CURL_COMMON[@]}" -sS -D - -o /dev/null -b "$jar" -c "$jar")
  start_args+=(-G --data-urlencode "email=${email}")
  if [[ "${groups}" != "__ADMIN_DEFAULT__" ]]; then
    start_args+=(--data-urlencode "groups=${groups}")
  fi
  local start_headers
  start_headers="$(${CURL} "${start_args[@]}" "${E2E_BASE_URL}/api/auth/start")" || {
    echo "login_as: /api/auth/start unreachable" >&2
    return 1
  }
  local location
  location="$(sed -nE '/^[Ll]ocation:/{s/^[Ii][Rr][^:]*: *//;s/\r$//;p;q}' <<<"${start_headers}")"
  if [[ -z "${location}" ]]; then
    echo "login_as: /api/auth/start did not redirect" >&2
    return 1
  fi

  if [[ "${OIDC_MOCK}" == "1" ]]; then
    # Mock mode: the start screen 302s straight to the callback.
    ${CURL} "${CURL_COMMON[@]}" -o /dev/null -L -b "$jar" -c "$jar" "${location}" \
      || { echo "login_as: mock callback failed" >&2; return 1; }
  else
    # Real Dex flow: start -> Dex auth page -> password form -> callback.
    local form csrf action
    form="$(${CURL} "${CURL_COMMON[@]}" -L -b "$jar" -c "$jar" "${location}")" \
      || { echo "login_as: Dex auth page unreachable" >&2; return 1; }
    csrf="$(sed -nE 's/.*name="csrf" value="([^"]*)".*/\1/p' <<<"${form}" | head -1)"
    action="$(sed -nE 's/.*action="([^"]*)".*/\1/p' <<<"${form}" | head -1)"
    if [[ -z "${csrf}" || -z "${action}" ]]; then
      echo "login_as: could not parse Dex password form" >&2
      return 1
    fi
    if [[ "${action}" == /* ]]; then
      local issuer_host
      issuer_host="$(sed -nE 's#^(https?://[^/]+).*#\1#p' <<<"${DEX_OIDC_ISSUER}")"
      action="${issuer_host}${action}"
    fi
    ${CURL} "${CURL_COMMON[@]}" -o /dev/null -L -b "$jar" -c "$jar" \
      --data-urlencode "login=${email}" \
      --data-urlencode "password=${DEX_PASS}" \
      --data-urlencode "csrf=${csrf}" \
      "${action}" || { echo "login_as: Dex login POST failed" >&2; return 1; }
  fi

  # Verify a real session exists before handing the jar over.
  api_request "${jar}" GET /api/auth/me
  if [[ "${API_STATUS}" != "200" ]]; then
    echo "login_as: no session after flow (${API_STATUS})" >&2
    return 1
  fi
  LOGIN_JAR="${jar}"
  LOGIN_EMAIL="${email}"
  echo "${jar}"
}

me_fields() { # <jar> <python-expr-on-dict>  e.g. 'x["email"]'
  local jar="$1"
  api_request "${jar}" GET /api/auth/me
  [[ "${API_STATUS}" == "200" ]] || return 1
  python3 -c "import json,sys; d=json.loads('''${API_BODY}'''); print(eval(sys.argv[1]))" "$2"
}