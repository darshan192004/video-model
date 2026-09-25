# RTX 3090 GPU wire-up (DEFERRED-REAL)

Operationally deferred: authored, but the physical RTX 3090 box does not exist
in this environment yet, so nothing below has been executed. The systemd unit
was `systemd-analyze verify`-checked; the compose override was rendered and
validated on the dev box (no GPU); ship-image was archive-proven with
`DRY_RUN=1`; `gpu-smoke.sh --validate-shape` passes on the dev box. The
box-only steps are followed here, in order, by the on-site operator.

## 0. Preflight on the box

- Ubuntu 22.04 LTS (matches the ComfyUI image base), systemd, `docker`
  (compose v2 plugin), `rsync`, `jq`, `python3`, `nvidia-smi` present.
- NVIDIA driver exposes a single RTX 3090 (24 GB, gpu-only/no SLI).
  ```bash
  nvidia-smi --query-gpu=name,memory.total --format=csv
  ```
- `comfy` user created and added to the `docker` group;
  `comfy` owns `/home/comfy/media-system` and `/home/comfy/.docker`.

## 1. Ship artifacts (FROM the dev box)

```bash
DRY_RUN=0 SSH_ALIAS=$box bash system/scripts/ship-image.sh
```
Streams comfyui-media, controlplane-media, postgres, nginx (`docker save | ssh | docker load`),
then rsyncs `system/` to `/home/comfy/media-system` (excludes `.env`, certs, venvs, models, SPA build tree).

Verify on the box:
```bash
docker images                 # expect the four images
ls /home/comfy/media-system   # imports, but NO .env yet
```

## 2. Identity + secrets (`/home/comfy/media-system/.env`)

Copy the example and fill in:
```bash
cp .env.example .env && $EDITOR .env
```
- `DEX_OIDC_ISSUER=https://dex.<org.example>/dex` — the REAL org Dex with the
  FreeIPA-backed control-plane device/SE registration (§5.6). No in-repo test Dex.
- `OIDC_DOMAIN=<media-subdomain>`, `OIDC_SCHEME=https`, `HTTPS_PORT=443`.
- `LINKED_MODELS=<host path>/<tmp>/media-weights`, `LINKED_DEST=/opt/ComfyUI/models`.
- `TEMPLATE_FIXTURES_DIR=` left empty on the box (real templates only).
- `RESTART=unless-stopped`, `COMFY_VRAM=lowvram`, `COMFY_SHM=8g`.

Place the Let's Encrypt/org-signed keypair at `deploy/certs/media-system.crt` and
`.key` (nginx mounts them `:ro`; the dev self-signed certs are for dev-only).

## 3. Link weights through the model bridge

The manifest's sha256 pins are empty on first deploy, so link-models links
whatever `find` discovers under `LINKED_MODELS` and records verified/mismatch:
```bash
bash scripts/link-models.sh --write-hashes config/models.manifest.json       # records LINKS
jq . config/models.manifest.json                                             # REVIEW the new hashes
```
Then commit those hashes back from the box to the repo (they become verified
pins for the next sync). Re-run gpu-smoke --validate-shape once after hashing:
```bash
bash tests/gpu-smoke.sh --validate-shape    # now byte-exact on the real weights
```

## 4. Boot the stack under systemd

```bash
sudo install -m 0644 deploy/systemd/media-system.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now media-system
sudo systemctl status media-system          # active (oneshot RemainAfterExit)
docker compose -f base.yml -f compose.override.gpu.yml -p media ps
```
`docker compose up -d --wait` inside the unit waits for the four services to be
healthy; a non-zero exit is restarted by `Restart=on-failure`.

## 5. GPU smoke (`gpu-smoke.sh --deploy`)

Run as the operator from the box shell (not under systemd), with real SSO creds:
```bash
cd /home/comfy/media-system
DEX_USER=<box-device-account@org.domain> DEX_PASS=<secret> \
  bash tests/gpu-smoke.sh --deploy
```
Reduced-steps submissions land in `/opt/media/workflows/<template>.json`, poll to
success, and each gallery file is byte-checked as a PNG. The background sampler
writes `tests/artifacts/gpu-smoke-<ts>.csv`; the trailing line reports peak VRAM.
Expected: peak under 24 GB with `lowvram + --cpu-vae` (SAVE_VIDEO stays PNG in v2).
If an SSO MFA step blocks the browserless login, export a jar instead:
`GPU_SMOKE_COOKIE_JAR=/path/jar` (curl cookie jar with `media_session`).

## 6. Diagnose / rollback

- `journalctl -u media-system -f` (unit + compose health).
- `docker compose ... ps` / `logs` per service; ComfyUI stays on the internal
  network (no 8188 port mapping) — reach it via `docker compose exec comfyui`.
- `sudo systemctl restart media-system` re-runs `up -d --wait`.
- `sudo systemctl disable now media-system` then `docker compose down`
  to tear the stack down; named volumess preserve postgres/uploads.

## 7. Security notes

- ComfyUI bound to the compose bridge, bumped only by control-plane.
- `X-Frame-Options/CSRF` untouched here; the only new exposure is nginx:443.
- Weights/links live outside the container (`LINKED_MODELS` `:ro`); cipherkeys
  stay in `.env` (0600, owned by comfy) per the P0 secret-scope rules.