# Self-hosted media generation system

A LAN media box: text-to-image / image-edit with **Qwen-Image-2.1** and
text-to-video / image-to-video with **Wan 2.2** (both run inside ComfyUI). A
FastAPI **control-plane** pins user-supplied generation templates, enforces
**per-user galleries**, provides OIDC single sign-on through your org's
**Dex/FreeIPA**, and nginx (TLS) is the only exposed surface. Deliverables are
structured as a `system/` repo with compose + k3s deployment paths.

**License gate:** read `docs/LICENSES.md` before any commercial use. Wan 2.2 is
Apache-2.0 (commercial OK). **Qwen-Image-2.1 is under the Qwen Research License
– NON-COMMERCIAL ONLY**; commercial use requires a separate license from Qwen.
Current deployments are private/internal (compliant).

## Layout map

| Path | What it is |
| ---- | ---------- |
| `system/controlplane/` | FastAPI app + FIFO worker (same image); `app/` is the code, `unit/` has the mock ComfyUI server + unittests |
| `system/spa/` | Nuxt SPA (SSG) — the user surface, baked into the control-plane image |
| `system/comfyui/` | Pinned, digest-based ComfyUI server image (backend SHA + frontend tag) |
| `system/nginx/` | TLS reverse proxy; `/ws` upgrade + `/api/(jobs\|auth)/` rate limit |
| `system/deploy/compose/` | `base.yml` + `compose.override.{cpu,gpu,dex-test}.yml` |
| `system/deploy/k8s/` | kustomize `base/` + `overlays/{k3s,production}/` |
| `system/workflows/` | 4 locked API-format generation graphs (`qwen-t2i`, `qwen-edit`, `wan-t2v`, `wan-i2v`) |
| `system/config/` | `templates.schema.json` (param/URL contract) + `models.manifest.json` (sha256 lockstep) |
| `system/tests/` | Suites: `proxy_tls.sh`, `controlplane_unit.sh`, `e2e_spa.sh`, `workflow_schema.sh`, `smoke.sh`, `gpu-smoke.sh`, `k8s-smoke.sh`, `k3s-regression.sh` |
| `system/scripts/` | `gen-certs.sh`, `link-models.sh`, `doctor.sh`, `ship-image.sh`, `k3s-prep.sh`, `k8s-sync-configmaps.sh`, `gate.sh` |
| `docs/` | `LICENSES.md`, `README.md` (this file), `ops/runbook.md`, `acceptance-report.md` (generated) |
| `system/docs/ops/` | `gpu-wire-up.md` (3090 box runbook), `k3s-dev-cluster.md` |

## Quickstart (CPU dev box)

```bash
cd system
cp .env.example .env        # then set SESSION_SECRET, OIDC_CLIENT_SECRET,
                            # POSTGRES_PASSWORD — see SECURITY.md
bash scripts/gen-certs.sh   # self-signed certs for nginx (TLS-only)
bash scripts/link-models.sh # fixture weights + models.manifest lockstep
docker compose -f deploy/compose/base.yml \
               -f deploy/compose/compose.override.cpu.yml \
               -f deploy/compose/compose.override.dex-test.yml \
               up -d --build
make unit                   # in-process API/worker checks, no services
make smoke                  # full control-plane smoke over the compose stack
```

Open `https://localhost` (accept the self-signed cert) and sign in via the test
Dex (`admin@test`/`adminpass`). Dev auth can use the in-app mock instead:
`OIDC_MOCK=1 make e2e` (needs the native stack — `system/tests/start_mock_comfy.sh`).

## Production (RTX 3090 GPU box)

1. `bash scripts/ship-image.sh` — push the four images to the box (add `DRY_RUN=1` to inspect).
2. Place weights, then `bash scripts/link-models.sh` (`--write-hashes` to record true sha256).
3. On the box: `docker compose -f deploy/compose/base.yml -f deploy/compose/compose.override.gpu.yml up -d` (nginx:443 is the only published port; ComfyUI stays on the private network).
4. `bash system/tests/gpu-smoke.sh --deploy` — full GPU job roundtrip + VRAM profile; browser check in the SPA.
5. Autostart: `deploy/systemd/media-system.service` (unit notes in the file).

Full box runbook: `system/docs/ops/gpu-wire-up.md`.

## Kubernetes

Same base, same stack, in-cluster. Dev overlay with an in-cluster test Dex:

```bash
bash scripts/k3s-prep.sh                 # stage certs + secrets.env (idempotent)
kubectl apply -k deploy/k8s/overlays/k3s # import the images into k3s first
bash tests/k8s-smoke.sh                  # in-cluster OIDC roundtrip
bash tests/k3s-regression.sh             # every prior suite, re-run in-cluster
```

Node IP substitution + image import steps: `system/docs/ops/k3s-dev-cluster.md`
and `deploy/k8s/overlays/k3s/README.md`. The GPU **production overlay**
(`deploy/k8s/overlays/production/`) renders + server-dry-runs and is
validate-only in this repo — see its README.

## Security

See `SECURITY.md`. TLS-only (one nginx:443), OIDC-only auth (no basic-auth),
non-root containers (UID 1000), digest-pinned base images, API rate limiting,
and **zero committed secrets** (everything is gitignored + `.example` stubs).

## Acceptance trace

Run the aggregated final gate to recertify every spec acceptance line:

```bash
bash system/scripts/gate.sh
```

It writes `docs/acceptance-report.md` tagging each criterion **VERIFIED** (this
machine) or **DEFERRED** (GPU box / real weights — see the report).