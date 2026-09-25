# Dev overlay (k3s) — the project's primary in-cluster test vehicle

Renders the media stack into `media-system` with NodePort surfaces, CPU mode,
an in-cluster test Dex, hostPath models and gitignored secrets.

## Prep (per box)

```bash
cd system
bash scripts/k3s-prep.sh          # stages certs + secrets.env (idempotent)
# Substitute the node IP in the two files that reference ${NODE_IP}:
sed -i "s/\${NODE_IP}/$NODE_IP/" deploy/k8s/overlays/k3s/patches/controlplane-env-cm.yaml
sed -i "s/\${NODE_IP}/$NODE_IP/" deploy/k8s/overlays/k3s/config-dex.yaml
```

`${NODE_IP}` = the k3s node LAN IP (`kubectl get nodes -o wide`). One Dex
NodePort (30556) serves BOTH legs of the OIDC flow (pod → `http://$NODE_IP:30556`,
test host → `http://127.0.0.1:30556`); nginx is NodePort 30443; comfyui and
controlplane stay ClusterIP-only.

## Render / apply (needs a live cluster + imported images)

```bash
kubectl kustomize overlays/k3s > /tmp/media-k3s.yaml   # parse (works anywhere)
kubectl apply -k overlays/k3s                          # k3s box
kubectl -n media-system rollout status deploy/comfyui --timeout=300s
kubectl -n media-system get pods -o wide
```

## Test

```bash
bash tests/k8s-smoke.sh          # in-cluster OIDC roundtrip (NodePort 30443)
bash tests/k3s-regression.sh     # every prior suite, re-run in-cluster
```

## Layout

- `patches/cpu-args.yaml` — comfyui `COMFY_MODE=cpu` (dev box has no GPU).
- `patches/hostPath-models.yaml` — mounts the Phase-3 `link-models.sh` tree.
- `patches/nodeport.yaml` + `patches/controlplane-env-cm.yaml` — NodePort/URL wiring.
- `config-dex.yaml` — test Dex (admin@test/user@test, group media-admins).
- `secrets.env` (gitignored) + `certs/` (gitignored) — secret sources for the
  `app-secrets` / `comfyui-tls` secretGenerators.