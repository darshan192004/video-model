# Phase 5 — Kubernetes Deployment (k3s, cluster-agnostic) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Express the **full control-plane stack** as Kubernetes manifests with **kustomize** — cluster-agnostic `deploy/k8s/base` (nginx + control-plane + postgres + comfyui) + a `overlays/k3s` dev overlay (NodePorts, CPU mode, **in-cluster test Dex**) — boot it, and prove the complete OIDC roundtrip + gallery isolation **inside the cluster**. The production GPU overlay is validated structurally only (this box has no GPU).

**Architecture:** Four workloads mirror the compose `base.yml`: `comfyui` (Deployment, internal ClusterIP), `controlplane` (Deployment, internal ClusterIP) reaches ComfyUI over the internal service DNS, `postgres` (StatefulSet + PVC), `nginx` (Deployment + Service — NodePort on dev). ConfigMaps carry the nginx server block, the five workflow JSONs, `templates.schema.json`, and the Dex config; secrets (via `secretGenerator`) carry the TLS cert/key, `OIDC_CLIENT_SECRET`, `SESSION_SECRET`, and `POSTGRES_PASSWORD`. Models mount from a hostPath → `system/models` (the Phase-3 `link-models.sh` tree). The k3s overlay runs a **test Dex** (static connector, `admin@test`/`user@test`, group `media-admins`) so the in-cluster regression exercises real OIDC login. Production overlay: GPU nodeSelector/tolerations/`nvidia.com/gpu`, real registry refs, ingress — validated with `kubectl kustomize`/dry-run only.

**Tech Stack:** k3s, kubectl, kustomize (built-in), Bash, curl, jq.

**Spec:** `docs/superpowers/specs/2026-09-25-comfyui-app-mode-media-system-design.md` — Phase 5 implements §5.3, §5.6, §5.7 (SPA on k8s), §5.8 (Postgres StatefulSet), §8, §9 (K8s row), §10 P5.

## Global Constraints

- Anything environment-specific lives in an **overlay**, never in `base`.
- **Exact env contract from compose** (spec §8), same names in-cluster: `COMFY_MODE/LISTEN/PORT/VRAM/EXTRA_ARGS`, `CONTROLPLANE_LISTEN/PORT`, `COMFY_INTERNAL_URL`, `DATABASE_URL` (or `POSTGRES_*` assembly), `GALLERY_ROOT`, `UPLOAD_ROOT`, `DEX_OIDC_ISSUER`, `OIDC_CLIENT_ID/SECRET`, `OIDC_REDIRECT_URI`, `ADMIN_GROUPS`, `SESSION_SECRET`, `AUTO_MIGRATE`. One image, one entrypoint, compose and k8s identical.
- Secrets via **`secretGenerator`** only (no committed plaintext). TLS from Phase-1 gitignored `deploy/certs`; OIDC/session/postgres values from a gitignored `overlays/k3s/secrets.env`.
- Workflows + `templates.schema.json` mount as **read-only ConfigMaps** into the control-plane at `/opt/media/workflows` and `/opt/media/config` (same paths as compose mounts).
- ComfyUI stays **internal-only**: no Service route to the outside; only the control-plane talks to `comfyui:8188`. nginx proxies the SPA + `/api/*` + `/ws` to `controlplane:8000`.
- **No GPU on this box** → `overlays/k3s` runs CPU (`COMFY_MODE=cpu`). The production overlay carries the GPU shape; applying it to a real cluster is a documented, manually-executed step — never run here.
- Persistence: Postgres data PVC (`postgres-data`), gallery + uploads PVCs, ComfyUI output PVC; models via hostPath (dev) patched in the overlay. Everything in `base` uses PVC/hostPath-less placeholders that overlays fill.
- All resources carry `app: comfyui-media` labels; containers run `runAsNonRoot: true`, `runAsUser: 1000`.
- **k3s is the PRIMARY test vehicle (user directive):** every prior suite re-runs inside the cluster (`k3s-regression.sh`). CPU mode + fixture weights throughout. GPU scheduling is validated structurally only.
- **Dex reachability contract:** the act `DEX_OIDC_ISSUER` must be reachable from BOTH the control-plane (server-side discovery/token exchange) AND the test host (browser leg of the OIDC flow). Dev/k3s implement this by publishing Dex on a reachable address: compose binds `127.0.0.1:5556:5556` (host) and gives the control-plane container `extra_hosts: host.docker.internal:host-gateway`; k3s exposes `svc/dex-test` via **NodePort 30556**, and the issuer is set to a URL both the pod and the host can route (node IP or a dev DNS alias). `lib_login.sh` honors `DEX_OIDC_ISSUER` verbatim for its redirect-follow. Document the specific binding in the overlay README.
- The in-cluster callback URL must be registered in the Dex static client (dev overlay ConfigMap) — NodePort base URL, e.g. `https://127.0.0.1:30443/api/auth/callback`.

---

## File Structure (Phase 5 creates)

```
deploy/k8s/base/
  kustomization.yaml
  namespace-holder.md            (no namespace in base; overlay defines it)
  comfyui-deployment.yaml        comfyui-service.yaml
  controlplane-deployment.yaml   controlplane-service.yaml
  postgres-statefulset.yaml      postgres-service.yaml
  nginx-deployment.yaml          nginx-service.yaml
  configmaps.yaml                (nginx-conf, comfyui-workflows, templates-schema)
  secrets.yaml                   (secretGenerator sources doc; actual secrets in overlay)
  pvc.yaml                       (postgres-data, gallery-storage, uploads-storage, comfyui-output, models-scratch)
deploy/k8s/overlays/k3s/
  kustomization.yaml             ns=media-system; NodePorts; CPU; dex-test; secretGenerators
  config-dex.yaml                (dex ConfigMap: static connector admin@test/user@test, media-admins)
  dex-deployment.yaml            dex-service.yaml (ClusterIP + NodePort 30556)
  patches/ hostPath-models.yaml  cpu-args.yaml  nodeport.yaml  extra-hosts.yaml
  secrets.env                    (gitignored: OIDC_CLIENT_SECRET, SESSION_SECRET, POSTGRES_PASSWORD)
deploy/k8s/overlays/production/
  kustomization.yaml             patches/ gpu-device.yaml  registry-image.yaml  ingress.yaml
system/tests/k8s-smoke.sh        in-cluster control-plane OIDC roundtrip
system/tests/k3s-regression.sh   re-run ALL prior suites in-cluster
```

---

### Task 5.1: Bootstrap the k3s test cluster on the dev box

- [ ] **Step 1: Install (or verify) k3s**

```bash
curl -sfL https://get.k3s.io | K3S_KUBECONFIG_MODE=644 sh -
systemctl is-active k3s
kubectl get nodes
```
Expected: one Ready node. Capture version + node IP (`kubectl get nodes -o wide`) for the overlay patches and the Dex NodePort issuer URL.

- [ ] **Step 2: Write `docs/ops/k3s-dev-cluster.md`** — install/reset (`k3s-uninstall.sh`), kubeconfig location, "test cluster only" disclaimer, and the node-IP notes used by the Dex reachability contract.

- [ ] **Step 3: Commit** — `docs: dev k3s cluster runbook`.

---

### Task 5.2: Kustomize base manifests (4 workloads + configmaps + PVCs)

**Files:** the full `deploy/k8s/base/` set above.

- [ ] **Step 1: `comfyui-deployment.yaml` + `comfyui-service.yaml`**

Deployment `comfyui`, image `comfyui-media:0.1.0`, `imagePullPolicy: IfNotPresent`, port 8188, probes (`/system_stats` readiness, `/` liveness), env contract (`COMFY_MODE` overridden in overlays; `COMFY_LISTEN 0.0.0.0`, `COMFY_PORT 8188`), volumes: `models` (base: `emptyDir` placeholder; overlays patch), `output` → PVC `comfyui-output`. `runAsUser: 1000`. Service: ClusterIP `comfyui` → 8188. **No external route.**

- [ ] **Step 2: `controlplane-deployment.yaml` + `controlplane-service.yaml`**

Deployment `controlplane`, image `controlplane-media:0.1.0`, port 8000, readiness `/api/healthz`, liveness `/api/healthz`. Env:
- From ConfigMap `controlplane-env` (non-secret): `CONTROLPLANE_LISTEN=0.0.0.0`, `CONTROLPLANE_PORT=8000`, `COMFY_INTERNAL_URL=http://comfyui:8188`. No `DATABASE_URL`/DSN in the ConfigMap — the control-plane `settings.py` assembles the DSN from `POSTGRES_USER`/`POSTGRES_DB`/`POSTGRES_PASSWORD` (all from the `app-secrets` Secret) per the P1.5 contract. Plus `GALLERY_ROOT=/data/galleries`, `UPLOAD_ROOT=/data/uploads`, `ADMIN_GROUPS=media-admins`, `AUTO_MIGRATE=1`.
- From Secret `app-secrets`: `OIDC_CLIENT_SECRET`, `SESSION_SECRET`, `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`.
- `DEX_OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_REDIRECT_URI` from ConfigMap `controlplane-env` (dev overlay sets Dex NodePort URL).
Volumes: workflows ConfigMap → `/opt/media/workflows` (ro), templates-schema ConfigMap → `/opt/media/config` (ro), `gallery` → PVC `gallery-storage`, `uploads` → PVC `uploads-storage`. Service: ClusterIP `controlplane` → 8000.

- [ ] **Step 3: `postgres-statefulset.yaml` + `postgres-service.yaml`**

image `postgres:16-alpine`, 1 replica, env `POSTGRES_DB/USER/PASSWORD` from Secret `app-secrets`, PVC `postgres-data` (10Gi) at `/var/lib/postgresql/data`, readiness `pg_isready`. Service ClusterIP `postgres` → 5432. (On a single-node k3s `ReadWriteOnce` suffices; production overlay documents a StorageClass.)

- [ ] **Step 4: `nginx-deployment.yaml` + `nginx-service.yaml`**

image `nginx:1.27-alpine`, container port 443, entrypoint `envsubst '$DOMAIN'` + `nginx -g 'daemon off;'` (env `DOMAIN` from ConfigMap). Volumes: `nginx-conf` ConfigMap → `/etc/nginx/conf.d/default.conf` (Phase-1 file unchanged — upstream `controlplane:8000`), TLS Secret → `/etc/nginx/certs` (items mapping `tls.crt→fullchain.pem`, `tls.key→privkey.pem`). Probes via `GET /api/healthz` on 443 (through the proxy). Service: ClusterIP in base; NodePort (30443) in the dev overlay.

- [ ] **Step 5: `configmaps.yaml`**

- `nginx-conf`: `default.conf` (identical content to compose `system/nginx/conf.d/default.conf`).
- `comfyui-workflows`: five keys `<wf>.json` (from `system/workflows/*.json`).
- `templates-schema`: `templates.schema.json` (from `system/config/templates.schema.json`).
- `controlplane-env`: non-secret control-plane vars + `DOMAIN`.

- [ ] **Step 6: `pvc.yaml`** — `comfyui-output` (20Gi), `gallery-storage` (100Gi), `uploads-storage` (20Gi), `postgres-data` (10Gi), `models-scratch` (1Gi; dev hostPath patch replaces the whole `models` volume rather than this PVC — keep for production shape).

- [ ] **Step 7: Render + dry-run**

```bash
cd deploy/k8s
kubectl kustomize overlays/k3s > /tmp/rendered.yaml
kubectl apply --dry-run=client -f /tmp/rendered.yaml
```
Expected: no schema errors.

- [ ] **Step 8: Commit** — `feat: kustomize base manifests for the media stack`.

---

### Task 5.3: Import images, build secrets, and apply the k3s overlay

- [ ] **Step 1: Build the secret sources (gitignored)**

```bash
cd system
openssl rand -hex 32 > deploy/k8s/overlays/k3s/.secrets.env   # placeholder
cat > deploy/k8s/overlays/k3s/secrets.env <<'EOF'
OIDC_CLIENT_SECRET=test-secret
SESSION_SECRET=<openssl rand -hex 32>
POSTGRES_PASSWORD=<openssl rand -hex 24>
POSTGRES_USER=media
POSTGRES_DB=media
EOF
chmod 600 deploy/k8s/overlays/k3s/secrets.env
```
`kustomization.yaml`:
```yaml
secretGenerator:
  - name: comfyui-tls
    files: [ "tls.crt=../../../deploy/certs/fullchain.pem", "tls.key=../../../deploy/certs/privkey.pem" ]
  - name: app-secrets
    envs:
      - secrets.env
```

- [ ] **Step 2: Import the four images into k3s**

```bash
docker save comfyui-media:0.1.0 controlplane-media:0.1.0 postgres:16-alpine nginx:1.27-alpine \
  | k3s ctr images import -
k3s ctr images list | grep -E 'comfyui-media|controlplane-media|postgres|nginx'
```
Expected: all four listed.

- [ ] **Step 3: Apply**

```bash
cd deploy/k8s
kubectl apply -k overlays/k3s
kubectl -n media-system rollout status deploy/comfyui --timeout=300s
kubectl -n media-system rollout status deploy/controlplane --timeout=120s
kubectl -n media-system rollout status sts/postgres --timeout=180s
kubectl -n media-system rollout status deploy/nginx --timeout=120s
kubectl -n media-system get pods -o wide
```
Expected: all Running; control-plane migrated the schema (`AUTO_MIGRATE=1`), Postgres healthy.

- [ ] **Step 4: Commit** — `feat: k3s overlay with in-cluster dex-test (dev)`.

---

### Task 5.4: In-cluster roundtrip (`system/tests/k8s-smoke.sh`)

**Files:**
- Create: `system/tests/k8s-smoke.sh`

**Interfaces:**
- Consumes: NodePort 30443 (`DOMAIN=127.0.0.1 HTTPS_PORT=30443 NO_RESOLVE=1`), in-cluster Dex via `DEX_OIDC_ISSUER` (NodePort 30556 / node-IP URL).
- Produces: exit 0 when the **full control-plane path** works in-cluster: nginx up → SPA 200 → `/api/healthz` 200 → **test-Dex login** (`lib_login.sh`) → `POST /api/jobs` smoke → poll success → gallery PNG → admin vs user isolation.

- [ ] **Step 1: Write `system/tests/k8s-smoke.sh`**

```bash
#!/usr/bin/env bash
# In-cluster control-plane roundtrip against the k3s overlay (NodePort).
# Reuses lib_login.sh + the smoke.sh submission curve pointed at the NodePort.
set -euo pipefail
SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${DOMAIN:-127.0.0.1}"
HTTPS_PORT="${HTTPS_PORT:-30443}"
export DOMAIN HTTPS_PORT NO_RESOLVE=1
BASE="https://${DOMAIN}:${HTTPS_PORT}"
fail() { echo "K8S SMOKE FAIL: $*" >&2; exit 1; }

echo "[1] nginx serving SPA + healthz in-cluster"
code=$(curl -sk -o /dev/null -w '%{http_code}' "$BASE/")
[ "$code" = "200" ] || fail "SPA not served: $code"
code=$(curl -sk -o /dev/null -w '%{http_code}' "$BASE/api/healthz")
[ "$code" = "200" ] || fail "healthz: $code"

echo "[2] full control-plane e2e in-cluster (login -> cohort = smoke.sh)"
# smoke.sh (Phase 3) is the authoritative control-plane suite; in-cluster it
# must pass end-to-end (test Dex login, FIFO, cancel, failure, isolation).
bash "$SYS/tests/smoke.sh" || fail "control-plane smoke in-cluster"

echo "[3] cleanup: leave the stack up for the regression"
echo "K8S SMOKE: ALL PASS"
```

- [ ] **Step 2: Run it**

```bash
cd system && bash tests/k8s-smoke.sh
```
Expected: `K8S SMOKE: ALL PASS`. If `lib_login.sh` cannot follow the Dex redirect (reachability), fix the issuer/NodePort per the Dex reachability contract and re-run.

- [ ] **Step 3: Makefile target + commit** — `test: in-cluster k8s roundtrip` (`make k8s-smoke`).

---

### Task 5.5: Consolidated in-cluster regression (`system/tests/k3s-regression.sh`)

**Files:**
- Create: `system/tests/k3s-regression.sh`

**Interfaces:**
- Re-runs **every prior suite inside k3s** — the project's primary test vehicle per the user directive.

- [ ] **Step 1: Write `system/tests/k3s-regression.sh`**

```bash
#!/usr/bin/env bash
# Re-run every phase's testable suite against the k3s-hosted stack.
# Each suite reads DOMAIN/HTTPS_PORT/NO_RESOLVE (+ DEX creds) from env, so the
# only change from compose runs is NO_RESOLVE=1 and the NodePort target.
set -euo pipefail
SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DOMAIN="${DOMAIN:-127.0.0.1}"
export HTTPS_PORT="${HTTPS_PORT:-30443}"
export NO_RESOLVE=1
export DEX_OIDC_ISSUER="${DEX_OIDC_ISSUER:-http://127.0.0.1:30556/dex}"
export DEX_USER_ADMIN="${DEX_USER_ADMIN:-admin@test}" DEX_PASS_ADMIN="${DEX_PASS_ADMIN:-adminpass}"
export DEX_USER_PLAIN="${DEX_USER_PLAIN:-user@test}"  DEX_PASS_PLAIN="${DEX_PASS_PLAIN:-userpass}"
fail() { echo "K3S-REGRESSION FAIL: $*" >&2; exit 1; }

bash "$SYS/tests/proxy_tls.sh"                       || fail "proxy_tls (tls/ws)"
bash "$SYS/tests/controlplane_unit.sh"               || fail "controlplane_unit"
bash "$SYS/tests/e2e_spa.sh"                         || fail "e2e_spa (dEld ex 12-groups)"
# workflow_schema fetches /object_info inside the cluster (COMFY_FETCH hook,
# e.g. kubectl -n media-system run --rm curl -- curl -s http://comfyui:8188/object_info)
COMFY_FETCH='kubectl -n media-system run oi --rm -i --restart=Never --image=curlimages/curl -- curl -s http://comfyui:8188/object_info' \
  bash "$SYS/tests/workflow_schema.sh"               || fail "workflow_schema"
bash "$SYS/tests/smoke.sh"                           || fail "smoke"
bash "$SYS/tests/gpu-smoke.sh" --validate-shape      || fail "gpu-smoke --validate-shape"
bash "$SYS/tests/k8s-smoke.sh"                       || fail "k8s-smoke"

echo "K3S-REGRESSION: ALL PASS"
```

> Make `workflow_schema.sh` (P2) fetch `/object_info` via an externally settable `COMFY_FETCH` command (compose default: one-shot curl on the compose network; k3s: the `kubectl run` curl above), so the same file serves both.

- [ ] **Step 2: Run it**

```bash
cd system && bash tests/k3s-regression.sh
```
Expected: `K3S-REGRESSION: ALL PASS`.

- [ ] **Step 3: Makefile target + commit** — `test: consolidated in-cluster regression`.

---

### Task 5.6: Production GPU overlay (validated structurally, not applied here)

**Files:**
- Create: `deploy/k8s/overlays/production/` (kustomization + `patches/gpu-device.yaml`, `registry-image.yaml`, `ingress.yaml`).

- [ ] **Step 1: GPU node shape**

Patches: `resources.limits: { nvidia.com/gpu: "1" }`; `nodeSelector: { comfy-node/gpu: "true" }`; toleration for a GPU taint; env `COMFY_MODE=gpu`, `COMFY_VRAM=lowvram`, `COMFY_EXTRA_ARGS=--cpu-vae`; registry image refs (pushed images, e.g. `registry.internal.example/media/{comfyui,controlplane,nginx}` + `postgres:16-alpine`); ingress with TLS for `DOMAIN`; `DEX_OIDC_ISSUER`/`OIDC_CLIENT_*`/`OIDC_REDIRECT_URI` → the **real org Dex**; StorageClass override for the PVCs; models volume → real PV/CSI.

- [ ] **Step 2: Validate structurally (no GPU apply)**

```bash
cd deploy/k8s && kubectl kustomize overlays/production > /tmp/prod.yaml
kubectl apply --dry-run=server -f /tmp/prod.yaml
```
Expected: dry-run passes against the dev API (schema/labels sane). **Applying on a real cluster is out of scope** (flagged in the overlay README).

- [ ] **Step 3: Commit + README** — `feat: production k8s overlay (gpu node, ingress) - validate-only`.

---

## Phase 5 Exit Criteria

1. Dev k3s cluster Ready; the four images imported into k3s containerd.
2. `base` + `overlays/k3s` render and apply; comfyui/controlplane/nginx Deployments + postgres StatefulSet Running (CPU mode); schema migrated by the control-plane against in-cluster Postgres.
3. ComfyUI and control-plane Services are ClusterIP-only; nginx NodePort 30443 is the sole external surface.
4. Dex reachability contract honored: `lib_login.sh` completes a real OIDC code flow through the in-cluster test Dex (NodePort 30556), roles from `media-admins`.
5. `system/tests/k8s-smoke.sh` passes (SPA 200, healthz, control-plane smoke in-cluster).
6. `system/tests/k3s-regression.sh` passes — every prior suite re-run inside the cluster (proxy/TLS, unit, e2e, workflow schema via `COMFY_FETCH`, smoke incl. two-user isolation, gpu validate-shape).
7. Production GPU overlay renders + server-dry-run cleanly; NEVER applied on dev (no GPU node).
8. Secrets generated only from gitignored sources; no plaintext committed in any kustomization.
9. README documents how the same base deploys to the user's real cluster (production overlay).