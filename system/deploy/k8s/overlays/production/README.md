# Production GPU overlay — VALIDATE-ONLY in this repository.

## Status

Renders and server-dry-runs cleanly; it is NEVER applied from this repo (no GPU
node, no registry, no org Dex). Deploying is an operator action on the real
cluster, from this overlay after filling the gitignored inputs below.

## Prep (per cluster)

```bash
cd system
mkdir -p deploy/k8s/overlays/production/certs
cp deploy/certs/fullchain.pem  deploy/certs/privkey.pem deploy/k8s/overlays/production/certs/
cp deploy/k8s/overlays/production/secrets.env.example \
   deploy/k8s/overlays/production/secrets.env   # then fill in (chmod 600)
# Substitute the real org endpoints in patches/controlplane-env-cm.yaml and
# patches replaced by the operator's registry/StorageClass/Ingress host names.
```

Invariants relied on by the operator:

- `comfy-node/gpu=true` label + the shown taint/toleration on GPU nodes; the
  nvidia-device-plugin must advertise `nvidia.com/gpu`.
- Images `registry.internal.example/media/*` already pushed with the same tags
  Shipped by `scripts/ship-image.sh`.
- An Ingress controller for class `nginx`; `comfyui-tls` hosts
  `media.example.com` (DEX / OIDC values in `patches/controlplane-env-cm.yaml`
  must match what the org Dex has for this client).
- StorageClasses `fast` / `slow` and a PV behind the `models` claim (rename the
  base placeholder — see `patches/pvc-storageclass.yaml`).

## Validate (no apply)

```bash
kubectl kustomize deploy/k8s/overlays/production > /tmp/media-prod.yaml
kubectl apply --dry-run=server -f /tmp/media-prod.yaml
```

ComfyUI runs `COMFY_MODE=gpu COMFY_VRAM=lowvram COMFY_EXTRA_ARGS=--cpu-vae` with
`limits.nvidia.com/gpu=1` and is the only workload pinned to GPU nodes; nginx is
the sole external surface (Ingress), comfyui/controlplane/postgres stay
ClusterIP-only.