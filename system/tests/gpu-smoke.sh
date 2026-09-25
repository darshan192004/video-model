#!/usr/bin/env bash
# GPU/workflow validation for the four production templates. Two modes:
#
#   --validate-shape   (THIS MACHINE, no GPU): parse workflows, manifest
#                        lockstep, schema alignment, no App-Mode fields; then
#                        the P2 workflow_schema.sh class/bind checks.
#   --deploy           (USER BOX ONLY, [DEFERRED-REAL]): org-SSO login ->
#                        submit each of qwen-t2i/qwen-edit/wan-t2v/wan-i2v
#                        through /api/jobs at REDUCED steps -> poll success ->
#                        assert the gallery PNG -> sample nvidia-smi into a csv.
#
# --deploy requires a live control-plane + GPU ComfyUI on the box and is driven
# by the operator per docs/ops/gpu-wire-up.md; it is never executed here.
set -euo pipefail

MODE="${1:---validate-shape}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bow() { echo "gpu-smoke FAIL: $*" >&2; exit 1; }

WAIT_TEMPLATES=(qwen-t2i qwen-edit wan-t2v wan-i2v)
WORKFLOW_FILES=(qwen-t2i.json qwen-edit.json wan-t2v-a14b.json wan-i2v-a14b.json)

validate_shape() {
  echo "== validate-shape (this machine)"
  [[ -f "$ROOT/config/models.manifest.json" ]] || bow "missing manifest"
  [[ -f "$ROOT/config/templates.schema.json" ]] || bow "missing templates.schema.json"
  for wf in "${WORKFLOW_FILES[@]}"; do
    file="$ROOT/workflows/$wf"
    [[ -s "$file" ]] || bow "missing workflow $wf"
    jq empty "$file" || bow "$wf not valid JSON"
    jq -e 'to_entries | all(.value | type == "object" and has("class_type"))' "$file" >/dev/null \
      2>&1 || bow "$wf is not API-format (a node lacks class_type)"
    if jq -e '.extra?' "$file" >/dev/null 2>&1; then
      grep -q 'appMode' "$file" && bow "$wf contains appMode"
    fi
    refs="$(jq -r '.. | strings | select(test("\\.safetensors$"))' "$file" 2>/dev/null | sort -u)"
    [[ -n "${refs}" ]] || bow "$wf references no .safetensors weight (empty manifest lockstep)"
    for r in $refs; do
      grep -q -- "$r" "$ROOT/config/models.manifest.json" \
        || bow "$wf references unknown weight: $r (manifest lockstep)"
      grep -q "$wf" "$ROOT/config/templates.schema.json" \
        || bow "$wf has no entry in templates.schema.json (schema alignment)"
    done
  done
  bash "$ROOT/tests/workflow_schema.sh"   # classes in /object_info + bind alignment (class check needs COMFY_OBJECT_INFO)
  echo "  shape OK (workflows API-format + parse, manifest lockstep, schema aligned, no appMode)"
}

deploy() {  # user box only
  echo "== deploy (USER BOX ONLY; DEFERRED)"

  # --- session: org-SSO via lib_login, or an operator-supplied cookie jar ---
  source "$ROOT/tests/lib_login.sh"
  if [[ -n "${GPU_SMOKE_COOKIE_JAR:-}" ]]; then
    JAR="$GPU_SMOKE_COOKIE_JAR"
  elif [[ -n "${DEX_USER:-}" && -n "${DEX_PASS:-}" ]]; then
    JAR="$(login_as "$DEX_USER" __ADMIN_DEFAULT__ "$DEX_PASS")"
  else
    bow "--deploy needs DEX_USER/DEX_PASS (org SSO) or GPU_SMOKE_COOKIE_JAR"
  fi

  # --- a source image for the two image in-templates ---
  SRC_IMG="${GPU_SMOKE_IMAGE:-}"
  if [[ -z "${SRC_IMG}" ]]; then
    SRC_IMG="$(mktemp --suffix=.png)"
    python3 - "$SRC_IMG" <<'PY'
import struct, sys, zlib
w = h = 320
rows = []
for y in range(h):
    rows.append(b"\x00" + bytes((x * 3) % 256 for x in range(w)) + bytes((y * 3) % 256 for x in range(w)) + b"\x80" * w)
raw = b"".join(rows)
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
open(sys.argv[1], "wb").write(png)
PY
  fi
  code="$(${CURL} "${CURL_COMMON[@]}" -b "$JAR" -o /tmp/upload_resp.json -w '%{http_code}' \
    -F "file=@${SRC_IMG};type=image/png" "${E2E_BASE_URL}/api/uploads/pre")"
  [[ "$code" == "200" ]] || bow "upload failed (${code}): $(cat /tmp/upload_resp.json)"
  IMAGE_REF="$(jq -r .url_path /tmp/upload_resp.json)"
  [[ -n "${IMAGE_REF}" && "${IMAGE_REF}" != null ]] || bow "no url_path in upload response"

  # --- submitted templates (reduced steps, fixed seed, short frames) ---
  PROMPT="${GPU_SMOKE_PROMPT:-asteroids passing the rings of a gas giant, cinematic lighting}"
  SEED="${GPU_SMOKE_SEED:-42}"
  LENGTH="${GPU_SMOKE_LENGTH:-17}"
  ARTIFACTS="$ROOT/tests/artifacts"
  mkdir -p "$ARTIFACTS"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  CSV="$ARTIFACTS/gpu-smoke-$STAMP.csv"
  LOG="$ARTIFACTS/gpu-smoke-$STAMP.log"

  tpl="$(api_get "$JAR" /api/templates)"
  echo "date,template,status,media,error" > "$LOG"

  nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null 2>&1 || bow "nvidia-smi unavailable on the box"
  sampler() {
    while :; do
      nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu --format=csv,noheader,nounits >>"$CSV" 2>/dev/null || break
      sleep 2
    done
  }
  sampler &
  SAMPLER_PID=$!

  for tid in "${WAIT_TEMPLATES[@]}"; do
    spec="$(api_get "$JAR" "/api/templates/$tid/schema")"
    body="$(python3 - "$spec" "$PROMPT" "$IMAGE_REF" "$SEED" "$LENGTH" <<'PY'
import json, sys
spec = json.loads(sys.argv[1]); prompt, image_ref, seed, length = sys.argv[2:6]
params = {}
for name, p in spec.get("params", {}).items():
    if "default" in p and p.get("default") is not None:
        params[name] = p["default"]
    elif p.get("type") == "string":
        params[name] = prompt
if isinstance(params.get("steps"), int):
    params["steps"] = max(4, params["steps"] // 2)
if "length" in params:
    params["length"] = int(length)
if "seed" in params:
    params["seed"] = int(seed)
for img_param, p in spec.get("params", {}).items():
    if p.get("type") == "image":
        params[img_param] = image_ref
print(json.dumps({"template_id": spec["id"], "params": params}))
PY
)"
    api_request "$JAR" POST /api/jobs "$body"
    [[ "$API_STATUS" == "201" ]] || { echo "$STAMP,$tid,reject,," >> "$LOG"; bow "$tid submission: $API_STATUS $API_BODY"; }
    jid="$(jq -r .job_id <<<"$API_BODY")"
    st="queued"
    for _ in $(seq 1 720); do          # up to ~2h per job on the box
      api_request "$JAR" GET "/api/jobs/$jid"
      st="$(jq -r .status <<<"$API_BODY")"
      [[ "$st" == "running" || "$st" == "queued" ]] || break
      sleep 10
    done
    if [[ "$st" != "success" ]]; then
      echo "$STAMP,$tid,$st,," >> "$LOG"
      bow "$tid ended $st: $(jq -c .error <<<"$API_BODY")"
    fi
    url="$(jq -r '.gallery[0].file_url // empty' <<<"$API_BODY")"
    curl "${CURL_COMMON[@]}" -b "$JAR" -o /tmp/gpu-media.bin -w '%{http_code}' "${E2E_BASE_URL}${url}" >/tmp/gpu-code
    [[ "$(<"/tmp/gpu-code")" == "200" ]] || bow "$tid gallery file missing (${url})"
    magic="$(od -An -tx1 -N8 /tmp/gpu-media.bin | tr -d ' \n')"
    [[ "$magic" == "89504e470d0a1a0a" ]] || bow "$tid gallery file is not a PNG"
    echo "$STAMP,$tid,success,$url," >> "$LOG"
    echo "  $tid: success (front = $url)"
  done
  kill "$SAMPLER_PID" 2>/dev/null || true
  wait "$SAMPLER_PID" 2>/dev/null || true
  peak="$(awk -F',' 'NR==1 {m=$2} $2+0>m {m=$2} END {print m}' "$CSV")"
  echo "gpu-smoke deploy: 4/4 templates succeeded; peak VRAM ${peak} MiB (see $CSV)"
}

case "$MODE" in
  --validate-shape) validate_shape ;;
  --deploy) deploy ;;
  *) echo "usage: gpu-smoke.sh [--validate-shape|--deploy]" >&2; exit 2 ;;
esac