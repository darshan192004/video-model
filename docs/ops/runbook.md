# Day-2 operations runbook

Self-hosted media box + optional k3s. Every command below exists in this repo.

## Start / stop / restart

**Compose on the GPU box** (systemd-autostarted via `deploy/systemd/media-system.service`):

```bash
systemctl --user start|stop|restart media-system      # or with sudo if system scope
docker compose -f deploy/compose/base.yml -f deploy/compose/compose.override.gpu.yml up -d --wait
docker compose -f deploy/compose/base.yml -f deploy/compose/compose.override.gpu.yml down
```

**k3s** (per-overlay):

```bash
kubectl -n media rollout restart deploy/controlplane deploy/worker deploy/comfyui deploy/nginx
kubectl -n media get pods -o wide                        # wait until Running/Ready
kubectl -n media logs deploy/worker --tail=100 -f        # worker loop / job debugging
```

## Users & admins

Provisioning/de-provisioning happens in the **org IdP**, never per-box:

- **Dex static users**: `system/deploy/dex/config.yaml` → `staticPasswords` (dev
  test users `admin@test`, `user@test`); the test Dex is only for dev/CICD.
- **FreeIPA/org Dex**: members of the `media-admins` group become
  `is_admin:true` server-side (`ADMIN_GROUPS`, default `media-admins`).
- **Promotion/demotion** = a group edit in the IdP. ⚠️ **Users must re-authenticate
  after a role change** — session roles are captured at login (documented
  behavior, not a bug).

## Backup / restore (Postgres metadata)

Users, jobs, and the gallery index live in Postgres; image files live on
`GALLERY_ROOT` (hash-codified filenames — content is verifiable independently).

```bash
# compose
docker compose -f deploy/compose/base.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "backup-$(date -u +%F).sql"
# k3s
kubectl -n media exec deploy/postgres -- sh -c \
  'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "backup-$(date -u +%F).sql"
```

Restore: apply the dump on a fresh Postgres before first boot
(`psql -U "$POSTGRES_USER" "$POSTGRES_DB" < backup.sql`), then start the stack.

## Cert rotation

`deploy/certs/` is gitignored and self-signed for the internal box.

```bash
bash system/scripts/gen-certs.sh          # regenerate fullchain.pem + privkey.pem
# compose
docker compose -f deploy/compose/base.yml restart nginx
# k3s — re-stage the certs into the overlay (secretGenerator) and roll the pod:
bash system/scripts/k3s-prep.sh
kubectl -n media rollout restart deploy/nginx
```

## Model update

```bash
# drop the new .safetensors under the model tree, then re-link + verify hashes:
MODELS_PATH=/srv/media-weights bash system/scripts/link-models.sh
bash system/scripts/link-models.sh --write-hashes   # record real sha256 in the manifest
# restart the workloads so caches (if any) drop:
kubectl -n media rollout restart deploy/controlplane deploy/worker deploy/comfyui
```

Manifest↔workflow lockstep is enforced by `system/scripts/verify-manifest-lockstep.sh`
and re-checked in `system/tests/gpu-smoke.sh --validate-shape` and
`system/tests/workflow_schema.sh`.

## ComfyUI upgrade

Bump `COMFYUI_BACKEND_REV` (and optionally `COMFYUI_FRONTEND_TAG`) in
`system/comfyui/Dockerfile`, rebuild the image, then re-run the gate:

```bash
docker compose -f deploy/compose/base.yml -f deploy/compose/compose.override.gpu.yml build comfyui
bash system/scripts/doctor.sh && bash system/scripts/gate.sh
```

## Node failure / GPU box reinstall

1. From raw Ubuntu → `system/docs/ops/gpu-wire-up.md` (`scripts/gen-certs.sh`,
   `link-models.sh`, GPU driver/NVIDIA container toolkit).
2. Install the systemd unit (`deploy/systemd/media-system.service`) →
   `systemctl enable --now media-system`.
3. `bash scripts/doctor.sh` — environment sanity (docker, users, certs, hash
   lockstep); `bash system/scripts/ship-image.sh` to restock missing images.
4. k3s path: follow `system/docs/ops/k3s-dev-cluster.md` then
   `bash system/scripts/k3s-prep.sh && kubectl apply -k system/deploy/k8s/overlays/k3s`.