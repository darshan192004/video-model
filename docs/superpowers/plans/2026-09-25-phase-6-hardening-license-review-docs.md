# Phase 6 — Hardening, License Review, Docs, and Final Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop: review the Qwen-Image-2.1 license (flagged pre-commercial-use gate), run a security/hardening pass (non-root, no secrets in repo, TLS-only, no HF downloads, OIDC sessions), complete operator docs (quickstart, runbook, architecture recap tying to the spec + diagrams), then execute the **final validation gate** — a full trace of every spec acceptance criterion to evidence.

**Architecture:** No new runtime components; this phase is review + docs + evidence. The final gate aggregates the per-phase test suites (`proxy_tls.sh`, `controlplane_unit.sh`, `e2e_spa.sh`, `workflow_schema.sh`, `smoke.sh`, `gpu-smoke.sh --validate-shape`, `k8s-smoke.sh`) into one `system/scripts/gate.sh` that fails loudly on any gap, and produces a machine-readable report the user can eyeball before commercialization. Auth posture is **OIDC-only** (org Dex/FreeIPA); there is no basic-auth anywhere.

**Tech Stack:** git, curl/jq, shell, Markdown; `code-review-and-quality` skill for the review sub-tasks.

**Spec:** `docs/superpowers/specs/2026-09-25-comfyui-app-mode-media-system-design.md` — Phase 6 implements §3 (licenses), §8 (security/config), §9 (hardening row), §10 P6, and renders the §12 "Acceptance" checklist.

## Global Constraints

- **License is a ship-blocker.** Qwen-Image-2.1's license must be read and its commercial-use terms recorded before this system runs commercially (openly flagged in the spec; do not hand-wave). For private/internal use the gate still records the determination.
- Hardening must not regress Phase 0-5 smoke paths; each hardening change re-runs the affected suite.
- No secret ever lands in git: `.env`, `deploy/certs/`, `*.key`, overlay `secrets.env` stay gitignored (`OIDC_CLIENT_SECRET`, `SESSION_SECRET`, `POSTGRES_PASSWORD`, TLS keys). The final `docs/` sells the *mechanism*, not the values.
- `gate.sh` exits non-zero on the first failure; each phase's exit criteria re-trace to a line of gate output.
- Docs are user-facing and must match *actual* commands in the repo (a doc referencing a script that doesn't exist is a bug).
- **Test environment (this machine only):** the gate runs entirely on this machine against the k3s stack — no GPU, no real weights, no 3090 access. Acceptance criteria requiring real GPU/weights are **classified DEFERRED** (listed in gate output as "deferred: user must run — see docs/ops/gpu-wire-up.md") and are NOT gate failures; the gate fails loudly if any non-deferred check is red. No check may fake green via a stub.

---

## File Structure (Phase 6 creates/changes)

- `docs/LICENSES.md` — Wan (Apache-2.0) + Qwen-Image-2.1 determination.
- `docs/README.md` (repo root) — quickstart, architecture, runbook, security notes, gate reference.
- `docs/ops/runbook.md` — day-2 ops (FreeIPA group admin, pg_dump backup, cert rotation, updates, node failure).
- `system/scripts/gate.sh` — aggregated final gate.
- `SECURITY.md` — secrets policy + vuln reporting path (short).
- Review artifacts inline in `.md` sections (no extra files); the review itself uses the skills from this env.

---

### Task 6.1: Qwen-Image-2.1 license determination (BLOCKER GATE)

**Files:**
- Create: `docs/LICENSES.md`

**Interfaces:**
- Consumes: the license text as it ships with the downloaded weights (fetch the repo's `LICENSE`/README at the pinned rev), and the spec §3 assumption.
- Produces: a written determination with a **Go/No-go line** recorded for commercial use.

- [ ] **Step 1: Fetch the license text at the pinned Qwen-Image-2.1 revision**

From the weights repo (name/rev recorded in spec §5.2), capture:
- The `LICENSE` file verbatim (or the license identifier field in the safetensors header).
- Authoritative URL + commit-hash the text was captured at.

- [ ] **Step 2: Classify the terms**

Answer in `docs/LICENSES.md`:
1. Open-source license (Apache/MIT/BSD/etc.) or source-available?
2. Explicit **commercial-use** permission or restriction?
3. Any weight-specific / "you must disclose" / trailing attribution clauses?
4. Transferability to the user's deployment (self-hosted, LAN, commercial if applicable).
Include the verbatim quote for term (2).

- [ ] **Step 3: Record the determination + gate line**

Write a mandatory line:
```markdown
Determination (date): Qwen-Image-2.1 is licensed under <X> which [permits|restricts]
commercial use. Commercial launch is: [GO|NO-GO] — <one-line reason>.
```
If NO-GO: the plan requires listing the mitigation (e.g., internal-only use, or swap to a licensed alternative) in the same file — do not proceed to commercialization silently.

- [ ] **Step 4: Commit**

```bash
git add docs/LICENSES.md
git commit -m "docs: license determination for wan + qwen weights"
```

---

### Task 6.2: Security/hardening pass

**Files:**
- Create: `SECURITY.md` (repo root)
- Edit: `system/deploy/compose/base.yml` / `system/deploy/k8s/base` where the pass surfaces gaps.

**Interfaces:**
- Consumes: Phase 0-5 deliverables (dockerfile, compose, k8s, scripts).
- Produces: documented posture + rendered fixes; re-run of affected smoke suites.

Conduct as a code review (use the `code-review-and-quality` skill mindset) over:
- **Secrets:** assert none of `OIDC_CLIENT_SECRET`, `SESSION_SECRET`, `POSTGRES_PASSWORD`, TLS private keys, or `secrets.env` values are committed; `.gitignore` covers `.env`, `deploy/certs/`, `*.key`, `*.pem`, `overlays/*/secrets.env`.
- **AuthN/AuthZ posture:** OIDC RP is the only authentication surface (no htpasswd, no `auth_basic` anywhere); admin vs user enforced server-side from the Dex `groups` claim ∩ `ADMIN_GROUPS`; sessions HttpOnly/Secure/SameSite=Lax; `SESSION_SECRET` rotated and re-issued on promo/demote.
- **Non-root:** images run UID 1000; k8s sets `runAsNonRoot`; compose `cap_drop: [ALL]`, `security_opt: no-new-privileges` (ComfyUI read_only stays off — it writes).
- **Network:** TLS-only via nginx; ComfyUI keeps no HTTP port published to the host (internal-only, control-plane is the only client); nginx `server` accepts only 443.
- **Supply chain:** no HF `--download` in entrypoint by default; image bases pinned to digests rather than `:latest`; Dockerfile records `FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04@sha256:<pin>`.
- **DoS-ish guardrails:** nginx `limit_req` on `/api/jobs` + `/api/auth/*`, `proxy_read_timeout 3600s` stays, `client_max_body_size` set for video frames.

- [ ] **Step 1: Run the automated grep battery**
```bash
cd /home/darshan.parmar/Desktop/video-model
git ls-files | grep -Ev '\.md$' | xargs -r grep -lnE '(password|secret|token|BEGIN.*PRIVATE)' 2>/dev/null | grep -Ev '(example|\.env\.example|sample)' || true
```
Expected: only `.env.example`-style placeholders, never real values. Any real credential hit → scrub + note in SECURITY.md. Also assert `git check-ignore` covers `.env`, `deploy/certs/`, `overlays/*/secrets.env`.

- [ ] **Step 2: Apply the hardening deltas from review (only regression-free ones)**
Reorder so each change is individually tested:
- `cap_drop: [ALL]` + `security_opt: no-new-privileges` on controlplane/nginx; `read_only` stays off for ComfyUI.
- Pin image bases to digests (the Phase 0 Dockerfile edit).
- Add `limit_req` zone to nginx `default.conf` for `/api/jobs` and `/api/auth/*`.
- Confirm no `auth_basic`/htpasswd artifacts remain in compose/k8s configs (proxy is `proxy_tls.sh` from Phase 1).
Then re-run `system/tests/proxy_tls.sh` → expect PASS; `system/tests/smoke.sh` → expect PASS. On k8s re-run `system/tests/k8s-smoke.sh`.

- [ ] **Step 3: Write `SECURITY.md`**
Report the posture table (area → status → evidence), the no-committed-secrets rule (with the `.env.example` placeholder convention + `check-ignore` guard), OIDC session flags, and a low-friction report path (email placeholder hidden).

- [ ] **Step 4: Commit**
```bash
git add SECURITY.md system/deploy/compose/base.yml system/deploy/k8s/base system/nginx/conf.d/default.conf system/comfyui/Dockerfile
git commit -m "security: hardening pass (caps, digest pins, rate-limit)"
```

---

### Task 6.3: User-facing docs (root README + ops runbook)

**Files:**
- Create: `docs/README.md` (repo-root README)
- Create: `docs/ops/runbook.md`

**Interfaces:**
- Consumes: every script and compose target produced in Phases 0-5 (the docs MUST reference real, runnable commands).
- Produces: a new-user quickstart, an architecture recap (spine: nginx → comfyui, weights via MODELS_PATH), and an ops runbook.

- [ ] **Step 1: Write `docs/README.md`**

Sections (concise, real commands):
1. **What this is** — self-hosted media generation system (Qwen-Image-2.1 text→image + Wan-2.2 text→video) with a FastAPI control-plane, Nuxt SPA UI, single-sign-on via your org's Dex/FreeIPA (OIDC), per-user galleries, and Postgres metadata.
2. **Layout map** — table: `system/controlplane/` + `system/spa/` images, `system/deploy/compose/`, `system/deploy/k8s/`, `system/workflows/`, `system/config/models.manifest.json`, `system/tests/`, `docs/`.
3. **Quickstart (dev box, CPU):** the three commands (`make up-cpu` inside `system/`, `bash system/scripts/link-models.sh` against fixtures, `make smoke`), then open the SPA and log in.
4. **Production (3090):** `system/scripts/ship-image.sh`, place weights, `link-models.sh`, run the gpu override, run `gpu-smoke.sh --deploy`, verify in the SPA (browser). Backed by `docs/ops/gpu-wire-up.md`.
5. **Kubernetes:** `system/deploy/k8s/overlays/k3s` + `system/tests/k8s-smoke.sh`; link to production overlay doc.
6. **Security:** summarize `SECURITY.md`; TLS-only; OIDC-only auth; no secrets in repo.
7. **Acceptance trace pointer:** run `bash system/scripts/gate.sh` (Task 6.4) to produce `docs/acceptance-report.md` — the spec-criteria recertification.

- [ ] **Step 2: Write `docs/ops/runbook.md`**

Day-2:
- **Start/stop/restart** (systemd unit on the box; `make` targets; `kubectl -n media rollout restart`).
- **Users & admins** — provisioning/de-provisioning happens in the org IdP (Dex `staticPasswords` or FreeIPA). Admins = membership in the `media-admins` group (→ `is_admin:true` server-side; promotion/demotion is a group edit, no server config change). ❗ Login sessions: users must re-auth after a role change (documented; session roles are captured at login).
- **Backup** — `pg_dump` of the Postgres metadata (users, jobs, gallery index) to a timestamped file (k8s: `kubectl -n media exec deploy/postgres -- pg_dump -U media media`); restore sequence documented; gallery files live on `GALLERY_ROOT` (hash-verifiable).
- **Cert rotation** — regenerate `fullchain.pem/privkey.pem`, mount as k8s `Secret` (k3s overlay re-seals secrets.env), restart nginx.
- **Model update** — replace file under `MODELS_PATH` (hostPath), run `link-models.sh`, confirm sha map, restart workloads.
- **ComfyUI upgrade** — bump `COMFYUI_BACKEND_REV` in Dockerfile ARG, rebuild, re-gate.
- **Node failure / GPU box reinstall** — from raw Ubuntu → `docs/ops/3090-box.md` → systemd unit.

- [ ] **Step 3: Commit**
```bash
git add docs/README.md docs/ops/runbook.md
git commit -m "docs: root readme + day-2 runbook"
```

---

### Task 6.4: Final validation gate (`system/scripts/gate.sh`)

**Files:**
- Create: `system/scripts/gate.sh` (canonical scripts dir, per Phase 0; orchestrates per-phase suites)
- Output: `docs/acceptance-report.md` (generated, committed as evidence)

**Interfaces:**
- Consumes: each phase exit suite (Phase 1 `proxy_tls.sh`, Phase 1.5 `controlplane_unit.sh` + `e2e_spa.sh`, Phase 2 `workflow_schema.sh`, Phase 3 `smoke.sh`, Phase 4 `gpu-smoke.sh --validate-shape`, Phase 5 `k8s-smoke.sh`/`k3s-regression.sh`).
- Produces: exit 0 only when every check passes; a human-readable report mapping each spec acceptance line to its test, each row tagged VERIFIED or DEFERRED.

- [ ] **Step 1: Write `system/scripts/gate.sh`**

```bash
#!/usr/bin/env bash
# Final acceptance gate. Fails on first red (verified checks only).
# Deferred (real GPU/weights) checks are reported but never block.
set -euo pipefail

SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"      # system/
ROOT="$(cd "$SYS/.." && pwd)"                               # repo root
BASE="http://127.0.0.1:30443"                               # k3s nginx NodePort

req="$(mktemp -d)"; export CURLCONF="$req/curl.insecure"    # NO_RESOLVE-style
printf 'insecure\n' > "$CURLCONF"                           # self-signed dev cert

# ---- Verified on this machine (must be green) --------------------------
# Phase 1: TLS handoff via k3s NodePort (SPA 200 / healthz JSON / ws 101):
"$SYS/tests/proxy_tls.sh"      "https://$BASE"           || { echo "GATE FAIL: proxy_tls"; exit 1; }
# Phase 1.5: unit suite (OIDC RP, sessions, FIFO, gallery):
"$SYS/tests/controlplane_unit.sh"                         || { echo "GATE FAIL: controlplane_unit"; exit 1; }
# Phase 1.5: real browser-ish OIDC e2e through the k3s URL (admin + user):
bash "$SYS/tests/e2e_spa.sh" DEX_OIDC_ISSUER="$DEX_OIDC_ISSUER" \
     E2E_BASE="${E2E_BASE:-https://$BASE}"                || { echo "GATE FAIL: e2e_spa"; exit 1; }
# Phase 2: workflow/vocab alignment against the k3s control-plane object_info:
COMFY_FETCH="$BASE" bash "$SYS/tests/workflow_schema.sh" || { echo "GATE FAIL: workflow_schema"; exit 1; }
# Phase 3: smoke (FIFO/cancel/gallery/isolation) via k3s regression:
bash "$SYS/tests/k3s-regression.sh"                      || { echo "GATE FAIL: k3s-regression"; exit 1; }
# Phase 4 shape check needs no GPU:
bash "$SYS/tests/gpu-smoke.sh" --validate-shape         || { echo "GATE FAIL: gpu-shape"; exit 1; }

report="$ROOT/docs/acceptance-report.md"
: > "$report"
{
  echo "# Acceptance Report ($(date -u +%FT%TZ))"
  echo "Host: $(hostname) (this machine — no GPU)"
  echo "Deployed target: k3s (nginx NodePort 30443)"
  echo "## Verified checks"
  echo "- proxy_tls (200/json/101 via NodePort-honoring NO_RESOLVE)"
  echo "- controlplane_unit (authz via groups claim; session flags; FIFO; gallery)"
  echo "- e2e_spa (OIDC login admin+user, jobs, gallery)"
  echo "- workflow_schema (object_info alignment; no appMode/\"lo ras\")"
  echo "- k3s-regression (Phase 2+3 suites rerun in-cluster)"
  echo "- gpu-smoke --validate-shape (schema/graph shape without GPU)"
  echo
  echo "## Deferred — user must run on the GPU box (NOT gate-blocking)"
  echo "- CUDA handoff (gpus all / nvidia-smi in container) -> docs/ops/gpu-wire-up.md"
  echo "- real weight sha256 pinning (link-models.sh --write-hashes) -> gpu-wire-up.md"
  echo "- real image/video runs + VRAM profile -> gpu-wire-up.md"
  echo "- SPA check on LAN with org IdP -> gpu-wire-up.md"
  echo "- systemd autostart on 3090 -> gpu-wire-up.md"
} >> "$report"

echo "GATE PASS on $(date -u +%FT%TZ)"
echo "Deferred items documented; verified set fully green."
```

- [ ] **Step 2: Map spec acceptance lines → evidence (with deferred classification)**

Append to `docs/acceptance-report.md` (generated) a hand-written mapping during this task (kept in the repo, regenerated each gate). Classify each spec acceptance line as **VERIFIED (this machine)** or **DEFERRED (user on GPU box)**:

- Spec §12 acceptance 1 ("signed-in user submits a job via the SPA; real weights produce MP4/PNG") → the submit/queue/gallery-half is **VERIFIED** here via `e2e_spa.sh` + `smoke.sh` (fixture weights); lossy rendering with **real weights DEFERRED** → `docs/ops/gpu-wire-up.md` step 7 + verification ledger.
- §12 acceptance 2 ("progress streams over /ws; cancel + failure behave") → **VERIFIED** here (worker FIFO/cancel/failure paths in `controlplane_unit.sh` + smoke; WS upgrade asserted by `proxy_tls.sh`).
- §12 acceptance 3 ("deploys to k3s on gpu=true node; in-cluster smoke") → GPU-node half **DEFERRED**; the in-cluster smoke half is **VERIFIED** here via `system/tests/k8s-smoke.sh` + `k3s-regression.sh` on the CPU k3s cluster.
- §12 acceptance 4 ("MODELS_PATH is the only wiring") → **VERIFIED** here via `link-models.sh` fixture runs + `--write-hashes` test; real-hash pinning remains DEFERRED.
- §12 acceptance 5 ("two users each see only their own jobs/galleries") → **VERIFIED** here (isolation checks in `smoke.sh` (compose) and `k3s-regression.sh` (k3s)).
- §12 acceptance 6 ("SSO: sessions, logout, admin-flag from group membership") → **VERIFIED** here via `e2e_spa.sh` (`admin@test` → admin view; `user@test` → no admin routes).
- §5.2 caveat note ("I2V fp8/fp16 template disagreement") → **DEFERRED resolution** on the box at first `link-models.sh` mismatch (documented in runbook).

- [ ] **Step 3: Run the gate + commit**

```bash
bash system/scripts/gate.sh
git add system/scripts/gate.sh docs/acceptance-report.md
git commit -m "feat: final acceptance gate + report (verified/deferred classes)"
```
Expected: `GATE PASS` + report lists the verified set green and the deferred set pointing to the runbook. No "ALL CHECKS PASS" stub if any verified item fails.

---

### Task 6.5: Final self-review of the delivered system

**Files:**
- Review artifacts stored under `docs/` only.

**Interfaces:**
- Consumes: everything (repo state, running systems).
- Produces: a written "ship/no-ship" review note; fixes tracked via new commits (NOT amends).

- [ ] **Step 1: Fresh-eyes review (use the `code-review-and-quality` skill + `doubt-driven-development`)**

Dispatch a review (prefer `requesting-code-review`/`code-review-and-quality` skill) over:
- Secrets sweep (repeat Task 6.2 Step 1) + confirm `.env.example` placeholders, never real `OIDC_CLIENT_SECRET`/`SESSION_SECRET`/`POSTGRES_PASSWORD`.
- `shellcheck` all `system/scripts/*.sh` — zero errors, warnings reviewed.
- `docker compose config` on all compose files — no warnings.
- `kubectl kustomize` render parity between overlays.
- Cross-check every repo path named in `docs/README.md` exists (`while read p; do test -e "$p" || echo MISSING $p; done`).
- Re-run `e2e_spa.sh` cold (fresh sessions) — confirm no cross-user session bleed and `media_sid` cookie flags (HttpOnly/Secure/SameSite=Lax).
- Confirm manifest↔workflow lockstep still green post-hardening.

- [ ] **Step 2: Write `docs/REVIEW-<date>.md`**

Record: reviewer notes, items fixed, items accepted-with-reason, and final disposition (SHIP / SHIP-WITH-CAVEATS / NO-GO). Reference every spec deviation consciously.

- [ ] **Step 3: Commit the review + any fixes**

```bash
git add docs/REVIEW-*.md; git commit -m "docs: final review disposition"
```

---

## Phase 6 Exit Criteria

1. `docs/LICENSES.md` contains a dated determination with an explicit commercial GO/NO-GO (blocker gate satisfied).
2. `SECURITY.md` documents the posture (OIDC-only auth, TLS-only, non-root); the repo has zero committed secrets (grep battery empty modulo `.env.example` placeholders); `proxy_tls.sh` + `smoke.sh` still pass post-hardening.
3. `docs/README.md` + `docs/ops/runbook.md` reference only real commands (FreeIPA group admin, `pg_dump` backup, cert rotation); quickstart runs from a clean checkout on this machine via k3s.
4. `system/scripts/gate.sh` runs green on this machine and produces `docs/acceptance-report.md` mapping every spec acceptance line to evidence, each tagged **VERIFIED** or **DEFERRED** (no unclassified rows).
5. `docs/REVIEW-<date>.md` records a fresh-eyes review with SHIP disposition (or NO-GO + concrete blockers), consciously noting deferred items.
6. Everything committed; the repo's git log tells the full P0→P6 story with sensible granularity.