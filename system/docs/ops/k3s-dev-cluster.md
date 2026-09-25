# Dev k3s cluster (local test vehicle)

Per the user directive, **k3s is the primary in-cluster test vehicle**: every
prior suite re-runs against the k3s-hosted stack via `tests/k3s-regression.sh`.
This document covers bootstrap/reset and the addressing notes the DevX overlay
needs. It is for the **dev box only** — production GPU deployment goes through
`deploy/k8s/overlays/production` + `docs/ops/gpu-wire-up.md`.

> Status on THIS box: **bootstrap DEFERRED** — no k3s install performed yet
> (`systemctl is-active k3s` reports inactive; no `/usr/bin/k3s`). The overlay
> render + structural checks below run without a cluster; `kubectl apply` and
> the in-cluster suites are executed once the box is bootstrapped.

## Install (first time)

```bash
curl -sfL https://get.k3s.io | K3S_KUBECONFIG_MODE=644 sh -
systemctl is-active k3s
kubectl get nodes
kubectl get nodes -o wide          # record NODE_IP for the Dex reachability contract
```

Addressing notes captured at install time:

- **NODE_IP** — the node's LAN IP. The in-cluster test Dex publishes a NodePort
  (`30556`); the control-plane pod reaches the issuer at
  `http://${NODE_IP}:30556/dex`, while the test host (same machine) reaches the
  same NodePort via `127.0.0.1:30556`. Because k3s NodePorts bind `0.0.0.0`, one
  Service serves both the pod leg and the browser leg of the OIDC flow.
- **nginx NodePort** — `overlays/k3s` maps 443→30443; the callback URL registered
  in the Dex static client is `https://127.0.0.1:30443/api/auth/callback`.
- **images** — dev images are imported out-of-band for an offline farm:
  `docker save <4 images> | k3s ctr images import -` (see Task 5.3).

The DevX overlay uses `${NODE_IP}` in `overlays/k3s/kustomization.yaml`
(`DEX_OIDC_ISSUER` literal) — substitute the real node IP before applying.

## Reset / teardown

```bash
sudo systemctl stop k3s-agent k3s 2>/dev/null || true
sudo /usr/local/bin/k3s-uninstall.sh
```
Re-install from scratch per the Install section; the `media-system` namespace,
PVCs and the imported images all go away with the node, so re-run the overlay
apply + `k3s-regression.sh` after a fresh boot.

## Wrap-up (after bootstrap)

- `system/tests/k8s-smoke.sh` → in-cluster OIDC roundtrip.
- `system/tests/k3s-regression.sh` → every prior suite re-run in-cluster.