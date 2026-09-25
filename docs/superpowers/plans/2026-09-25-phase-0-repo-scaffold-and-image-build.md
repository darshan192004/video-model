# Phase 0 — Repo Scaffold + ComfyUI Image Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize the git repo and the `system/` tree, then build a pinned, non-root ComfyUI Docker image and a **control-plane skeleton image** (multi-stage: Nuxt SPA → FastAPI) and prove both serve their liveness endpoints.

**Architecture:** Establish the repository skeleton (`system/comfyui|controlplane|spa|nginx|workflows|config|scripts|deploy|tests`), a Makefile with the standard target surface, an environment template, the pinned ComfyUI `Dockerfile` (non-root `entrypoint.sh` forwards env-driven CLI flags), and a minimal FastAPI control-plane scaffold baked together with a placeholder Nuxt static page (liveness only; full OIDC/queue/gallery logic lands in Phase 1.5). Liveness for both images is verified before any proxy/workflow work. Postgres is a pinned **stock image** (`postgres:16-alpine`) — no local Dockerfile.

**Tech Stack:** Docker, Docker Compose, GNU Make, Bash, Python (ComfyUI base + FastAPI control-plane), Node (Nuxt SPA build stage), Git.

**Spec:** `docs/superpowers/specs/2026-09-25-comfyui-app-mode-media-system-design.md` — Phase 0 implements §5.1, §5.5 (image set), §5.6 (control-plane image base), §5.7 (SPA build stage) , §5.8, §9 (liveness), §10 P0.

## Global Constraints

- Repo root: `/home/darshan.parmar/Desktop/video-model` (NOT a git repo yet; `git init` in Task 1).
- All new code under `system/`, diagrams untouched.
- ComfyUI backend commit: **pin to a merge ≥ `0.37.0`** for Qwen-Image-2.1 native support (verify at build time via VERSION/`comfy/cli_args.py`).
- ComfyUI frontend tag: **pin to `Comfy-Org/ComfyUI_frontend@` ≥ `v1.41.13`** (reproducibility; the UI is internal-only — the SPA is the user surface).
- Control-plane image `controlplane-media:0.1.0`: **multi-stage** — stage 1 `node:20-alpine` builds the Nuxt SPA (SSG placeholder in P0; real SPA in P1.5) → stage 2 `python:3.12-slim` runs FastAPI (UID 1000, non-root) serving the SPA statics + `/api/healthz`. Same image in compose and k8s.
- Postgres: stock pinned `postgres:16-alpine` (no local Dockerfile in this repo).
- Container runtime users must be **non-root**.
- Cluster/deploy parity: the images produced here are the **same images** later used by compose and kustomize.
- Env-driven config only: `COMFY_LISTEN`, `COMFY_PORT`, `COMFY_MODE`, `COMFY_VRAM`, plus `COMFY_EXTRA_ARGS` (Phase 4 adds the VAE-offload flag). Control-plane env (`DEX_OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`, `ADMIN_GROUPS`, `SESSION_SECRET`, `COMFY_INTERNAL_URL`, `DATABASE_URL`, `GALLERY_ROOT`, `UPLOAD_ROOT`) are declared in `.env.example` now and consumed in P1.5.
- `.env` and secrets/certs must never be committed (`.gitignore`).
- No emojis in code; no runtime Hugging Face downloads; no ComfyUI-Manager.
- **Test environment (this machine only):** development and testing happen entirely on this machine — **no GPU, no real weights, no 3090-box access** for the whole project (user confirmed). The ComfyUI image must build here (CUDA wheels install fine on a CPU-only host; they just won't be exercised) and pass CPU-mode liveness; the control-plane image must build and pass `/api/healthz`. Real CUDA handoff is verified only later, by the user, via the Phase 4 runbook — never asserted on this machine.

---

## File Structure (Phase 0 creates or prepares)

- `system/.gitignore` — ignores env, secrets, certs, model symlinks, build caches.
- `system/.env.example` — documented env template (ComfyUI + control-plane + OIDC + Postgres).
- `system/Makefile` — `doctor build dev-up gpu-up down smoke k3s-apply clean`.
- `system/comfyui/Dockerfile` — pinned ComfyUI image.
- `system/comfyui/entrypoint.sh` — env→args bridge.
- `system/comfyui/requirements-extra.txt` — empty placeholder (native nodes need nothing; kept for future pins).
- `system/controlplane/Dockerfile` — multi-stage control-plane image (Nuxt SPA → FastAPI).
- `system/controlplane/app/main.py` — minimal FastAPI app (liveness + static SPA mount placeholder).
- `system/spa/` — Nuxt SPA source (P0: placeholder `public/index.html`; full app in P1.5).
- `system/scripts/.keep` placeholder dir marker.
- `system/workflows/.keep`, `system/config/.keep`, `system/nginx/.keep`, `system/deploy/compose/.keep`, `system/deploy/k8s/.keep`, `system/tests/.keep` — dir markers.
- `system/scripts/doctor.sh` — environment/liveness validator.
- `system/tests/liveness.sh` — asserts ComfyUI image serves 8188 `/system_stats`.
- `system/tests/controlplane_liveness.sh` — asserts control-plane image serves `/api/healthz`.
- `docs/superpowers/plans/` — this and subsequent phase plans.

---

### Task 0.1: Initialize git repo and scaffold directory tree

**Files:**
- Create: `/home/darshan.parmar/Desktop/video-model/.gitignore`
- Create: `/home/darshan.parmar/Desktop/video-model/system/` plus the empty dirs listed above (via `.keep` markers)
- Create: `/home/darshan.parmar/Desktop/video-model/README.md` (one-line root pointer)

**Interfaces:**
- Produces: repo root with `system/` tree present and a `.gitignore` that later tasks rely on.

- [ ] **Step 1: Initialize git (run from repo root)**

The repo root is `/home/darshan.parmar/Desktop/video-model`. It is intentionally **not** a git repo yet (only `diagrams/` and `.playwright-mcp/` exist).

Run:
```bash
cd /home/darshan.parmar/Desktop/video-model
git init -b main
```
Expected: `Initialized empty Git repository in /home/darshan.parmar/Desktop/video-model/.git/`

- [ ] **Step 2: Write the root `.gitignore`**

Create `/home/darshan.parmar/Desktop/video-model/.gitignore`:

```gitignore
# env & secrets
.env
system/.env
system/deploy/secrets/
system/deploy/certs/
*.htpasswd
*.crt
*.key
*.csr

# model wiring (symlinks into user infra)
system/models/
system/link/

# python
__pycache__/
*.pyc
.venv/
venv/

# tooling
system/.doctor-cache/
*.log

# editor/os
.DS_Store
Thumbs.db
.idea/
.vscode/
```

- [ ] **Step 3: Create the `system/` directory tree**

Run:
```bash
cd /home/darshan.parmar/Desktop/video-model
mkdir -p system/comfyui system/controlplane/app system/spa/public system/spa/app \
  system/nginx/conf.d system/workflows system/config system/scripts \
  system/deploy/compose system/deploy/k8s/base system/deploy/k8s/overlays/k3s system/tests
touch system/scripts/.keep
touch system/workflows/.keep system/config/.keep system/nginx/conf.d/.keep
touch system/deploy/compose/.keep system/deploy/k8s/base/.keep system/deploy/k8s/overlays/k3s/.keep
touch system/controlplane/app/.keep system/spa/public/.keep system/spa/app/.keep system/tests/.keep
```
Expected: `ls system` prints `comfyui config controlplane deploy nginx scripts spa tests workflows`.

- [ ] **Step 4: Write root README.md**

Create `/home/darshan.parmar/Desktop/video-model/README.md`:

```markdown
# video-model

Self-hosted ComfyUI media generation system (Qwen-Image-2.1 + Wan 2.2) behind an nginx HTTPS
proxy, runnable via Docker Compose and deployable to Kubernetes.

- `diagrams/` — validated reference diagrams (architecture, workflow, sequence, dataflow, lifecycle).
- `system/` — the runnable system (images, workflows, config, deploy, scripts, tests).
- `docs/superpowers/specs/` — the system spec.
- `docs/superpowers/plans/` — per-phase implementation plans.

See `system/README.md` (added in Phase 6) for operator instructions.
```

- [ ] **Step 5: Verify tree + commit**

Run:
```bash
cd /home/darshan.parmar/Desktop/video-model
git add -A
git status --short
```
Expected: newly listed files under `system/`, `docs/`, `.gitignore`, `README.md`; `.playwright-mcp/` should **not** appear (it is not ignored — check; if it shows, add `.playwright-mcp/` to `.gitignore` and re-add).

Then commit:
```bash
git commit -m "chore: scaffold system tree and gitignore"
```

- [ ] **Step 6: Verify commit**

Run: `git log --oneline -1`
Expected: `chore: scaffold system tree and gitignore`

---

### Task 0.2: Write `.env.example` and the ComfyUI entrypoint

**Files:**
- Create: `system/.env.example`
- Create: `system/comfyui/entrypoint.sh`

**Interfaces:**
- Produces: `entrypoint.sh` contract used by the Dockerfile `CMD` and later by compose overrides.
- Env contract (exact names / defaults):
  - `COMFY_LISTEN` default `0.0.0.0`
  - `COMFY_PORT` default `8188`
  - `COMFY_MODE` default `gpu` (values: `gpu` | `cpu`)
  - `COMFY_VRAM` default empty (valid: empty/auto | `--lowvram` | `--gpu-only`)

- [ ] **Step 1: Write `system/.env.example`**

Create `system/.env.example`:

```bash
# --- ComfyUI service configuration ---
# COMFY_MODE=gpu runs CUDA; COMFY_MODE=cpu forces --cpu (dev box smoke only).
# Copy to system/.env and edit.
COMFY_MODE=gpu
COMFY_LISTEN=0.0.0.0
COMFY_PORT=8188
# Optional VRAM strategy: leave empty for auto, or set lowvram|gpu-only
COMFY_VRAM=lowvram
# Extra CLI flags forwarded verbatim (e.g. --cpu-vae for VAE on CPU RAM).
# Used by the GPU override on the 3090 box; empty on the dev box.
COMFY_EXTRA_ARGS=
# Absolute path on the host containing the user's model weights tree.
# link-models.sh (Phase 3) maps it into ComfyUI/models layout.
MODELS_PATH=/srv/media-weights
# nginx hostname / ServerName SNI used by gen-certs.sh (Phase 1).
DOMAIN=media.local
HTTPS_PORT=443

# --- Control-plane (FastAPI) ---
CONTROLPLANE_LISTEN=0.0.0.0
CONTROLPLANE_PORT=8000
# OIDC issuer from the org's existing Dex (FreeIPA-backed). In dev compose/k3s
# this points at the dev test Dex, reachable from BOTH the control-plane pod and
# the test host (P1.5 reachability contract); on the 3090 box it is the real org issuer.
DEX_OIDC_ISSUER=http://host.docker.internal:5556/dex
OIDC_CLIENT_ID=media-controlplane
OIDC_CLIENT_SECRET=
OIDC_REDIRECT_URI=https://media.local/api/auth/callback
# Comma-separated FreeIPA group names whose members are admins (via Dex 'groups' claim).
ADMIN_GROUPS=media-admins
SESSION_SECRET=
# ComfyUI is reachable only inside the internal network:
COMFY_INTERNAL_URL=http://comfyui:8188
DATABASE_URL=postgresql://media:media@postgres:5432/media
GALLERY_ROOT=/data/galleries
UPLOAD_ROOT=/data/uploads

# --- Postgres ---
POSTGRES_DB=media
POSTGRES_USER=media
POSTGRES_PASSWORD=media
```

- [ ] **Step 2: Write `system/comfyui/entrypoint.sh`**

Create `system/comfyui/entrypoint.sh`:

```bash
#!/usr/bin/env bash
# Entrypoint for the ComfyUI container.
# Bridges env vars to ComfyUI CLI flags; runs as non-root inside the image.
# COMFY_DRYRUN=1 prints the computed args and exits (used by unit tests
# on this machine where no GPU exists).
set -euo pipefail

LISTEN="${COMFY_LISTEN:-0.0.0.0}"
PORT="${COMFY_PORT:-8188}"
MODE="${COMFY_MODE:-gpu}"
VRAM="${COMFY_VRAM:-}"
EXTRA="${COMFY_EXTRA_ARGS:-}"

ARGS=(--listen "$LISTEN" --port "$PORT")

if [[ "$MODE" == "cpu" ]]; then
  ARGS+=(--cpu)
fi

case "$VRAM" in
  lowvram) ARGS+=(--lowvram) ;;
  gpu-only) ARGS+=(--gpu-only) ;;
  ""|auto) ;;   # let ComfyUI decide
  *)
    echo "ERROR: unknown COMFY_VRAM '$VRAM' (expected: empty|auto|lowvram|gpu-only)" >&2
    exit 1
    ;;
esac

if [[ -n "$EXTRA" ]]; then
  # Trusted operator-supplied extra flags (e.g. --cpu-vae); word-split on purpose.
  # shellcheck disable=SC2206
  ARGS+=($EXTRA)
fi

echo "[entrypoint] launching: python main.py ${ARGS[*]}" >&2

if [[ "${COMFY_DRYRUN:-0}" == "1" ]]; then
  echo "DRYRUN: ${ARGS[*]}"
  exit 0
fi

exec python main.py "${ARGS[@]}"
```

Make it executable:
```bash
chmod +x system/comfyui/entrypoint.sh
```

- [ ] **Step 3: Syntax-check the script**

Run: `bash -n system/comfyui/entrypoint.sh`
Expected: exit 0, no output.

- [ ] **Step 4: Commit**

```bash
git add system/.env.example system/comfyui/entrypoint.sh
git commit -m "feat: add env template and comfyui entrypoint arg bridge"
```

---

### Task 0.3: Write the pinned ComfyUI Dockerfile

**Files:**
- Create: `system/comfyui/Dockerfile`
- Create: `system/comfyui/requirements-extra.txt`
- Create: `system/comfyui/.dockerignore`

**Interfaces:**
- Consumes: `entrypoint.sh` (mounted/copied as service entrypoint).
- Produces: image `comfyui-media:0.1.0` that runs `python main.py` as a non-root user, exposing 8188.
- **Version pins (verify at build):** backend commit `RELEASE_PIN` must be a commit whose tree includes native Qwen-Image-2.1 support (merged in `Comfy-Org/ComfyUI#16400`, i.e. backend ≥ 0.37.0). Frontend pin `Comfy-Org/ComfyUI_frontend@v1.41.13` or newer.

- [ ] **Step 1: Write `system/comfyui/Dockerfile`**

Create `system/comfyui/Dockerfile`:

```dockerfile
# Syntax: docker/dockerfile:1.7
# Pinned, non-root ComfyUI server image used by both compose and k8s.

# Python 3.12 CUDA base. Keep this tag pinned for reproducibility.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# --- Versions (reproducibility contract) --------------------------------
# COMIFYUI *backend* revision: must include native Qwen-Image-2.1 support
#   (merged in Comfy-Org/ComfyUI#16400; backend >= 0.37.0).
# RELEASE_PIN is a full 40-char commit SHA on a released tag's lineage.
ENV COMFYUI_BACKEND_REV=19f2c0f0c9894e867aa68f4edd7f9b283f9bfe8a
# COMfyUI *frontend*: pinned for reproducibility only (the SPA is the user
# surface; ComfyUI's built-in UI is never served to users).
ENV COMFYUI_FRONTEND_TAG=v1.41.13

# --- System deps --------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
      git \
      libgl1 \
      libglib2.0-0 \
      libsm6 \
      libxext6 \
      libxrender1 \
      curl \
      && rm -rf /var/lib/apt/lists/*

# --- Non-root user -------------------------------------------------------
RUN useradd --create-home --uid 1000 --gid 100 comfy
WORKDIR /home/comfy

# --- Python deps ---------------------------------------------------------
COPY requirements-extra.txt /opt/requirements-extra.txt
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install \
         torch==2.4.1 \
         torchvision==0.19.1 \
         torchaudio==2.4.1 \
         --index-url https://download.pytorch.org/whl/cu124

# --- ComfyUI checkout (pinned) -------------------------------------------
RUN git clone https://github.com/Comfy-Org/ComfyUI.git /opt/ComfyUI \
    && cd /opt/ComfyUI \
    && git checkout "${COMFYUI_BACKEND_REV}" \
    && python3 -m pip install --no-cache-dir -r requirements.txt

RUN if [ -s /opt/requirements-extra.txt ]; then \
      python3 -m pip install --no-cache-dir -r /opt/requirements-extra.txt; \
    fi

# --- Frontend (pinned) ----------------------------------------------------
# The backend self-manages the frontend via --front-end-version when the
# web/ dir is absent; we install it explicitly so the version is auditable
# and reproducible without assuming the CLI's network fetch at boot.
ARG COMFYUI_FRONTEND_URL=\
https://github.com/Comfy-Org/ComfyUI_frontend/releases/download/${COMFYUI_FRONTEND_TAG}/dist.tar.gz
RUN curl -fsSL "${COMFYUI_FRONTEND_URL}" -o /tmp/frontend.tar.gz \
    && mkdir -p /opt/ComfyUI/web \
    && tar -xzf /tmp/frontend.tar.gz -C /opt/ComfyUI/web --strip-components=1 \
    && rm /tmp/frontend.tar.gz

# --- Layout & entrypoint --------------------------------------------------
RUN mkdir -p /opt/ComfyUI/models \
             /opt/ComfyUI/output \
             /opt/ComfyUI/input \
             /opt/ComfyUI/user \
             /opt/ComfyUI/custom_nodes \
    && chown -R 1000:100 /opt/ComfyUI

COPY --chown=1000:100 entrypoint.sh /usr/local/bin/comfy-entrypoint
RUN chmod +x /usr/local/bin/comfy-entrypoint

WORKDIR /opt/ComfyUI
USER 1000:100
EXPOSE 8188
ENTRYPOINT ["/usr/local/bin/comfy-entrypoint"]
```

> **Build-time note:** If `COMFYUI_BACKEND_REV` (the placeholder commit `19f2c0f0…`) does not exist or its tree lacks native Qwen-Image-2.1, resolve the current tip of the newest released tag at build time via:
> `git ls-remote https://github.com/Comfy-Org/ComfyUI.git <newest-tag>` and re-pin. Record the final SHA as a comment in the Dockerfile. Applies to frontend tag too — validate the tag exists under `Comfy-Org/ComfyUI_frontend/releases`.

- [ ] **Step 2: Write `system/comfyui/requirements-extra.txt`**

Create `system/comfyui/requirements-extra.txt` (empty — native Wan/Qwen nodes require nothing extra; kept as the pin surface for future needs):
```text
# Extra Python dependencies for ComfyUI custom nodes, pinned as needed.
```

- [ ] **Step 3: Write `system/comfyui/.dockerignore`**

Create `system/comfyui/.dockerignore`:

```dockerignore
.env
*.md
.git
.gitignore
```

- [ ] **Step 4: Build the image and verify pure-syntax compliance**

Run:
```bash
cd /home/darshan.parmar/Desktop/video-model/system
docker build -t comfyui-media:0.1.0 ./comfyui
```
Expected: exit 0; final line `Successfully tagged comfyui-media:0.1.0`.

> If the pin SHAs are stale, follow the note in Step 1 to re-resolve, update the `ENV` lines, rebuild. Do not proceed with a build you have to wiggle at runtime.

- [ ] **Step 5: Record build metadata**

Run:
```bash
docker images comfyui-media
```
Expected: row with tag `0.1.0`. Note the IMAGE ID for the liveness test in the next task.

- [ ] **Step 6: Commit**

```bash
git add system/comfyui
git commit -m "feat: pinned non-root comfyui server image"
```

Revert nothing; `entrypoint.sh` was committed in Task 0.2, so it will already be in the index — the commit message here covers the whole image package.

---

### Task 0.4: `doctor.sh` environment validator

**Files:**
- Create: `system/scripts/doctor.sh`

**Interfaces:**
- Consumes: env vars `COMFY_MODE`, `MODELS_PATH`, `DOMAIN`, `HTTPS_PORT`.
- Produces: `doctor.sh` invoked by `make doctor`, later extended by Phase 4 (nvidia-smi) and Phase 5 (kubectl).
- Exit codes: `0` all green; `1` any check failed (aggregates).

- [ ] **Step 1: Write `system/scripts/doctor.sh`**

Create `system/scripts/doctor.sh`:

```bash
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
```

Make it executable:
```bash
chmod +x system/scripts/doctor.sh
```

- [ ] **Step 2: Syntax-check and walk smoke run**

Run:
```bash
bash -n system/scripts/doctor.sh
```
Expected: exit 0.

Run:
```bash
COMFY_MODE=cpu MODELS_PATH=/tmp bash system/scripts/doctor.sh
```
Expected: `[ok]` rows and exit 0 (ports 443/8188 are free on the dev box). If port 8188 is occupied by a leftover server, note it — do not kill unknown processes; report instead.

- [ ] **Step 3: Commit**

```bash
git add system/scripts/doctor.sh
git commit -m "feat: add doctor preflight validator"
```

---

### Task 0.5: Config surface + serial queue explanation docs (small)

**Files:**
- Create: `system/config/README.md`

**Interfaces:**
- Produces: single source of truth describing the `models/` layout the later Phases 2–4 mount into, matching ComfyUI's expected dirs.

- [ ] **Step 1: Write `system/config/README.md`**

Create `system/config/README.md`:

```markdown
# Config surface

This directory holds machine- and operator-facing configuration:

- `models.manifest.json` — Phase 3: expected weight files + sha256 + target dir.
- `README.md` — this file.

## Env vars consumed by the system

| Var | Default | Meaning |
|---|---|---|
| `COMFY_MODE` | `gpu` | `gpu` = CUDA, `cpu` = `--cpu` (dev smoke only) |
| `COMFY_LISTEN` | `0.0.0.0` | bind addr |
| `COMFY_PORT` | `8188` | listen port |
| `COMFY_VRAM` | (auto) | empty/auto, `lowvram`, `gpu-only` |
| `COMFY_EXTRA_ARGS` | (empty) | extra CLI flags verbatim (e.g. `--cpu-vae`) |
| `MODELS_PATH` | — | host path to the user's weight tree (required) |
| `DOMAIN` | `media.local` | SNI/ServerName for nginx + certs |
| `HTTPS_PORT` | `443` | host publish port |
| `DEX_OIDC_ISSUER` | (dev: test Dex) | OIDC issuer (org Dex in prod; test Dex in dev/k3s) |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | (empty) | control-plane's OIDC client creds (secret) |
| `OIDC_REDIRECT_URI` | — | callback URL (must match Dex registration) |
| `ADMIN_GROUPS` | `media-admins` | comma-separated FreeIPA group names → admin role |
| `SESSION_SECRET` | (empty) | session signing secret (secret) |
| `COMFY_INTERNAL_URL` | `http://comfyui:8188` | internal ComfyUI base URL (never published) |
| `DATABASE_URL` | `postgresql://media:media@postgres:5432/media` | Postgres DSN (control-plane) |
| `GALLERY_ROOT` | `/data/galleries` | per-user gallery store volume root |
| `UPLOAD_ROOT` | `/data/uploads` | staged uploads dir (I2V/Edit inputs) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `media/media/media` | Postgres bootstrap creds (secret in prod) |


## ComfyUI model directories this system mounts

ComfyUI resolves model file loaders against these default dirs (all under
`/opt/ComfyUI/models` inside the container):

- `diffusion_models/` — UNET/DiT backbones (Wan high/low noise, Qwen ConvRot).
- `text_encoders/` — CLIP/LLM text encoders (umt5_xxl_fp8 scaled, Qwen TE).
- `vae/` — VAE weights (wan_2.1_vae, Qwen VAE).
- `checkpoints/` — full checkpoints (unused by our pinned workflows).
- `loras/`, `clip/`, `controlnet/`, `embeddings/` — not required by pinned workflows.

The container mounts `$MODELS_PATH` (host) at `/opt/ComfyUI/models` (container);
`link-models.sh` (Phase 3) guarantees the on-disk layout matches the manifest.
```

- [ ] **Step 2: Commit**

```bash
git add system/config/README.md
git commit -m "docs: config surface and models layout contract"
```

---

### Task 0.6: Image liveness test script

**Files:**
- Create: `system/tests/liveness.sh`

**Interfaces:**
- Consumes: built image `comfyui-media:0.1.0`.
- Produces: exit 0 when the CPU-mode container answers `/system_stats` with HTTP 200 and JSON containing `"system": "ComfyUI"`.

- [ ] **Step 1: Write `system/tests/liveness.sh`**

Create `system/tests/liveness.sh`:

```bash
#!/usr/bin/env bash
# Liveness/probe for the ComfyUI image: start in CPU mode, wait for /system_stats.
set -euo pipefail

IMAGE="${1:-comfyui-media:0.1.0}"
NAME="liveness-test-$RANDOM"
PORT=18188

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -p "${PORT}:8188" \
  -e COMFY_MODE=cpu \
  "$IMAGE"

# Wait up to 120s for readiness.
for i in $(seq 1 120); do
  if code=$(curl -s -o /tmp/stats_body.$$ -w '%{http_code}' "http://127.0.0.1:${PORT}/system_stats" \
      2>/dev/null) && [ "$code" = "200" ]; then
    echo "liveness: HTTP 200 after ${i}s"
    cat /tmp/stats_body.$$
    rm -f /tmp/stats_body.$$
    exit 0
  fi
  sleep 1
done

echo "liveness: FAILED - /system_stats not 200 within 120s"
docker logs "$NAME" 2>&1 | tail -40 || true
rm -f /tmp/stats_body.$$
exit 1
```

Make it executable:
```bash
chmod +x system/tests/liveness.sh
```

- [ ] **Step 2: Run the liveness test**

Run:
```bash
bash system/tests/liveness.sh comfyui-media:0.1.0
```
Expected: `liveness: HTTP 200 after Ns` and a JSON body containing `"system":"ComfyUI"`. Wait time may approach 120s on first CPU boot (torch import).

- [ ] **Step 3: Entrypoint DRYRUN flag-mapping test (no GPU needed)**

These assertions prove the env→args contract on this machine without ever booting CUDA. Run each:

```bash
docker run --rm -e COMFY_DRYRUN=1 -e COMFY_MODE=cpu comfyui-media:0.1.0
# expect: DRYRUN: --listen 0.0.0.0 --port 8188 --cpu

docker run --rm -e COMFY_DRYRUN=1 -e COMFY_MODE=gpu -e COMFY_VRAM=lowvram comfyui-media:0.1.0
# expect: DRYRUN: --listen 0.0.0.0 --port 8188 --lowvram

docker run --rm -e COMFY_DRYRUN=1 -e COMFY_MODE=gpu -e COMFY_EXTRA_ARGS=--cpu-vae comfyui-media:0.1.0
# expect: DRYRUN: --listen 0.0.0.0 --port 8188 --cpu-vae
```
All three expected lines must match exactly. Hint: `docker run --rm -e COMFY_DRYRUN=1 -e COMFY_MODE=gpu comfyui-media:0.1.0` is the base line (no `--cpu`, no vram flag).

- [ ] **Step 4: Negative probe (sanitization)**

Run:
```bash
bash -n system/tests/liveness.sh && echo OK
```
Expected: `OK`.

- [ ] **Step 5: Wire `make doctor` and `make build` into the Makefile**

Create `system/Makefile`:

```makefile
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help
.PHONY: help doctor build dev-up gpu-up down smoke k3s-apply clean

COMPOSE_BASE := deploy/compose/base.yml

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

doctor: ## Run preflight checks
	scripts/doctor.sh

build: ## Build the ComfyUI image
	docker build -t comfyui-media:0.1.0 ./comfyui

dev-up: ## Start CPU-mode stack (dev box, smoke only)
	COMFY_MODE=cpu docker compose -f $(COMPOSE_BASE) -f deploy/compose/compose.override.cpu.yml up -d --build

gpu-up: ## Start GPU-mode stack (RTX 3090)
	docker compose -f $(COMPOSE_BASE) -f deploy/compose/compose.override.gpu.yml up -d --build

down: ## Stop compose stack
	docker compose -f $(COMPOSE_BASE) down

smoke: ## Run the API roundtrip smoke test
	bash tests/smoke.sh

k3s-apply: ## Apply k8s manifests (overlay k3s)
	kubectl apply -k deploy/k8s/overlays/k3s

clean: ## Remove built image and test artifacts
	docker rm -f liveness-test-* 2>/dev/null || true
	docker image rm comfyui-media:0.1.0 2>/dev/null || true
```

> Note: `dev-up`/`gpu-up`/`smoke`/`k3s-apply` reference files from later phases; they are placeholder-resolvable now because the targets fail fast with a clear compose/kubectl error until Phases 1/3/5 land. This is intentional — the Make target surface is defined here once.

- [ ] **Step 6: Verify `make build` and `make doctor`**

Run:
```bash
cd system && make build && COMFY_MODE=cpu MODELS_PATH=/tmp make doctor
```
Expected: build is a no-op re-tag (cached), doctor prints all `[ok]` and exits 0.

- [ ] **Step 7: Commit**

```bash
git add system/Makefile system/tests/liveness.sh
git commit -m "feat: makefile surface and image liveness test"
```

---

### Task 0.7: Control-plane skeleton image (multi-stage SPA → FastAPI)

**Files:**
- Create: `system/controlplane/Dockerfile`
- Create: `system/controlplane/app/main.py`
- Create: `system/spa/public/index.html` (placeholder; real Nuxt app lands in P1.5)
- Create: `system/controlplane/requirements.txt`
- Create: `system/tests/controlplane_liveness.sh`

**Interfaces:**
- Consumes: env `CONTROLPLANE_LISTEN`/`CONTROLPLANE_PORT` (defaults `0.0.0.0:8000`).
- Produces: image `controlplane-media:0.1.0` running FastAPI (UID 1000, non-root) that serves
  `/api/healthz` → `200 {"status":"ok"}` and the SPA static build at `/`.

- [ ] **Step 1: Write the Nuxt placeholder page and requirements**

Create `system/spa/public/index.html`:
```html
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Media System</title></head>
<body><main><h1>Media System</h1><p>Control-plane UI (SPA lands in Phase 1.5).</p></main></body></html>
```

Create `system/controlplane/requirements.txt` (pinned; FastAPI version chosen at build time, then locked):
```text
# Control-plane API. Add authlib, uvicorn, etc. in Phase 1.5.
fastapi
uvicorn[standard]
```

- [ ] **Step 2: Write the minimal FastAPI app**

Create `system/controlplane/app/main.py`:
```python
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="media-controlplane")
STATIC = Path(os.environ.get("SPA_STATIC", "/opt/media/spa"))


@app.get("/api/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
```

> The static dir default `/opt/media/spa` is populated by the Dockerfile build stage.

- [ ] **Step 3: Write the multi-stage Dockerfile**

Create `system/controlplane/Dockerfile`:
```dockerfile
# Syntax: docker/dockerfile:1.7
# Control-plane image: Nuxt SPA (SSG) baked into a FastAPI runtime.
# P0 ships a placeholder static index; the full Nuxt build replaces it in Phase 1.5.

# --- Stage 1: build the SPA static output (placeholder in P0) ---
FROM node:20-alpine AS spa-build
WORKDIR /app/spa
COPY spa/ ./          # real Nuxt source arrives in P1.5
RUN mkdir -p /out && cp -r public/. /out/ 2>/dev/null || cp public/index.html /out/

# --- Stage 2: Python runtime ---
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 1000 --gid 100 control
COPY controlplane/requirements.txt /opt/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /opt/requirements.txt
WORKDIR /opt/media
COPY --from=spa-build /out /opt/media/spa
COPY controlplane/app/ /opt/media/app/
RUN chown -R 1000:100 /opt/media
USER 1000:100
EXPOSE 8000
ENV CONTROLPLANE_LISTEN=0.0.0.0 CONTROLPLANE_PORT=8000 SPA_STATIC=/opt/media/spa
CMD ["sh", "-c", "cd /opt/media && uvicorn app.main:app --host ${CONTROLPLANE_LISTEN} --port ${CONTROLPLANE_PORT}"]
```

- [ ] **Step 4: Write `system/controlplane/.dockerignore`**

```dockerignore
.env
.git
.venv
__pycache__
*.pyc
```

- [ ] **Step 5: Build the image and verify**

Run:
```bash
cd /home/darshan.parmar/Desktop/video-model/system
docker build -t controlplane-media:0.1.0 ./controlplane
docker run --rm -d --name cp-live -p 18000:8000 controlplane-media:0.1.0
for i in $(seq 1 30); do sleep 1; code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/api/healthz 2>/dev/null || true); [ "$code" = "200" ] && break; done
curl -s http://127.0.0.1:18000/api/healthz        # expect {"status":"ok"}
curl -s http://127.0.0.1:18000/ | grep -q "Media System"   # SPA HTML served
docker exec cp-live id | grep -q uid=1000        # non-root
docker rm -f cp-live >/dev/null
```

- [ ] **Step 6: Write `system/tests/controlplane_liveness.sh`**

Same shape as `liveness.sh` (start on a random free port, poll `/api/healthz`, exit 0 on 200). Make executable.

- [ ] **Step 7: Wire `make build` for both images + commit**

Extend the Makefile `build` target:
```makefile
build: ## Build the ComfyUI + control-plane images
	docker build -t comfyui-media:0.1.0 ./comfyui
	docker build -t controlplane-media:0.1.0 ./controlplane
```
Commit:
```bash
git add system/controlplane system/spa system/Makefile system/tests/controlplane_liveness.sh
git commit -m "feat: control-plane skeleton image (SPA + FastAPI)"
```

---

## Phase 0 Exit Criteria

1. `git log` shows clean scaffold + image commits on `main`.
2. `docker build -t comfyui-media:0.1.0 ./comfyui` succeeds from scratch (not cache).
3. `bash system/tests/liveness.sh` exits 0 with HTTP 200 on `/system_stats` (CPU mode).
4. Entrypoint DRYRUN mappings (cpu/gpu-lowvram/extra-args) all match exactly.
5. `COMFY_MODE=cpu MODELS_PATH=/tmp make doctor` exits 0.
6. Image runs as UID 1000 (verify optional: `docker run --rm --entrypoint id comfyui-media:0.1.0` → `uid=1000(comfy)`).
7. `controlplane-media:0.1.0` builds; `/api/healthz` → 200 and `/` serves the placeholder SPA HTML; container runs as UID 1000.
8. `.env.example` declares the full env surface (ComfyUI + control-plane + OIDC + Postgres) from spec §8.
9. No `.env`, secrets, or certs are present in git (`git status --ignored` shows them ignored).