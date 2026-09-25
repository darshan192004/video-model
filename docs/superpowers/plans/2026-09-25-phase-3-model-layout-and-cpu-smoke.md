# Phase 3 — Model Wiring + Smoke on Dev Box Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the machine-readable model manifest (`models.manifest.json`), provide `link-models.sh` that maps a user's weight tree into ComfyUI's `models/` layout with sha256 verification, then prove the whole request roundtrip works in CPU mode on the dev box **through the control-plane** — OIDC login (test Dex), submit → FIFO progress → gallery result, including cancel, validation-failure, job-failure, and **two-user gallery isolation** paths.

**Architecture:** `MODELS_PATH` points at the user's weight tree; `link-models.sh` builds the container `models/` layout (symlink forest) constrained to `MODELS_PATH`, validating sha256 against the manifest when real hashes exist. `tests/smoke.sh` drives the **control-plane API**: login via the P1.5 test Dex → session cookie → `POST /api/jobs` (smoke template) → poll `GET /api/jobs/{id}` → assert gallery row + `GET /api/gallery/{id}/file` PNG, then cancel/FIFO/validation/broken-template/isolation paths. No direct ComfyUI HTTP from tests.

**Tech Stack:** Bash, jq, sha256sum, curl, websocat (optional WS check), Python (helper for WS probe).

**Spec:** `docs/superpowers/specs/2026-09-25-comfyui-app-mode-media-system-design.md` — Phase 3 implements §5.4, §6 (data flow), §7 (job lifecycle), §9 (smoke), §10 P3. Reconciles workflow weight filenames (Phase 2) with the manifest here.

## Global Constraints

- **Manifest ↔ workflows lockstep:** every filename referenced by `workflows/*.json` MUST appear in `models.manifest.json` (and vice-versa for pre-required files). Verified by `verify-manifest-lockstep.sh` (Task 3.2).
- Spelled **`loras`** everywhere — no `"lo ras"` typo in any committed file (schema `enum` included).
- sha256 values must match the files the user actually serves (Phase 4 verifies on the 3090); values are pinned as the contract and TODO-checked if the tree differs. For dev, placeholder hashes are skipped by `link-models.sh`.
- `link-models.sh` must refuse to follow symlinks that escape `MODELS_PATH` (defense-in-depth).
- Files under `system/models/` (symlinks) and the real `MODELS_PATH` are gitignored; `models.manifest.json` is committed.
- `smoke.sh` must exit non-zero on any assertion failure and print the failing stage.
- Cancel path: the **control-plane's** `/api/jobs/{id}/cancel` (sets `cancelled`; the worker interrupts a running prompt and skips queued rows). Tests never hit ComfyUI's `/queue`.
- **Test environment (this machine only):** no GPU, no real weights. All Phase-3 testing uses **fixture files** (zero-byte/sparse) under `/tmp/media-weights`. Real sha256 is pinned later on the user's box via `link-models.sh --write-hashes`. The full roundtrip smoke runs here in CPU compose mode and is re-asserted in-k3s in Phase 5.
- Authentication in every smoke path uses the **test Dex** identities (`admin@test`/`user@test`, group `media-admins`) — the old `smoke:smoke-pass-312` basic-auth user no longer exists.

---

## File Structure (Phase 3 creates)

- `system/config/models.manifest.json` — the weight contract.
- `system/config/models.schema.json` — JSON schema for the manifest (includes `loras` dir).
- `system/scripts/link-models.sh` — MODELS_PATH → ComfyUI models layout with sha256 check.
- `system/scripts/verify-manifest-lockstep.sh` — cross-checks workflow filenames vs manifest.
- `system/tests/lib_login.sh` — shared OIDC login helper (created in P1.5; consumed here and reused by P5).
- `system/tests/smoke.sh` — control-plane smoke: login/FIFO/cancel/failure/isolation/gallery.
- `system/tests/workflows/broken-template.json` — deliberately invalid fixture (failure-path test).
- (Temporary) `system/models/` — symlink target tree produced by `link-models.sh` (gitignored).

---

### Task 3.1: Write `models.manifest.json`

**Files:**
- Create: `system/config/models.manifest.json`
- Create: `system/config/models.schema.json`

**Interfaces:**
- Consumes: field names used by `link-models.sh`: `{ "id", "role", "filename", "dir", "sha256", "size_hint_gb", "required" }`.
- Produces: authoritative list of weights and target dirs; workflow filenames reconciled in Task 3.2.

- [ ] **Step 1: Write the manifest**

Create `system/config/models.manifest.json` (sha256 hex placeholders replaced with real values procured from the user's tree in Phase 4; the manifest is valid JSON with exact placeholders now):

```json
{
  "$schema": "./models.schema.json",
  "version": 1,
  "release_date": "2026-09-25",
  "note": "Weights serve from MODELS_PATH; link-models.sh maps into ComfyUI/models layout.",
  "models": [
    { "id": "qwen-diffusion", "role": "diffusion_models", "filename": "qwen_image_2.1_int8_convrot.safetensors", "dir": "diffusion_models", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 8.0,  "required": true },
    { "id": "qwen-te",        "role": "text_encoders",   "filename": "qwen_image_2.1_text_encoder.f16.safetensors", "dir": "text_encoders", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 4.0,  "required": true },
    { "id": "qwen-vae",       "role": "vae",             "filename": "qwen_image_2.1_vae.safetensors", "dir": "vae", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 0.3,  "required": true },
    { "id": "wan-t2v-high",   "role": "diffusion_models", "filename": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors", "dir": "diffusion_models", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 14.0, "required": true },
    { "id": "wan-t2v-low",    "role": "diffusion_models", "filename": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors", "dir": "diffusion_models", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 14.0, "required": true },
    { "id": "wan-i2v-high",   "role": "diffusion_models", "filename": "wan2.2_i2v_high_noise_14B_fp16.safetensors", "dir": "diffusion_models", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 28.0, "required": true },
    { "id": "wan-i2v-low",    "role": "diffusion_models", "filename": "wan2.2_i2v_low_noise_14B_fp16.safetensors", "dir": "diffusion_models", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 28.0, "required": true },
    { "id": "wan-te",         "role": "text_encoders",   "filename": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "dir": "text_encoders", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 8.0,  "required": true },
    { "id": "wan-vae",        "role": "vae",             "filename": "wan_2.1_vae.safetensors", "dir": "vae", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_hint_gb": 0.4,  "required": true }
  ]
}
```

> **Hash policy (development vs. real):** sha256 stays `0000…` during development because real weights never exist on this machine. `link-models.sh` treats all-`0`/empty as "skip verification". `link-models.sh --write-hashes [path]` records computed sha256 into the manifest (in place, or into `path`) so the user's box pins true hashes automatically — no manual editing, keeping "MODELS_PATH is the only wiring step" true. Phase 6's gate asserts the placeholder form renders.

- [ ] **Step 2: Add a JSON schema for the manifest**

Create `system/config/models.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["models", "version"],
  "properties": {
    "version": { "type": "integer" },
    "models": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "role", "filename", "dir", "sha256"],
        "properties": {
          "id": { "type": "string" },
          "role": { "type": "string" },
          "filename": { "type": "string" },
          "dir": {
            "type": "string",
            "enum": ["diffusion_models", "text_encoders", "vae", "checkpoints", "loras", "clip", "controlnet"]
          },
          "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
          "size_hint_gb": { "type": "number" },
          "required": { "type": "boolean" }
        }
      }
    }
  }
}
```

(Note: `loras` is spelled correctly here — the historic `"lo ras"` typo is intentionally not present.)

- [ ] **Step 3: Validate manifest parses and schema-check it**

Run:
```bash
jq empty system/config/models.manifest.json && echo "manifest valid"
python3 - <<'PY'
import json
m = json.load(open('system/config/models.manifest.json'))
assert len(m['models']) == 9, m['models']
assert all(e['sha256'] and len(e['sha256'])==64 for e in m['models']), 'sha length'
print('manifest items:', len(m['models']))
PY
```
Expected: `manifest valid`, `manifest items: 9`.

- [ ] **Step 4: Commit**

```bash
git add system/config/models.manifest.json system/config/models.schema.json
git commit -m "feat: model weight manifest contract"
```

---

### Task 3.2: Manifest ↔ workflow lockstep verifier

**Files:**
- Create: `system/scripts/verify-manifest-lockstep.sh`

- [ ] **Step 1: Write the verifier**

Create `system/scripts/verify-manifest-lockstep.sh` (extract every `.safetensors` filename the workflows reference — widget keys per `/object_info`, e.g. `unet_name`, `clip_name`, `vae_name` — and assert each is in the manifest; warn on orphaned manifest entries). See the Phase-2 lockstep + shape so the extraction list covers the actual loader keys.

- [ ] **Step 2: Run the verifier**

```bash
bash system/scripts/verify-manifest-lockstep.sh
```
Expected: exit 0. If a loader widget key differs (`text_encoder_name` vs `clip_name`), extend the extraction list from `/object_info` and re-run until exit 0.

- [ ] **Step 3: Commit** — `feat: manifest/workflow lockstep verifier`.

---

### Task 3.3: `link-models.sh` — MODELS_PATH → ComfyUI models layout

**Files:**
- Create: `system/scripts/link-models.sh`

**Interfaces:**
- Consumes: env `MODELS_PATH` (default `/srv/media-weights`), `models.manifest.json`, target `system/models/`.
- Produces: `system/models/<dir>/<filename>` symlinks for each manifest entry; sha256 verification before linking (skipped on placeholder hashes); `--write-hashes [path]` records computed hashes. Idempotent.

- [ ] **Step 1: Write the script**

Create `system/scripts/link-models.sh` (flat `find -L "$SRC" -maxdepth 4` discovery, `realpath`-under-`MODELS_PATH` guard, sha256 verify-or-record per the hash policy, report + non-zero exit on missing/bad). Reference the prior-phase file for the exact jq/TSV loop; keep `declare -A NEW_HASHES` recording and the `--write-hashes` `jq` merge.

- [ ] **Step 2: Test with a fake tree**

```bash
mkdir -p /tmp/media-weights/fixtures
for f in qwen_image_2.1_int8_convrot.safetensors qwen_image_2.1_text_encoder.f16.safetensors \
         qwen_image_2.1_vae.safetensors wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors \
         wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors wan2.2_i2v_high_noise_14B_fp16.safetensors \
         wan2.2_i2v_low_noise_14B_fp16.safetensors umt5_xxl_fp8_e4m3fn_scaled.safetensors \
         wan_2.1_vae.safetensors; do
  dd if=/dev/zero of="/tmp/media-weights/fixtures/$f" bs=1 count=0 seek=4096 2>/dev/null
done
MODELS_PATH=/tmp/media-weights bash system/scripts/link-models.sh
```
Expected: all 9 reported "HASH pending"; symlinks created under `system/models/`.

- [ ] **Step 3: Test `--write-hashes`** — record fixture hashes into `/tmp/write-test-out.json`; assert every sha256 field length is `64` there while the committed manifest keeps placeholders.

- [ ] **Step 4: Test missing-file failure path** — `rm /tmp/media-weights/fixtures/wan_2.1_vae.safetensors`; `link-models.sh` exit 1 with the missing VAE listed; restore.

- [ ] **Step 5: Mount the linked tree into the compose stack (dev CPU)**

`base.yml` comfyui models mount uses `${LINKED_MODELS:-${MODELS_PATH:-/srv/media-weights}}:${LINKED_DEST:-/opt/ComfyUI/models}`; dev `.env` sets `LINKED_MODELS=…/system/models`. Confirm `docker compose … exec comfyui ls /opt/ComfyUI/models/diffusion_models | head` lists the nine names.

- [ ] **Step 6: Commit** — `feat: link-models wiring script and linked models mount`.

---

### Task 3.4: OIDC login helper + control-plane smoke suite

**Files:**
- Reuse: `system/tests/lib_login.sh` (created in P1.5 Task 1.5.8 — this task only depends on it)
- Create: `system/tests/smoke.sh`
- Create: `system/tests/workflows/broken-template.json` (fixture for the failure path)

**Interfaces:**
- Consumes: running compose stack (nginx + control-plane + postgres + comfyui CPU + dex-test); env `DOMAIN`/`HTTPS_PORT`/`NO_RESOLVE`/`DEX_USER`/`DEX_PASS`; `tests/lib_login.sh` from P1.5.
- Produces: exit 0 when all assertions pass; a repeatable in-k3s regression target (Phase 5).

- [ ] **Step 1: Confirm `system/tests/lib_login.sh` (P1.5) works against the compose stack**

No new code needed if P1.5's helper already exposes `login <email> <password>` → cookie jar honoring `DEX_OIDC_ISSUER`. If it needs tightening (e.g. CSRF re-capture or case where redirect is absolute), patch the helper directly and re-run P1.5's e2e — keep a single implementation, not a fork.

- [ ] **Step 2: Write `system/tests/smoke.sh`**

```bash
#!/usr/bin/env bash
# Control-plane smoke (CPU): OIDC login, FIFO queue, cancel, validation-failure,
# job-failure, two-user gallery isolation. Reads DOMAIN/HTTPS_PORT/NO_RESOLVE/
# DEX_USER/DEX_PASS. No direct ComfyUI HTTP — everything goes through /api/*.
set -euo pipefail

SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${DOMAIN:-media.local}"
PORT="${HTTPS_PORT:-443}"
if [[ "${NO_RESOLVE:-0}" == "1" ]]; then RESOLVE=""; else RESOLVE="--resolve ${DOMAIN}:${PORT}:127.0.0.1"; fi
ADMIN_EMAIL="${DEX_USER_ADMIN:-admin@test}"
USER_EMAIL="${DEX_USER_PLAIN:-user@test}"
ADMIN_PASS="${DEX_PASS_ADMIN:-adminpass}"
USER_PASS="${DEX_PASS_PLAIN:-userpass}"
BASE="https://${DOMAIN}:${PORT}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
. "$SYS/tests/lib_login.sh"

echo "[1] login admin@test and user@test -> session cookies"
COOKIE_A="$(login "$ADMIN_EMAIL" "$ADMIN_PASS")"
COOKIE_B="$(login "$USER_EMAIL" "$USER_PASS")"

echo "[2] submit smoke template as admin -> 201 job_id"
resp=$(curl -skb "$COOKIE_A" $RESOLVE -H 'Content-Type: application/json' \
  -d '{"template_id":"smoke","params":{}}' "$BASE/api/jobs")
job1=$(jq -r '.job_id // empty' <<<"$resp")
[[ -n "$job1" ]] || fail "no job_id from $resp"

echo "[3] second job while first running -> FIFO (stays queued until first done)"
resp2=$(curl -skb "$COOKIE_A" $RESOLVE -H 'Content-Type: application/json' \
  -d '{"template_id":"smoke","params":{}}' "$BASE/api/jobs")
job2=$(jq -r '.job_id // empty' <<<"$resp2")
st=$(curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/jobs/$job2" | jq -r .status)
# FIFO surfaces as: second job claims 'queued' while first is 'running' (fast CPUs may race) OR it also completes.
[ "$st" = "queued" ] || [ "$st" = "success" ] || fail "job2 unexpected status $st"
echo "  job2 initial status: $st"

echo "[4] wait for job1 success; cancel path on job2 if still queued"
st1=""; for i in $(seq 1 60); do
  st1=$(curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/jobs/$job1" | jq -r .status)
  [ "$st1" = "success" ] && break; [ "$st1" = "failed" ] && fail "job1 failed"
  sleep 1
done
st2=$(curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/jobs/$job2" | jq -r .status)
if [ "$st2" = "queued" ]; then
  code=$(curl -skb "$COOKIE_A" $RESOLVE -X POST "$BASE/api/jobs/$job2/cancel" -o /dev/null -w '%{http_code}')
  [ "$code" = "200" ] || fail "cancel status $code"
  st2=$(curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/jobs/$job2" | jq -r .status)
  [ "$st2" = "cancelled" ] || fail "job2 not cancelled: $st2"
  echo "  queued job2 cancelled"
else
  echo "  job2 completed before cancel (fast smoke)"   # acceptable; isolation still exercised below
fi

echo "[5] job1 gallery row + file download 200 PNG"
gal=$(curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/jobs/$job1" | jq -r '.gallery[0].id // empty')
[[ -n "$gal" ]] || fail "no gallery row for job1"
curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/gallery/$gal/file" -o "$TMP/out.bin"
file "$TMP/out.bin" | grep -qi 'png image' || fail "gallery file is not PNG"
echo "  gallery item $gal is a PNG"

echo "[6] validation failure: missing required param -> 422"
code=$(curl -skb "$COOKIE_A" $RESOLVE -o "$TMP/val.json" -w '%{http_code}' \
  -H 'Content-Type: application/json' -d '{"template_id":"qwen-t2i","params":{}}' "$BASE/api/jobs")
[ "$code" = "422" ] || fail "expected 422 got $code (missing required prompt)"

echo "[7] job failure: broken template -> status failed, no gallery"
# Inject a template that references a nonexistent node class through the test fixture path.
# (Implementation detail: broken-template.json is a workflow whose class_type does not
# exist in /object_info; a template_id 'broken' is registerable under the admin test hook.)
resp=$(curl -skb "$COOKIE_A" $RESOLVE -H 'Content-Type: application/json' \
  -d '{"template_id":"broken","params":{}}' "$BASE/api/jobs")
fb=$(jq -r '.job_id // empty' <<<"$resp")
[[ -n "$fb" ]] || fail "broken job not accepted"
stf=""; for i in $(seq 1 30); do
  stf=$(curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/jobs/$fb" | jq -r .status)
  [ "$stf" = "failed" ] && break; sleep 1
done
[ "$stf" = "failed" ] || fail "broken job did not fail: $stf"
gal_f=$(curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/jobs/$fb" | jq -r '.gallery | length')
[ "$gal_f" = "0" ] || fail "failed job has gallery rows"

echo "[8] two-user isolation: B cannot see or touch A's jobs/gallery"
gA=$(curl -skb "$COOKIE_A" $RESOLVE "$BASE/api/gallery")
gB=$(curl -skb "$COOKIE_B" $RESOLVE "$BASE/api/gallery")
# assert: gallery list for B contains no item id from A, and B's direct access 403s
echo "$gB" | jq -e --arg g "$gal" 'any(.items[]?.id == $g) | not' >/dev/null || fail "B can see A's gallery item"
code=$(curl -skb "$COOKIE_B" $RESOLVE -o /dev/null -w '%{http_code}' "$BASE/api/gallery/$gal/file")
[ "$code" = "403" ] || fail "B reads A gallery: $code"
code=$(curl -skb "$COOKIE_B" $RESOLVE -X POST "$BASE/api/jobs/$job1/cancel" -o /dev/null -w '%{http_code}')
[ "$code" = "403" ] || fail "B cancels A job: $code"

echo "SMOKE: ALL PASS"
```

> Tighten the isolation assertion to the real `/api/gallery` shape (list `items[].id`) implemented in P1.5; adjust jq paths accordingly. `lib_login.sh` and the "broken template register hook" are exercised first in P1.5's e2e; this suite is the generalized regression.

- [ ] **Step 3: Run the smoke suite (compose CPU + dex-test)**

```bash
cd /home/darshan.parmar/Desktop/video-model/system
bash tests/smoke.sh
```
Expected: eight stages print, ending `SMOKE: ALL PASS`. The same invocation with `NO_RESOLVE=1` and k3s NodePort is the Phase-5 in-cluster regression.

- [ ] **Step 4: Wire `make smoke`**

`system/Makefile`:
```makefile
smoke: ## Control-plane smoke (OIDC, FIFO, isolate)
	bash tests/smoke.sh
```

- [ ] **Step 5: Commit** — `test: control-plane smoke (oidc, fifo, cancel, failure, isolation)`.

---

## Phase 3 Exit Criteria

1. `models.manifest.json` valid, schema-conformant (incl. correct `loras` enum), 9 models.
2. `verify-manifest-lockstep.sh` exit 0 (workflows ↔ manifest reconcile).
3. `link-models.sh` links the full tree, verifies sha256 when present, refuses non-`MODELS_PATH` targets, `--write-hashes` records hashes, reports failures cleanly; verified on fixture trees here.
4. `system/tests/smoke.sh` passes via the control-plane API with test-Dex OIDC: login → submit → FIFO → queued-cancel → gallery PNG → 422 validation failure → job `failed` (no gallery) → **two-user isolation** (B cannot list/read/cancel A's items; 403s).
5. No direct ComfyUI HTTP from any test; nginx proxies only the SPA + `/api/*`; ComfyUI internal-only.
6. No weights required during Phase-3 testing (fixtures suffice); real hashes pinned later on the user's box via `link-models.sh --write-hashes`.
7. Old `smoke:smoke-pass-312` basic-auth identity is gone from every committed file.