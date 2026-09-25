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
