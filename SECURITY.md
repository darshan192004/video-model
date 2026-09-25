# Security posture

## Threat model (summary)

Internal, self-hosted media generation box. Exposure surfaces: the nginx HTTPS
port (SPA + API + WS). ComfyUI, Postgres, and the control-plane have **no**
published host ports; nginx is the only ingress. Attackers of concern: LAN
lurkers, the untrusted prompt/upload content hitting the API, and dependency
drift.

## Posture table

| Area | Status | Evidence |
| ---- | ------ | -------- |
| Transport | TLS-only (TLSv1.2/1.3, self-signed internal cert) | `nginx/conf.d/default.conf`; `tests/proxy_tls.sh` asserts 200/JSON/101 + no plaintext paths |
| Authentication | OIDC RP only — org Dex/FreeIPA (test Dex in dev). No basic-auth, no htpasswd anywhere | `controlplane.app.oidc`; `git grep -c auth_basic` = 0; `deploy/dex/` |
| Authorization | Admin flag derived server-side from the Dex `groups` claim ∩ `ADMIN_GROUPS` (default `media-admins`); promotion/demotion = IdP group edit | `controlplane/app/deps.py` + `tests/smoke.sh` isolation checks |
| Sessions | HttpOnly + Secure + SameSite=Lax `media_sid`; `SESSION_SECRET` rotated out-of-band; roles captured at login (re-auth after role change) | `controlplane/app/sessions.py`; `tests/e2e_spa.sh` exercises per-user sessions |
| Non-root | Containers run UID 1000 (nginx 101); k8s `runAsNonRoot` + `allowPrivilegeEscalation:false` + dropped ALL capabilities; compose `cap_drop: [ALL]` + `no-new-privileges` (controlplane/worker/nginx); ComfyUI writes so `read_only` stays off | `*/Dockerfile`, `deploy/k8s/base/*-deployment.yaml`, `deploy/compose/base.yml` |
| Secrets in repo | None. Real values never committed; `.env.example` shows the *mechanism*. `git check-ignore` covers `.env`, `deploy/certs/`, `overlays/*/secrets.env` | grep battery (see below) |
| Supply chain | Base images digest-pinned (`FROM …@sha256:…`); library tags pinned (`postgres:16-alpine@sha256:…`, `nginx:1.27-alpine@sha256:…`); ComfyUI backend+frontend pinned to SHAs/tags; no HF `--download` at boot (weights mounted via `link-models.sh`) | `comfyui/Dockerfile`, `controlplane/Dockerfile`, `deploy/compose/base.yml` |
| DoS guardrails | nginx `limit_req` (10 r/s, burst 20) on `/api/jobs` + `/api/auth/*`; `client_max_body_size 50m` on uploads; `proxy_read_timeout 3600s` for long GPU jobs | `nginx/conf.d/default.conf` |
| Worker isolation | Single FIFO worker (`SELECT … FOR UPDATE SKIP LOCKED`); per-user galleries/upload dirs; job timeout + failure path | `controlplane/app` worker + `tests/smoke.sh` |

## No-committed-secrets rule

- Credentials enter the system ONLY via gitignored files the operator populates:
  `system/.env` (compose/native), `deploy/certs/` (TLS), `overlays/*/secrets.env`
  (k8s secretGenerators). Committed `*.example` files carry placeholders only.
- Regression check (binds the grep battery + check-ignore):

  ```bash
  git ls-files | grep -Ev '\.(md)$' \
    | xargs -r grep -lnE '(password|secret|token|BEGIN.*PRIVATE)' 2>/dev/null \
    | grep -Ev '(example|\.env\.example|sample)' || true
  git check-ignore system/.env \
    system/deploy/certs/fullchain.pem \
    system/deploy/k8s/overlays/k3s/secrets.env \
    system/deploy/k8s/overlays/production/secrets.env
  ```

  Expected: only `.env.example`-style placeholders / code *names*; all four
  paths ignored. Any real value → scrub the history branch before merging.

## Vulnerability reporting

Internal system. Report issues to the repo owner (keyholders of the 3090 box /
org Dex admin) via email: `report @ <repohost>` — replace with the operator's
address at deploy time. Never open an issue with secret values.