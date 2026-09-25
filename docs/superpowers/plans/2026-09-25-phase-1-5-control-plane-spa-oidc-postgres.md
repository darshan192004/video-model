# Phase 1.5 — Control-Plane, SPA, OIDC, and Postgres Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the real user-facing surface: a **FastAPI control-plane** that owns authentication (OIDC against the org's existing Dex/FreeIPA), a **control-plane-owned FIFO job queue** driving ComfyUI, **per-user isolated galleries**, **PostgreSQL metadata storage**, and a **Nuxt (Vue 3) static SPA** served by the control-plane container. Everything runs through nginx (Phase 1 output) and is testable on this machine via a disposable **test Dex** (static connector). ComfyUI remains an **internal-only** backend: the control-plane is its sole client; its own web UI is never exposed.

**Architecture:** Browser → nginx:443 (TLS, Phase 1) → control-plane:8000 → { Postgres:5432 (metadata) | ComfyUI:8188 (internal) }. Auth is code-flow OIDC via authlib: `/api/auth/start` 302s to the (test or org) Dex issuer; `/api/auth/callback` exchanges the code, stores claims in a server-side session keyed by a signed HttpOnly cookie; roles derive from the Dex `groups` claim vs `ADMIN_GROUPS`. Jobs POST to `/api/jobs` (validated against per-template param schema) and are enqueued FIFO; a single asyncio worker pops jobs, POSTs the resolved workflow `client_id` to `comfyui:8188/prompt`, streams `@127.0.0.1:8188/ws/{client_id}` progress, then copies produced media (images/videos) plus a JSON metadata sidecar into `GALLERY_ROOT/<user>/<job-id>/` and records the row. Uploads (I2V/Edit input frames) land under `UPLOAD_ROOT/<user>/`; gallery files are owner-read/download/delete; admins additionally get moderation delete + a raw-workflow/system view. The Nuxt SPA is built with `nuxt generate` inside the control-plane's multi-stage image (P0) and served from `/opt/media/spa`.

**Tech Stack:** Python 3.12 + FastAPI + uvicorn; authlib (OIDC RP); SQLAlchemy 2 (async) + psycopg3; PostgreSQL 16 (`postgres:16-alpine`); httpx (ComfyUI client); Node 20 + Nuxt 3 (SPA, SSG output); test Dex `ghcr.io/dexidp/dex` (static connector); Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-25-comfyui-app-mode-media-system-design.md` — Phase 1.5 implements §5.6 (control-plane), §5.7 (SPA), §5.8 (Postgres), §6 (data flow), §7 (job lifecycle), §8 (security/config), §9 (testing), §10 P1.5.

## Global Constraints

- **No auth infrastructure we own in prod:** the org's existing Dex (FreeIPA-backed) is the issuer. The **test Dex** (static connector) exists only for dev/k3s e2e on this machine. Prod `.env` points `DEX_OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` at the real org registration.
- ComfyUI is reachable **only** from the control-plane on the internal network. No port publication, no nginx route to `comfyui/*` server internals.
- All users get **full parameter control** (all model params) via the SPA; only admins see raw workflow JSON and system internals (`/api/admin/*`).
- Sessions: server-side store in Postgres; HttpOnly + Secure + SameSite=Lax cookie; `SESSION_SECRET` signs the cookie. Never expose tokens to the SPA bundle.
- `groups` claim from Dex is the role source; membership check against `ADMIN_GROUPS` (comma-separated) is server-side only.
- FIFO queue owned by the control-plane (single worker); one job at a time. No in-memory queue that survives restart — the `jobs` table is the source of truth.
- Gallery copy is authoritative: control-plane copies `ComfyUI/output/<run>/…` into `GALLERY_ROOT/<user>/<job-id>/` (+ `metadata.json`). ComfyUI output volume is a scratch workspace the control-plane can read via shared named volume.
- All dates/filenames in gallery use the job id; no user-supplied paths ever reach the filesystem verbatim (ID/path sanitization enforced).
- Secrets in env only (`OIDC_CLIENT_SECRET`, `SESSION_SECRET`, `POSTGRES_PASSWORD`) — never in code or committed files; commit only `.env.example` placeholders.
- **Test environment (this machine only):** no GPU, no real weights. The ComfyUI "backend" during e2e is a **mock** (P0 liveness container in CPU mode responds to `/prompt`/`/history` with synthetic output) OR the real ComfyUI CPU container once Phase 2/3 land; the control-plane must not assume GPU. Real-Wan assertions in the e2e are limited to FIFO/basics; the 4 model workflows are validated against ComfyUI `/object_info` in P2.
- Identical images and env contract between compose and k8s (P5 reuses these manifests/values).

## File Structure (Phase 1.5 creates)

```
system/controlplane/
  Dockerfile                     (updated: SPA build stage copies real Nuxt output)
  requirements.txt               (+, authlib, sqlalchemy[asyncio], psycopg, httpx)
  app/
    main.py                      (FastAPI app factory, mounts routers + SPA static)
    settings.py                  (pydantic-settings from env; single source of truth)
    db.py                        (async engine, session dependency, schema.up())
    models.py                    (SQLAlchemy: users, jobs, gallery_media, sessions)
    oidc.py                      (authlib OIDC RP + session cookie helpers)
    deps.py                      (require_user, require_admin, gallery owner guard)
    routers/__init__.py
    routers/auth.py              (/api/auth/start|callback|logout|me)
    routers/templates.py         (/api/templates, /api/templates/{id}/schema)
    routers/uploads.py           (/api/uploads/pre, /api/uploads/{user}/files)
    routers/jobs.py              (/api/jobs POST/GET/{id}/cancel)
    routers/gallery.py           (/api/gallery list|file|delete)
    routers/admin.py             (/api/admin/* moderation + system view)
    comfy.py                     (httpx client: /prompt, /history, ws ticker)
    worker.py                    (single FIFO worker loop)
    gallery.py                   (copy + metadata sidecar + name sanitizer)
system/spa/
  package.json, nuxt.config.ts, tsconfig.json
  app/app.vue                    (login gate, nav: Templates|Jobs|Gallery, admin badge)
  app/pages/login.vue, templates/index.vue, jobs/index.vue, gallery/index.vue, admin.vue
  app/composables/api.ts         (fetch wrapper incl. credentials; error handling)
  app/stores/auth.ts
  public/                        (static)
system/deploy/compose/
  base.yml                       (controlplane/postgres/nginx/comfyui; P1 adds services now wired)
  compose.override.dex-test.yml  (test Dex service + config; dev/k3s only)
system/deploy/dex/               (test Dex config.yaml + entrypoint; k8s ConfigMap source)
system/tests/
  controlplane_unit.sh           (unit + API tests with mocked ComfyUI / in-process Postgres)
  e2e_spa.sh                     (full OIDC e2e against compose on this machine)
```

## Task 1.5.1: Postgres service + schema

- [ ] **Step 1: Postgres compose wiring**

`base.yml` already declares `postgres:16-alpine` (Phase 1). Verify healthcheck passes under the compose net. No Postgres code in the repo beyond the schema (see Step 2) — the image is stock.

- [ ] **Step 2: Write the schema `system/controlplane/app/models.py` (+ `schema.sql` reference)**

Tables (SQLAlchemy 2 declarative, async):
- `users` — `id` (PK), `subject` (Dex `sub`, unique), `name`, `email`, `groups` (JSONB), `is_admin` (bool, derived server-side), `created_at`.
- `jobs` — `id` (UUID PK, also the gallery dir name), `owner_id` → users, `template_id` (FK to template name/version), `params` (JSONB), `status` (`queued|running|success|failed|cancelled`), `client_id`, `counts` (progress snapshot JSONB), `error` (text), `created_at`, `started_at`, `finished_at`. `status` + `created_at` indexed for FIFO.
- `gallery_media` — `id` (PK), `job_id` → jobs, `user_id` → users (indexed), `kind` (`image|video`), `filename`, `size_bytes`, `content_type`, `sha256`, `created_at`. Unique `(job_id, filename)`.
- `sessions` — `id` (PK/sid), `user_id` → users, `csrf_token`, `expires_at`, `created_at` (server-side session store).

- [ ] **Step 3: Idempotent schema creation on boot**

`db.schema_up()` runs `CREATE TABLE IF NOT EXISTS …` (or a `alembic`-free DDL script) at control-plane startup when `AUTO_MIGRATE=1` (default in dev/compose; k8s sets it too). Postgres must be ready first: compose `depends_on: postgres: condition: service_healthy`, and the control-plane retries `DATABASE_URL` connection for up to 60s.

- [ ] **Step 4: Commit**

```bash
git add system/controlplane/app system/deploy/compose/base.yml system/.env.example
git commit -m "feat: postgres schema for users/jobs/gallery/sessions"
```

## Task 1.5.2: Control-plane settings + liveness

- [ ] **Step 1: `settings.py`**

pydantic-settings `Settings` reading every control-plane var from env with the spec §8 defaults: `CONTROLPLANE_LISTEN`/`PORT` (default `0.0.0.0:8000`), `DEX_OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`, `ADMIN_GROUPS` → `set[str]`, `SESSION_SECRET`, `COMFY_INTERNAL_URL` (default `http://comfyui:8188`), `DATABASE_URL` (default `postgresql://media:media@postgres:5432/media`), `GALLERY_ROOT` (default `/data/galleries`), `UPLOAD_ROOT` (default `/data/uploads`), `AUTO_MIGRATE`, `DEFAULT_ADMIN_GROUPS`. Reject-on-missing only for the OIDC prod trio when `OIDC_MOCK=0` (mock mode used by unit tests only).

- [ ] **Step 2: `/api/healthz` (from P0) extended**

Add async DB ping: returns `{"status":"ok","db":"up"}` when Postgres reachable else still `200 {"status":"ok","db":"down"}` (liveness ≠ readiness; do NOT block compose health). Keep `/` serving `SPA_STATIC/index.html`.

- [ ] **Step 3: Requirements + lockfile**

Extend `system/controlplane/requirements.txt`: `fastapi`, `uvicorn[standard]`, `authlib`, `sqlalchemy[asyncio]`, `psycopg[binary]`, `pydantic-settings`, `httpx`, `itsdangerous`. Freeze exact versions after install (`pip freeze` snapshot committed as `requirements.lock.txt`).

- [ ] **Step 4: Commit** — message `feat: controlplane settings, db ping, locked deps`.

## Task 1.5.3: OIDC RP + server-side sessions

- [ ] **Step 1: `oidc.py`**

authlib `OAuth` with provider `dex` from `DEX_OIDC_ISSUER`, `client_id`, `client_secret`; discovery off the issuer (`/.well-known/openid-configuration`). Grant type `authorization_code`, PKCE forced, code+nonce.

- [ ] **Step 2: Routers `auth.py`**

- `GET /api/auth/start` → 302 to issuer authz URL (state+nonce in the session store), `redirect_uri=OIDC_REDIRECT_URI`.
- `GET /api/auth/callback` → code exchange; `sub`/`name`/`email`/`groups`; upsert `users` row; compute `is_admin` from `groups ∩ ADMIN_GROUPS`; mint session; `Set-Cookie: media_sid=<signed sid>; HttpOnly; Secure; SameSite=Lax; Path=/`; 302 → `/`.
- `POST /api/auth/logout` → destroy session row + clear cookie.
- `GET /api/auth/me` → `{name, email, is_admin, groups}` or 401.
- CSRF: reducer cookie `media_csrf` (double-submit) on stateful form POSTs (jobs, uploads).

- [ ] **Step 3: Session + auth deps**

`deps.py`: `require_user` (reads signed cookie → session row → user), `require_admin` (user.is_admin). Every `/api/*` route except `auth/*`, `healthz`, and SPA statics requires a session; unauthenticated `/api` returns 401 JSON (never redirect loop for fetchers).

- [ ] **Step 4: Unit tests**

`controlplane_unit.sh`: with `OIDC_MOCK=1` and in-process SQLite/Postgres, assert: unauthenticated `/api/jobs` → 401; login flow sets cookie; admin flag flips with `ADMIN_GROUPS`; `/api/auth/me` roundtrip; logout invalidates.

- [ ] **Step 5: Commit** — `feat: oidc rp with server-side sessions and role mapping`.

## Task 1.5.4: Test Dex (dev-only OIDC issuer)

- [ ] **Step 1: Write `system/deploy/dex/config.yaml`**

Static connector (no LDAP dependency for tests):
```yaml
issuer: http://host.docker.internal:5556/dex
storage:
  type: memory
web:
  http: "0.0.0.0:5556"
staticClients:
  - id: media-controlplane
    redirectURIs:
      - "https://media.local/api/auth/callback"
      - "http://localhost/api/auth/callback"
    name: Media System
    secret: test-secret
enablePasswordDB: true
staticPasswords:
  - email: "admin@test"
    hash: <bcrypt of "adminpass">
    username: "admin"
    userID: "test-admin"
  - email: "user@test"
    hash: <bcrypt of "userpass">
    username: "user"
    userID: "test-user"
staticGroups:
  - email: "admin@test"
    group: "media-admins"
    userID: "test-admin"
```

> The `hash` is generated at build time (htpasswd-free) with `DEX_PASSWORD` env seed; the committed config uses a placeholder bcrypt string documented in `config.example.yaml`. The k8s ConfigMap (P5) carries the same content. `media-admins` group maps to `ADMIN_GROUPS=media-admins` so `admin@test` is an admin and `user@test` is not.

- [ ] **Step 2: Compose service `compose.override.dex-test.yml`**

`dex-test` service: image `ghcr.io/dexidp/dex:<pinned tag>` (e.g. `v2.39.1`), config mounted. **Reachability contract:** the issuer must be reachable from BOTH the control-plane container (server-side discovery/token exchange) AND the test host (curl follows the authz redirect). Compose implements:
- publish `127.0.0.1:5556:5556` on the host,
- control-plane gains `extra_hosts: ["host.docker.internal:host-gateway"]`,
- dev issuer = `http://host.docker.internal:5556/dex`, and the test host maps `host.docker.internal` → `127.0.0.1` (documented in `/etc/hosts`, dev-only) — or set issuer to the host LAN IP if reachable cross-net.
`lib_login.sh` follows the redirect URL verbatim, so both legs agree. (k3s uses a NodePort form of the same contract — Phase 5.)

Static client `redirectURIs` must include the dev redirect: `https://media.local/api/auth/callback` (compose) — k3s registers the NodePort URL separately in its own Dex ConfigMap.

- [ ] **Step 3: Verify Dex answers discovery**

With the stack up: `curl -s http://host.docker.internal:5556/dex/.well-known/openid-configuration | jq -r .issuer` → expected `http://host.docker.internal:5556/dex`; the control-plane's discovery+cache succeeds; login as both identities works.

- [ ] **Step 4: Commit** — `feat: test dex oidc provider for dev e2e`.

## Task 1.5.5: Control-plane API surface

- [ ] **Step 1: Templates — `routers/templates.py`**

`GET /api/templates` returns the template list read from `config/templates.schema.json` (authoring lands in P2; P1.5 ships a provisional `templates.schema.json` with the 4 model templates + smoke template, params typed). `GET /api/templates/{id}/schema` returns the param schema (admin and user identical — full control for all).

- [ ] **Step 2: Uploads — `routers/uploads.py`**

`POST /api/uploads/pre` (multipart, owner-scoped, stored at `UPLOAD_ROOT/<user>/<sha256-prefix>-<safe-name>`; size cap 1 GiB; mime allowlist `image/png|jpeg|webp|video/mp4`); `GET /api/uploads/{user}/files` (owner/admin only). Used by I2V first-frame and Edit input-image.

- [ ] **Step 3: Jobs — `routers/jobs.py`**

`POST /api/jobs` (param validation vs template schema → 422 JSON on mismatch; enqueue row `queued`; response 201 `{job_id}`); `GET /api/jobs` (owner's jobs, newest first, paged); `GET /api/jobs/{id}` (owner/admin; includes `progress`, `status`, gallery items); `POST /api/jobs/{id}/cancel` (owner/admin; set `cancelled` if `queued`; if `running`, tell worker → send interrupt).

- [ ] **Step 4: Gallery — `routers/gallery.py`**

`GET /api/gallery` (owner-only list; admin optional `?user=<uid>`); `GET /api/gallery/{id}/file` (stream, owner/admin only; `Content-Disposition` with safe filename); `GET /api/gallery/{id}/metadata`; `DELETE /api/gallery/{id}` (owner delete OR admin moderation delete — both remove row + files under that gallery dir).

- [ ] **Step 5: Admin — `routers/admin.py`** (`require_admin`)

`GET /api/admin/system` (versions, queue depth, worker health, storage free) ; `GET /api/admin/jobs/{id}/raw` (full POSTed workflow JSON); `GET /api/admin/users`; `POST /api/admin/gallery/{id}/delete` (moderation). Every route logs an audit line (user, action, target, ts) to stdout.

- [ ] **Step 6: OpenAPI**

Mount `/api/openapi.json` (default). SPA fetches by path; no hard-coded host.

- [ ] **Step 7: Unit/API tests + commit**

`controlplane_unit.sh` cases: unauthenticated 401 on jobs/gallery/admin; owner isolation (A's gallery not in B's); template validation 422; upload mime reject; cancel queued; admin raw view 403 for non-admin. Run inside the controlplane container or venv against the compose Postgres. Commit `feat: controlplane api (templates/uploads/jobs/gallery/admin)`.

## Task 1.5.6: FIFO worker + ComfyUI client + gallery copy

- [ ] **Step 1: `comfy.py`**

httpx client to `COMFY_INTERNAL_URL`: `POST /prompt` (workflow + `client_id`), `GET /history/{prompt_id}`, `POST /interrupt`. Non-2xx → job `failed` with server error text.

- [ ] **Step 2: `worker.py`**

Single asyncio loop: poll `jobs WHERE status='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED` (FIFO). On claim: set `running`, resolve template → workflow JSON (server-side file), inject user params (apply same `"lo ras"` → `"loras"` key normalize if template is a LoRA workflow), POST to ComfyUI with `client_id=job_id`; open `WS to /ws/{client_id}` subscribing to `executed`/`progress` → update `counts`; on terminal history entry → run `gallery.copy()`; set `success`. Exceptions → `failed`. Loop interval small; single worker enforced by the FOR UPDATE claim (safety net over "one worker" config).

> ComfyUI `/prompt` + its WS are internal-only, reached at `COMFY_INTERNAL_URL`; the SPA sees progress only via `GET /api/jobs/{id}` polling through the control-plane — never ComfyUI directly.

- [ ] **Step 3: `gallery.py`**

`GALLERY_ROOT/<user>/<job-id>/` mkdir; copy `ComfyUI/output/<run>/images/*.png`, `/videos/*.mp4` (and the JSON metadata sidecar `metadata.json`) from the shared scratch volume; compute sha256 + size; insert `gallery_media` rows. Filenames sanitized (basename-only, replace whitespace with `_`, reject `..`).

- [ ] **Step 4: Failure & cancel semantics**

Job that dies in ComfyUI or times out (Wan cap, e.g. 3600s) → `failed` with `error`. `cancel` sets `cancelled`; worker skips `queued` rows with `cancelled` and interrupts `running` ones. No `success` without a gallery row.

- [ ] **Step 5: Worker unit test with mock ComfyUI**

`controlplane_unit.sh` adds a mock `comfyui` fixture (an httpx ASGI transport or a tiny stub container answering `/prompt`/`/history`). Assert FIFO order, gallery copy, failure path, cancel of queued job.

- [ ] **Step 6: Commit** — `feat: fifo worker, comfy client, gallery copy`.

## Task 1.5.7: Nuxt SPA (SSG) served by the control-plane

- [ ] **Step 1: Scaffold `system/spa/`**

Nuxt 3 + TypeScript + vue-tsc. `nuxt.config.ts`: `ssr:false` (static client app), `nitro.preset` static output via `nuxt generate`, `app.baseURL` empty (served at `/`), build target config so `package.json` build script output lands in `dist/`.

- [ ] **Step 2: Auth plumbing**

`api.ts` composable wraps `fetch('/api/...', {credentials:'include'})`, maps 401 → login redirect, attaches JSON error bodies. `auth.ts` store: `me` from `/api/auth/me`, `isAdmin`, `login()` → `location.assign('/api/auth/start')`.

- [ ] **Step 3: Pages**

- `login.vue` — explains SSO redirect; "Sign in via organizational SSO" → `/api/auth/start`.
- `templates/index.vue` — template cards; expandable form generated from `/api/templates/{id}/schema` (typed inputs: sliders/checkboxes for float/bool, up/down for steps/image parms, file pickers for image-input flags that hit `/api/uploads/pre`); "Submit" → POST `/api/jobs`.
- `jobs/index.vue` — owner job list; poll `/api/jobs/{id}` progress; cancel button; status badges; link to gallery item when `success`.
- `gallery/index.vue` — grid of owner's media; download/open file, delete; metadata side-panel.
- `admin.vue` — shown only when `isAdmin`: system view, job raw JSON, moderation delete, user list.

- [ ] **Step 4: Responsive + a11y**

WCAG AA: focus states, form labels for every input, `prefers-reduced-motion` respects, no emoji-only status icons (text + icon). Pass `vue-tsc` and a production `nuxt build`.

- [ ] **Step 5: Bake into image**

Update `system/controlplane/Dockerfile`: Stage 1 does `npm ci && npm run build` on `system/spa/` → copy `dist/` to `/opt/media/spa`. `.dockerignore` excludes `node_modules`, `.nuxt`. Rebuild `controlplane-media:0.1.0` and confirm `/` serves the real app HTML and `/api/healthz` still 200.

- [ ] **Step 6: SPA build smoke test**

`controlplane_unit.sh` asset assertions: built `dist/index.html` exists, SPA served through proxy 200, no `http://` absolute API URLs in bundle (all relative `/api/…`).

- [ ] **Step 7: Commit** — `feat: nuxt spa ssg served by controlplane`.

## Task 1.5.8: E2E against compose (test Dex)

- [ ] **Step 1: Write `system/tests/lib_login.sh` + `system/tests/e2e_spa.sh`**

Extract the login sequence into a **shared helper** `system/tests/lib_login.sh`: `login <email> <password>` → prints a curl cookie-jar path holding a valid `media_sid` session (follows `/api/auth/start` → Dex password form → callback; idempotent; exits non-zero on failure). It honors `DEX_OIDC_ISSUER`/`DEX_USER`/`DEX_PASS` and stays parameterized so P3's `smoke.sh`, P4's `gpu-smoke.sh`, and P5's `k8s-smoke.sh` reuse it verbatim.

Sequence (browserless, curl-based with `-c/-b` cookie jar + CSRF capture):
1. Unauthenticated `/api/jobs` → 401; `/` → 200 SPA HTML.
2. `/api/auth/start` → 302 Location to `DEX_OIDC_ISSUER/auth?…` (assert `client_id=media-controlplane`, `redirect_uri`).
3. (Test Dex) login as `admin@test` → follows redirect back to callback → `media_sid` cookie set → `/api/auth/me` shows `is_admin:true`.
4. `GET /api/templates` lists 5 templates; `GET /api/templates/{id}/schema` returns typed params.
5. `POST /api/jobs` (smoke template, minimal params) → 201; poll `/api/jobs/{id}` until `success`; assert `gallery_media` row + `GET /api/gallery/{id}/file` → 200 and PNG magic bytes.
6. Submit a second job while first `running` → assert FIFO (second stays `queued` until first finishes).
7. Cancel a queued job → `cancelled`.
8. Failure path: `POST /api/jobs` missing required param → 422; a deliberate broken workflow (invalid node class injected via test fixture) → status `failed`.
9. **Two-user isolation:** login as `user@test` → `GET /api/gallery` excludes `admin@test`'s items; `GET /api/gallery/{admin_item}/file` → 403; `POST /api/jobs/{admin_job}/cancel` → 403.
10. Admin moderation: `admin@test` deletes `user@test`'s gallery item → 200, then file 404.
11. `/api/admin/*` as `user@test` → 403; as `admin@test` → 200.
12. Logout invalidates cookie → `/api/jobs` → 401.

- [ ] **Step 2: Run e2e on this machine**

```bash
cd /home/darshan.parmar/Desktop/video-model/system
docker compose -f deploy/compose/base.yml \
  -f deploy/compose/compose.override.cpu.yml \
  -f deploy/compose/compose.override.dex-test.yml up -d --build
DOMAIN=media.local bash tests/e2e_spa.sh
```
Expected: all 12 groups pass. Save output as `system/tests/artifacts/e2e.log` (gitignored).

- [ ] **Step 3: K3s-ready shape**

Keep `e2e_spa.sh` parameterized by `DOMAIN`/`HTTPS_PORT`/`NO_RESOLVE` (P5 re-runs it in-cluster) and a `DEX_USER`/`DEX_PASS` env pair so only the issuer/creds differ.

- [ ] **Step 4: Gate wiring prep**

Makefile `make smoke` (Phase 3) will call this e2e; for now add `make e2e` calling the above command so P6 `gate.sh` has a reference target.

- [ ] **Step 5: Commit** — `test: oidc e2e suite (login, fifo, gallery, isolation, moderation)`.

---

## Phase 1.5 Exit Criteria

1. `docker compose -f base.yml -f compose.override.cpu.yml -f compose.override.dex-test.yml up` runs nginx + control-plane + postgres + comfyui + dex-test on the internal net; ComfyUI and Postgres ports never published; Dex publishes only `127.0.0.1:5556` (+ control-plane `host.docker.internal` host-gateway) so the issuer stays reachable from both legs.
2. Test Dex discovery (`http://host.docker.internal:5556/dex/.well-known/openid-configuration`) returns `issuer`; login as both `admin@test` and `user@test` completes the full OIDC code flow to the callback and sets a signed HttpOnly session cookie.
3. `/api/auth/me` reflects `is_admin` from `media-admins` membership; users cannot self-attribute roles.
4. The full API surface (templates/uploads/jobs/gallery/admin) enforces auth; non-admins get 403 on `/api/admin/*` and cannot read/delete another user's gallery.
5. FIFO: second job stays `queued` until first `running` completes; cancel works for `queued` and `running` jobs; failures land in `failed` with an error and NO gallery row.
6. Gallery: every `success` job has a matching `gallery_media` row and a copyable file under `GALLERY_ROOT/<user>/<job-id>/` with a `metadata.json` sidecar; delete removes both DB and files.
7. SPA: `nuxt build` passes vue-tsc; bundle served at `/` through nginx; all API calls are relative `/api/*`; admin page only renders for admins.
8. `system/tests/controlplane_unit.sh` and `system/tests/e2e_spa.sh` pass on this machine (CPU), with ComfyUI mocked where GPU/model behavior is out of scope.
9. `git log` shows the P1.5 commits; `.env.example` carries the full control-plane env envelope reviewable in `config/README.md`.
10. No basic-auth/htpasswd anywhere; no ComfyUI UI exposure; Postgres is the sole metadata store.