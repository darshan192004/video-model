#!/usr/bin/env bash
# Final acceptance gate. Fails loudly on the first RED of any VERIFIED check;
# DEFERRED items (real GPU, real weights, org IdP, box-only) are reported but
# never block. Produces docs/acceptance-report.md mapping every spec acceptance
# line to evidence.
#
# Prereqs: the k3s overlay must be up (overlays/k3s) with the five images
# imported — `bash scripts/k3s-prep.sh && kubectl apply -k deploy/k8s/overlays/k3s`.
# Dev/test auth runs against the in-cluster test Dex (NodePort 30556).
#
# Usage: bash system/scripts/gate.sh
set -euo pipefail

SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "${SYS}/.." && pwd)"

# --- Preflight: the verified set runs ON the k3s node (NOT on a cold host) ---
if ! kubectl get ns media-system >/dev/null 2>&1; then
  echo "GATE FAIL: media-system namespace unreachable — start the k3s overlay first" >&2
  echo "  bash scripts/k3s-prep.sh && kubectl apply -k deploy/k8s/overlays/k3s" >&2
  exit 1
fi

# Points every suite at the nginx NodePort (single external surface) without DNS.
export DOMAIN=127.0.0.1 HTTPS_PORT=30443 NO_RESOLVE=1

# ---------------------------------------------------------------------------
# VERIFIED on this machine (any red here fails the gate):
# k3s-regression drives the full chain against the in-cluster stack:
#   proxy_tls      TLS 200/json + WS 101 via the NodePort
#   controlplane_unit   OIDC RP, sessions (HttpOnly/Secure/Lax), FIFO, gallery
#   e2e_spa         admin+user OIDC login (in-cluster test Dex), jobs, galleries
#   workflow_schema     structure checks + class membership via COMFY_FETCH
#                       (kubectl-run pod fetching http://comfyui:8188/object_info)
#   smoke           submit/FIFO/cancel/failure/two-user isolation in-cluster
#   gpu-smoke --validate-shape   graph shape + manifest lockstep (no GPU)
#   k8s-smoke       SPA+healthz then the full control-plane roundtrip
# ---------------------------------------------------------------------------
"${SYS}/tests/k3s-regression.sh" || { echo "GATE FAIL: k3s-regression"; exit 1; }

# --- Acceptance evidence (spec §12) ----------------------------------------
report="${ROOT}/docs/acceptance-report.md"
{
  echo "# Acceptance report"
  echo
  echo "Generated: $(date -u +%FT%TZ) on $(hostname) (this machine — CPU k3s, no GPU)"
  echo "Deployed target: k3s overlay (nginx NodePort 30443; test Dex 30556)"
  echo
  echo "## VERIFIED (this machine, green exactly as gated)"
  echo
  echo "| Spec acceptance line | Evidence |"
  echo "| --- | --- |"
  echo "| 1. Signed-in user submits a job (SPA→API→queue→gallery half) | e2e_spa + smoke + k8s-smoke (fixture weights; submit/queue/gallery) |"
  echo "| 2. Progress over /ws; cancel + failure behave | controlplane_unit + smoke (FIFO/cancel/fail); proxy_tls asserts WS 101 |"
  echo "| 3. Deploys to k3s; in-cluster smoke passes | k8s-smoke + k3s-regression on the CPU k3s overlay |"
  echo "| 4. MODELS_PATH is read-only wiring; hash lockstep | link-models.sh fixture run + gpu-smoke --validate-shape + verify-manifest-lockstep |"
  echo "| 5. Two users see only their own jobs/galleries | smoke isolation stage (compose + k3s) |"
  echo "| 6. SSO sessions, logout, admin-flag from groups claim | e2e_spa (admin@test vs user@test) + OIDC session flags in unit |"
  echo
  echo "## Deferred — must run on the GPU box / with real IdP (NOT gate-blocking)"
  echo
  echo "- CUDA handoff (gpus all, nvidia-smi in container) → system/docs/ops/gpu-wire-up.md"
  echo "- Real weight sha256 pinning (link-models.sh --write-hashes) → gpu-wire-up.md"
  echo "- Real image/video runs + VRAM profile (gpu-smoke.sh --deploy) → gpu-wire-up.md"
  echo "- SPA on LAN with the org Dex/FreeIPA → gpu-wire-up.md + docs/ops/runbook.md"
  echo "- systemd autostart on the 3090 → deploy/systemd/media-system.service"
  echo "- Licensing: Qwen-Image-2.1 commercial use NO-GO under the Qwen Research License → docs/LICENSES.md"
} > "${report}"

echo "GATE PASS $(date -u +%FT%TZ) — verified set fully green; report: docs/acceptance-report.md"
echo "Deferred items (GPU/weights/IdP/box) documented, not blocking."