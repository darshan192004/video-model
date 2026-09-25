# Spec: Self-Hosted Media Generation System (ComfyUI Core + Control-Plane SPA)

**Date:** 2026-09-25
**Status:** Approved for planning (revised: control-plane + SPA + OIDC + Postgres)
**Owner:** darshan.parmar
**Reference diagrams (already validated):** `diagrams/architecture-system.html`, `diagrams/workflow-user-tasks.html`, `diagrams/sequence-generate-job.html`, `diagrams/dataflow-pipeline.html`, `diagrams/lifecycle-generation-job.html`

## 1. Overview & Goals

Deliver a production-grade, reproducible system that packages:

- **ComfyUI** as the private generation engine (node graph, serial queue, `/prompt`, `/history`, `/view`, `/ws`) — **internal-only**, never exposed to end users.
- A **control-plane** (Python/FastAPI) that owns identity, the job queue, and the per-user gallery. It is the *only* component that talks to ComfyUI.
- A **custom SPA** (Nuxt/Vue 3, statically built) as the UI surface: full parameter control over the four locked workflows for all users; admins additionally see the raw workflow JSON and system architecture.
- **Authentication via OIDC** against the org's existing **Dex** (backed by FreeIPA LDAP). No username/password storage in this project; role (admin) derives from the FreeIPA member group surfaced in Dex's `groups` claim.
- **PostgreSQL** for all metadata (users, jobs, gallery index, sessions); generated media lives in a per-user gallery store on disk and is served only to its owner (admins may moderate).
- Four **locked generation workflows**: **Qwen-Image-2.1** for text-to-image + image editing, **Wan 2.2** for text-to-video + image-to-video.
- An **nginx** HTTPS reverse proxy (self-signed internal cert) that serves the SPA and proxies `/api` + `/ws` to the control-plane.
- A **model wiring path** for weights that already live on the user's infrastructure — **no runtime Hugging Face fetches**.

The system must run identically in two environments:

1. **Local (Docker Compose):** GPU mode on the RTX 3090 box (real weights); CPU mode on the dev box (no GPU, smoke-tested only).
2. **Kubernetes (k3s on the dev box as a test cluster; manifests written generically for the eventual production cluster):** same images, GPU achieved via NVIDIA device plugin + nodeSelector/toleration.

User goal (verbatim intent): "I just need to wire up the models on GPU with this system including UI… run on my system before deploying on k8s and wiring up." Revised intent: the UI must be a **custom SPA** with **per-user accounts (SSO via existing Dex/FreeIPA)** and **per-user isolated galleries**; the raw workflow JSON and system internals are visible only to **admins** (determined by a FreeIPA group via Dex).

> **Auth/branding note:** The project consumes the org's existing FreeIPA + Dex SSO. The SPA itself stands up none of the auth infrastructure — it reads an OIDC issuer URL, a client id/secret, and a redirect URI from config/secrets (Phase 1.5).

## 2. Scope / Non-Goals

### In scope
- Container images (ComfyUI, control-plane [with baked SPA build], postgres, nginx), compose files, kustomize manifests.
- Four locked workflows + one CPU smoke workflow, consumed server-side by the control-plane; a typed **param schema** per template (full parameter control in the SPA).
- Model layout manifest (`models.manifest.json`) + `link-models.sh`.
- Control-plane service: OIDC Relying Party, session management, Postgres-backed job queue (FIFO, single worker), ComfyUI client (submit/track/cancel), gallery copy + index, admin moderation + raw-workflow view.
- Nuxt SPA (SSG): template picker, full-param form, image upload, live job progress, per-user gallery (download/self-delete); admin system view.
- nginx (SPA host + `/api`/`/ws` proxy, TLS only), cert generation script, test-OIDC provider (Dex, static connector) for dev/k3s.
- Makefile, doctor/smoke scripts, per-phase end-to-end test scripts.
- Documentation (README for run/compose/k8s/wire-weights).

### Out of scope
- Custom ML engine or custom Python inference.
- Running our own FreeIPA or Dex (already exist in the org; consumed as an OIDC issuer).
- Model training.
- Public internet exposure (internal LAN only).
- Multi-GPU / horizontal scaling (single RTX 3090, serial queue).
- ComfyUI-Manager / custom node graph editing for end users; the ComfyUI UI (App Mode) is not the user surface.
- User self-service signup (accounts come from FreeIPA and are granted/provisioned there).

## 3. Fixed Decisions

| Decision | Choice |
|---|---|
| UI surface | **Custom Nuxt SPA (static build)** served via nginx; all generation parameters exposed to all users; ComfyUI UI/App Mode not user-facing |
| Admin view | FreeIPA group (via Dex `groups` claim) → role; admins see raw workflow JSON + system architecture; enforced server-side |
| Auth | **OIDC against existing Dex (FreeIPA LDAP)**; HttpOnly Secure session cookie issued by the control-plane; no local password store |
| Database | **PostgreSQL 16** (users, jobs, gallery index, sessions) |
| Queue | **Control-plane-owned FIFO**, single worker → ComfyUI `/prompt` (one job at a time) |
| Gallery | Control-plane copies outputs into `GALLERY_ROOT/<user>/<job-id>/` + Postgres index; owner-only read/download/delete; admin moderation |
| Reverse proxy | **nginx** (same image in compose + k8s — parity requirement) |
| TLS | Self-signed internal cert; optional internal CA documented |
| ComfyUI reachability | **Internal only** (never published to LAN; only the control-plane reaches it) |
| Runtime local | **Docker Compose:** `base.yml` + `compose.override.gpu.yml` (3090) + `compose.override.cpu.yml` (dev box smoke; includes test Dex) |
| Cluster | **k3s on dev box** for test (incl. test Dex in-cluster); artifacts generic for production cluster |
| Models | Live on user infra, mounted via `MODELS_PATH`; **no runtime HF download** |
| Workflows | We author + pin 4 (+ smoke), based on Comfy-Org official templates; control-plane injects params |
| Media storage | Per-user gallery store on a volume; metadata in Postgres |

## 4. Architecture

```
LAN user browser
      │  HTTPS :443 (self-signed internal cert, host SNI)
      ▼
nginx (unprivileged container) ── serves SPA static + proxies /api and /ws ── TLS only
      │  HTTP :8000 internal network (never published to LAN)
      ▼
control-plane :8000 (FastAPI) ── OIDC RP (existing Dex/FreeIPA) ── session cookie
      │  owns queue (Postgres) + gallery copy
      ├─▶ PostgreSQL :5432 (internal) — users/jobs/gallery/sessions
      │  HTTP :8188 internal network (control-plane is the ONLY client)
      ▼
ComfyUI :8188 (4 locked workflows; built-in serial queue)  ── NEVER published
      │
      ▼
RTX 3090 (24GB, CUDA) ── native Wan 2.2 (T2V/I2V) ── native Qwen-Image-2.1 (T2I/edit)
      │
      ▼
ComfyUI output/ dir → control-plane copies media+metadata into GALLERY_ROOT/<user>/<job-id>/
      │
      ▼
per-user gallery store (volume) + Postgres index; SPA lists own items via /api/gallery
```

The SPA is built (Nuxt SSG) into the control-plane image (multi-stage: node build → python runtime), so compose and k8s run an identical single control-plane container that both serves the UI and exposes `/api` + `/ws`. nginx simply terminates TLS and proxies everything to `controlplane:8000`.

Weights flow: `MODELS_PATH` (user's infra) → mounted → `scripts/link-models.sh` normalizes/symlinks into the ComfyUI `models/` tree → validated against `config/models.manifest.json`.

Test identity (dev/k3s only, never prod): a containerized **Dex** instance with a static-password connector (users `admin@test`, `user@test`) exercises the full OIDC flow on this machine. Production config points the same code at the org's Dex.

## 5. Components & Contracts

### 5.1 ComfyUI image (`system/comfyui/Dockerfile`) — engine core, internal-only
- Build from `Comfy-Org/ComfyUI` at a **pinned commit** (backend >= 0.37.0 for Qwen-Image-2.1) and **pinned frontend** (`--front-end-version` with `Comfy-Org/ComfyUI_frontend@v<tag>`). The web UI is *internal-only* (control-plane renders the user surface); frontend pin exists for reproducibility.
- Non-root runtime user; entrypoint reads env and forwards CLI args:
  - `COMFY_LISTEN` (default `0.0.0.0`)
  - `COMFY_PORT` (default `8188`)
  - `COMFY_MODE=cpu|gpu` (cpu → `--cpu`; gpu → default CUDA)
  - `COMFY_VRAM=auto|lowvram|gpu-only` passthrough (3090 documented: `lowvram` fallback if OOM)
  - `COMFY_EXTRA_ARGS` (e.g. `--cpu-vae`)
- Exposes `8188` **on the internal network only**; mounts `models`, `output`, `input`, `user`, `custom_nodes`.

### 5.2 Workflows + template schema (`system/workflows/` + `system/config/`)
Four **API-format** workflow JSONs based on Comfy-Org official templates, pinned and trimmed, loaded **server-side by the control-plane** (no App Mode config, no user-facing import). Plus `smoke.json` (CPU-safe). Each workflow ships with a **typed param schema** in `config/templates.schema.json` (field name, type, range/default/options, image-input flag) that the SPA renders and the control-plane validates + injects before `/prompt`. Full parameter control is surfaced to all users.

| Workflow | Backbone | Exposed inputs | Output | Pinned model files |
|---|---|---|---|---|
| `qwen-t2i.json` | Qwen-Image-2.1 T2I template | prompt, seed, steps, megapixel | image (PNG) | `qwen_image_2.1_int8_convrot.safetensors` + Qwen TE + Qwen VAE (Comfy-Org/Qwen-Image-2.1) |
| `qwen-edit.json` | Qwen-Image-2.1 edit template | prompt, upload image, seed, steps | image (matches input size) | same files |
| `wan-t2v-a14b.json` | Wan 2.2 14B T2V template | prompt, seed, steps, length, 480P | MP4 | `wan2.2_t2v_high_noise_14B_fp8_scaled` + `wan2.2_t2v_low_noise_14B_fp8_scaled` + `umt5_xxl_fp8_e4m3fn_scaled` + `wan_2.1_vae` |
| `wan-i2v-a14b.json` | Wan 2.2 14B I2V template | prompt, upload image, seed, steps, length | MP4 | `wan2.2_i2v_high_noise_14B_fp16` + `wan2.2_i2v_low_noise_14B_fp16` + same TE/VAE |
| `smoke.json` | tiny CPU workflow | (none needed) | image | none (CPU-safe) |

> **Caveat (verified):** Comfy-Org's I2V guide text says the sampler loads `…t2v_…fp8…`, but the download cards list **I2V FP16** files. We pin by the actual template's loader wiring and verify load on the 3090; adjust the manifest if the template differs.

Param schemas are authored alongside the workflows (Phase 2) and validated against the control-plane's `/api/templates` in Phase 3.

### 5.3 nginx (`system/nginx/`)
- `nginx.conf` (main) + `conf.d/default.conf`.
- Single `server` block, `listen 443 ssl`, server-name from `DOMAIN` env.
- **No basic auth.** Everything (SPA HTML/assets, `/api/*`, `/ws`) proxies to `http://controlplane:8000`.
- `/ws` location: `proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";`
- `proxy_read_timeout 3600s; proxy_buffering off;` (Wan 14B renders idle > 60s; progress must stream through the control-plane).
- No public exposure; LAN-only.

### 5.4 Model layout (`system/config/` + `system/scripts/`) — UNCHANGED
- `models.manifest.json` — entries `{ dir, filename, sha256, note }`.
- `link-models.sh` — takes `MODELS_PATH`, creates ComfyUI `models/` symlink tree, verifies hashes, exits non-zero with clear reporting; `--write-hashes [path]` records true sha256 on the user's box.
- `verify-manifest-lockstep.sh` — cross-checks workflow loader filename refs vs manifest.

### 5.5 Deploy artifacts
- Image set (compose + k8s parity):
  - `comfyui-media:0.1.0` — the engine (internal).
  - `controlplane-media:0.1.0` — multi-stage build: stage 1 `node:20` builds the Nuxt SPA (SSG) → stage 2 `python:3.12-slim` runs FastAPI + serves SPA statics + worker.
  - `nginx:1.27-alpine` — TLS + reverse proxy.
  - `postgres:16-alpine` — metadata store (pinned tag).
  - `ghcr.io/dexidp/dex:v2.4x` — **test-only** OIDC provider (static connector) for dev compose + k3s.
- `deploy/compose/base.yml` — services `nginx` + `controlplane` + `postgres` + `comfyui` (comfyui on an internal-only subnet), shared internal network, named volumes (`gallery-store`, `postgres-data`, `comfy-output/input/user`), nginx publishes host `443`.
- `deploy/compose/compose.override.gpu.yml` — GPU reservations (`gpus: all`), 3090 host paths.
- `deploy/compose/compose.override.cpu.yml` — `--cpu` mode, test Dex service, test-only paths.
- `deploy/k8s/base/` — kustomize base: namespace; Deployment+Service for comfyui (ClusterIP), controlplane (ClusterIP), nginx (NodePort in dev overlay / load-balanced in prod), postgres (Deployment+PVC); ConfigMaps (nginx conf, workflows, templates schema); Secrets (TLS, OIDC client creds, session secret, DB creds); PVCs.
- `deploy/k8s/overlays/k3s/` — dev overlay: local-path storage, CPU mode, NodePort 30443, test Dex Deployment.
- `deploy/k8s/overlays/production/` — GPU node shape (nvidia.com/gpu, nodeSelector/toleration), real image registry ref, ingress; validated structurally only.

### 5.6 Control-plane (`system/controlplane/`) — NEW
- Image `controlplane-media:0.1.0`; FastAPI app (`app/`) + worker process; serves SPA static build at `/`.
- OIDC RP (e.g. `authlib`): `/api/auth/start` → redirect to `DEX_OIDC_ISSUER`; callback exchanges code, stores **HttpOnly Secure SameSite=Lax** session cookie; `/api/auth/logout`, `/api/auth/me`.
- Role: from the `groups` claim → membership lists (case-insensitive DN/name match) in `ADMIN_GROUPS` (comma-separated env) → `is_admin` cached on the user row.
- API surface:
  - `/api/templates` — param schemas (from `config/templates.schema.json`).
  - `/api/jobs` POST/list/GET, `/api/jobs/{id}/cancel` — owner-scoped.
  - `/api/uploads` — multipart image upload for I2V/Edit (staged in an uploads dir, referenced by job).
  - `/api/gallery` GET (own index), `/api/gallery/{id}/file` (owner or admin), `/api/gallery/{id}` DELETE (owner self-delete or admin).
  - `/api/admin/*` — any user's gallery (index/delete), raw workflow JSON + architecture dump (admin only), job audit.
- Worker (single, FIFO): picks first `queued` job → builds ComfyUI API prompt from the raw workflow + validated params → `POST comfyui:8188/prompt` (unique `client_id`) → tracks `/ws` progress into the job row → on completion reads `/history/<prompt_id>` output filenames → **copies** media from ComfyUI `output/` into `GALLERY_ROOT/<user>/<job-id>/` and inserts `gallery_media` rows → status `done`. Failure → `failed` with `error`. Cancel → queued: drop row; running: ComfyUI `/queue` delete / WS `cancelled`.
- Postgres schema: `users`, `jobs`, `gallery_media`, `sessions`.

### 5.7 SPA (`system/spa/`) — NEW
- Nuxt 3 (Vue) statically generated; served by the control-plane (no separate runtime).
- Regular user surface: login redirect → template cards → full-param form (rendered from `/api/templates`) + optional image upload → submit → live progress via `/ws` → per-user gallery grid with download + delete.
- Admin surface: all of the above plus a **System view** (raw workflow JSON + architecture recap), gated by `/api/auth/me.is_admin` on every route and every admin API call.

### 5.8 Scripts / Makefile
- `scripts/gen-certs.sh` — self-signed cert for DOMAIN into `deploy/certs/` (gitignored).
- `scripts/doctor.sh` — checks docker, nvidia container toolkit (GPU mode), kubectl (k8s mode), ports free.
- `scripts/smoke.sh` — control-plane API roundtrip assertions (login → submit → queue → progress → gallery).
- `Makefile` targets: `doctor`, `build`, `dev-up` (cpu), `gpu-up`, `down`, `k3s-apply`, `smoke`, `clean`.

## 6. Data Flow (maps to sequence-generate-job.html)

1. Browser → nginx (TLS) → control-plane: unauthenticated request redirects to Dex `authorize` → user authenticates at FreeIPA → Dex returns code → control-plane `/api/auth/callback` exchanges it for a session cookie → SPA loads `/api/auth/me`.
2. SPA fetches `/api/templates` (param schemas) → user fills the form (+ optional image upload) → `POST /api/jobs` → row `queued` (owner = session user).
3. Single worker pops the FIFO head → injects params into the pinned workflow JSON → `POST comfyui:8188/prompt` (+ unique `client_id`) → job `running`; on completion reads `/history/<prompt_id>`.
4. ComfyUI (GPU: load Wan/Qwen → denoise/sample → VAE decode → save MP4/PNG to `output/`).
5. Worker watches `/ws` (progress persisted per job) and, on `executed`/`done`, **copies** output media + metadata into `GALLERY_ROOT/<user>/<job-id>/` and indexes Postgres → job `done`.
6. SPA polls `/api/jobs/{id}` (or live `/ws`) → gallery lists own `gallery_media` rows → `GET /api/gallery/{id}/file` streams media (owner or admin) → download; `DELETE` removes row + file (owner or admin).

## 7. Lifecycle / Error Handling (maps to lifecycle-generation-job.html)

- Job states (Postgres-owned): `queued → running → done | failed | cancelled`.
- Cancel: control-plane endpoint → queued: row dropped; running: ComfyUI `/queue` delete for pending / WS `cancelled` for running → job `cancelled`.
- Failures: model load failure / OOM surface as ComfyUI `execution_error` → worker marks `failed` with error text; user retries (creates a new job). `model-switch` = swap of pinned weight set (new manifest + rebuild of workflow wiring).
- Queue ordering: global FIFO across users (fairness is by submission order); each user sees only their own jobs.
- Gallery: owner-scoped reads/deletes; admin may delete any; no auto-expiry (kept until deleted).

## 8. Security, Reproducibility, Config, Secrets

- **Security:** internal-LAN only; `:8188` (ComfyUI) and `:8000` (control-plane) never published on the LAN in prod — nginx is the only listener. OIDC via org Dex/FreeIPA; no passwords stored. Role gating enforced server-side (admin-only routes + raw-workflow view). Per-user gallery authorization on every read/delete. Non-root containers (ComfyUI UID 1000, control-plane UID 1000, Postgres unprivileged). Session cookie: HttpOnly, Secure, SameSite=Lax, server-side sessions in Postgres. Secrets (OIDC client secret, session secret, DB password, TLS) as mounted Secret files/secrets, never in git. Symlink target constrained to `MODELS_PATH` root.
- **Reproducibility:** pinned ComfyUI commit + frontend tag; pinned workflow templates + param schemas; model manifest with sha256; pinned base images (`FROM …@sha256:`); single `make build && make smoke` path.
- **Config surface (env):**
  - ComfyUI: `COMFY_MODE`, `COMFY_LISTEN`, `COMFY_PORT`, `COMFY_VRAM`, `COMFY_EXTRA_ARGS`, `COMFY_MEMORY`, `MODELS_PATH`.
  - Overlay/nginx: `DOMAIN`, `HTTPS_PORT`.
  - Control-plane: `CONTROLPLANE_LISTEN`/`CONTROLPLANE_PORT` (default `0.0.0.0:8000`), `DEX_OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`, `ADMIN_GROUPS`, `SESSION_SECRET`, `COMFY_INTERNAL_URL` (default `http://comfyui:8188`), `DATABASE_URL` (default `postgresql://media:media@postgres:5432/media`), `GALLERY_ROOT` (default `/data/galleries`), `UPLOAD_ROOT` (default `/data/uploads`), `AUTO_MIGRATE` (default `1`).
  - Postgres: `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` (dev defaults; prod via Secret).

## 9. Testing & Verification Strategy

- **Liveness:** ComfyUI `/system_stats` responds; control-plane `/api/healthz` responds; image pins recorded.
- **Proxy/TLS:** TLS handshake → 200 on SPA HTML; `/ws` handshake → 101; long request not cut before 60s.
- **OIDC (test Dex, static connector):** `/api/auth/start` → 302 to issuer; callback → session cookie; `/api/auth/me` returns user; logout invalidates; group membership → `is_admin`.
- **Control-plane (unit/API, mock ComfyUI):** job lifecycle transitions, FIFO single-worker ordering, param schema validation, cancel path, gallery copy + index, owner/isolation + admin moderation, admin-only raw-workflow view.
- **SPA:** static build serves; login flow; form renders from `/api/templates`; job progress; gallery grid/download/delete; admin system view.
- **Smoke (CPU, dev box / k3s):** full roundtrip on `smoke.json` via the control-plane API; serial queue observed with 2 jobs (different users, FIFO); cancel; failure case returns error state; **two-user gallery isolation** asserted.
- **GPU (3090):** each of the 4 workflows at minimal settings produces saved output (via control-plane); `doctor.sh` clean; VRAM within 24GB.
- **k3s:** all workloads deployed with test Dex in-cluster; full login → submit → isolation flow passes in-cluster; secrets mounted.

## 10. Phases (one implementation plan per phase)

1. **P0 Repo scaffold + image build** — repo init, `system/` tree (incl. `controlplane/`, `spa/`, `postgres/`), Makefile, `doctor.sh`, ComfyUI Dockerfile (pinned), control-plane Dockerfile (multi-stage SPA→FastAPI) module skeleton, liveness tests.
2. **P1 Proxy, TLS, compose wiring (no auth)** — nginx config (proxy → control-plane, no basic auth), gen-certs, base compose skeleton with all four services, TLS + proxy assertions.
3. **P1.5 Control-plane + SPA + OIDC + Postgres** — FastAPI control-plane (OIDC RP, sessions, queue worker, ComfyUI client, gallery copy, admin moderation), Nuxt SPA, Postgres service, test Dex, full multi-user e2e on this machine.
4. **P2 Workflows + param schemas** — author 4 workflows + smoke.json, author `templates.schema.json`, server-side loading, schema validation.
5. **P3 Model layout + smoke on dev** — model manifest + link-models, CPU compose roundtrip through control-plane incl. cancel/failure/isolation tests.
6. **P4 GPU on 3090** — ship images (comfyui + controlplane + postgres + nginx), weight wiring, all 4 workflows end-to-end via SPA, VRAM profile.
7. **P5 Kubernetes** — kustomize base + k3s overlay (controlplane, postgres, test Dex, comfyui, nginx), GPU scheduling shape, in-cluster regression.
8. **P6 Hardening + docs** — license check (Qwen-Image-2.1), final README, security pass, final gate.

## 11. Assumptions & Open Items

- Repo lives under existing `video-model/` as `system/` (beside `diagrams/`). **Confirmed by user.**
- Dev box CPU smoke uses `smoke.json` only; real weights stay on the 3090 box. **Confirmed by user.**
- k3s = test cluster on dev box; production cluster differs but artifacts are cluster-agnostic. **Confirmed by user.**
- **FreeIPA + Dex already exist in the org** and are consumed via an OIDC issuer URL + client id/secret (no auth infra built here). **Confirmed by user.**
- **Admin identity** comes from a FreeIPA group surfaced by Dex's `groups` claim; mapping list configured via `ADMIN_GROUPS`. **Confirmed by user.**
- **UI is a separate SPA** (not built inside ComfyUI) because ComfyUI's own UI exposes the graph + global history/outputs, which violates the per-user gallery + hide-workflow requirements. **Confirmed by user.**
- **Full parameter control** is exposed to all users through the SPA (templates + all safe params); only the raw JSON/system internals are admin-only. **Confirmed by user.**
- License: Wan 2.2 Apache-2.0 (confirmed). **Qwen-Image-2.1 license to be verified before any commercial use** (flagged in P6).
- Self-signed internal cert + trust instructions; production may bring its own ingress/TLS — manifests keep it swappable.
- GPU box is SSH-only; `deploy/scripts` must be copy-and-run friendly (scp pattern documented).
- Control-plane, SPA, and Postgres are new code/first-party components of this repo and do not inherit ComfyUI's model licenses.

## 12. Acceptance Criteria (end of all phases)

1. Users log in via SSO (org Dex/FreeIPA; test Dex in dev); role (admin vs regular) is enforced server-side from the `groups` claim.
2. Regular users see only the SPA: all four templates with full parameter control; **no raw workflow JSON or architecture** visible.
3. Admin users have a System view exposing the raw workflow JSON + architecture, gated server-side.
4. Each user submits jobs through the single FIFO queue; progress streams live; cancel and failure states behave correctly; queue is global FIFO.
5. **Per-user galleries are isolated:** user A cannot list/download/delete user B's items; admins can moderate (view/delete) any.
6. Media generation happens on the 3090 box behind nginx (LAN): real weights produce saved MP4/PNG served from each user's gallery.
7. Identical stack deploys to k3s on a labeled `gpu=true` node; in-cluster multi-user smoke passes.
8. `MODELS_PATH` is the only model "wiring" the user performs.
9. `make build && make smoke` is green on the dev box (CPU).