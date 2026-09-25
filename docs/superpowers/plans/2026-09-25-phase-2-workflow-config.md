# Phase 2 — Workflows + Param Schemas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author the four locked ComfyUI workflows (Qwen T2I, Qwen Image Edit, Wan 2.2 T2V A14B, Wan 2.2 I2V A14B) plus a CPU-safe `smoke.json` as **pure API-format** workflow JSONs, and author **`config/templates.schema.json`** — the typed, user-facing parameter surface per template (including image-input flags). Workflows + schema are mounted **server-side, read-only** into the control-plane (no ComfyUI user-dir installer, no App Mode / embedded-UI config). Validation: every workflow class exists in ComfyUI `/object_info` (internal) AND every schema param aligns with a real widget in its workflow.

**Architecture:** `system/workflows/*.json` are canonical API-format graphs (nodes keyed by `class_type` + `inputs`) the control-plane worker (Phase 1.5) resolves, injects user params into, and POSTs to `comfyui:8188/prompt`. `config/templates.schema.json` is the single source of the public param API (`/api/templates` reads it, `POST /api/jobs` validates against it). Both are mounted read-only into the control-plane container (compose volume; k8s ConfigMap in Phase 5). Nothing is installed into ComfyUI's `user/` dir; ComfyUI's own UI remains internal-only.

**Tech Stack:** ComfyUI built-in nodes only (native Wan/Qwen — **no** custom node repos), JSON, jq (schema validation), bash.

**Spec:** `docs/superpowers/specs/2026-09-25-comfyui-app-mode-media-system-design.md` — Phase 2 implements §5.2, §5.6 (server-side workflow load), §9, §10 P2.

## Global Constraints

- Workflows must use **native ComfyUI nodes only** (no custom-node repos, no Manager).
- Weight files referenced by these workflows are **exactly** the ones in the spec §5.2 table; filenames must match `config/models.manifest.json` (Phase 3) — keep the two in lockstep. The LoRA dir is spelled **`loras`** everywhere (no `"lo ras"` typos survive in any committed file).
- Qwen-Image-2.1 native nodes require ComfyUI backend ≥ 0.37.0 (Phase 0 image satisfies this).
- Frontend tag ≥ v1.41.13 remains **pinned for reproducibility only** — it is an internal implementation detail (ComfyUI UI is not user-facing; the SPA is). No App Mode / `extra.appMode` config in any committed file.
- All five workflows are **API format** (`{ "<node_id>": {"class_type": …, "inputs": …} }`), including `smoke.json` — the worker POSTs API prompts; no UI-format scaffolds.
- Workflows + schema are **server-side** files: mounted read-only into the control-plane at `/opt/media/workflows` and `/opt/media/config/templates.schema.json` (compose volume; k8s ConfigMap later). No `install-workflows.sh`, no writes into ComfyUI's `user/` dir.
- `smoke.json` must run on CPU without loading any ≥100MB weight file.
- No placeholders: every workflow file must be complete, parseable JSON at commit time.
- `templates.schema.json` exposes **all** model parameters for every user (full-control UX; only admins additionally see raw JSON). Image-input params (`qwen-edit`, `wan-i2v`) carry a `"type": "image"` flag routed to `/api/uploads`.
- **Test environment (this machine only):** no GPU, no real weights, no 3090-box access. The four production workflows are validated on this machine **at schema level only** — every `class_type` exists in `/object_info` on the pinned backend, and schema keys align with widgets. They are NEVER queued here; real execution is the deferred user step via the Phase 4 runbook. `smoke.json` executes end-to-end **through the control-plane** (POST `/api/jobs` → poll → gallery), the same path P3 uses.

---

## File Structure (Phase 2 creates)

- `system/workflows/qwen-t2i.json` — locked Qwen T2I **API-format** workflow.
- `system/workflows/qwen-edit.json` — locked Qwen edit **API-format** workflow (image input).
- `system/workflows/wan-t2v-a14b.json` — locked Wan T2V **API-format** workflow.
- `system/workflows/wan-i2v-a14b.json` — locked Wan I2V **API-format** workflow (image input).
- `system/workflows/smoke.json` — CPU-safe minimal **API-format** workflow.
- `system/config/templates.schema.json` — typed param schema per template (single source of truth for `/api/templates` + `/api/jobs` validation).
- `system/workflows/README.md` — provenance + param→widget contract (no blanks).
- `system/tests/workflow_schema.sh` — validates classes against `/object_info` (internal) + schema↔workflow alignment.

---

### Task 2.1: Vendor the official template JSONs (reference ground truth)

**Files:**
- Fetch (for reference, not committed in final form): official templates from `Comfy-Org/workflow_templates`.

**Interfaces:**
- Produces: knowledge of the exact loader wiring (`class_type`, model filename widget values) to author, trim, and pin our versions from — pinned to **Comfy-Org official** sources, not community mirrors.

- [ ] **Step 1: Download the four official template JSONs**

Run (from repo root):
```bash
mkdir -p /tmp/comfy_templates
cd /tmp/comfy_templates
for slug in \
  image_qwen_image_2_1_t2i \
  image_qwen_image_2_1_image_edit \
  video_wan2_2_14B_t2v \
  video_wan2_2_14B_i2v; do
  curl -fsSL "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/${slug}.json" -o "${slug}.json" \
    && echo "got ${slug}"
done
ls -l
```
Expected: four non-empty `.json` files. These are UI-format (nodes/links/positions) — used only as the source for node wiring; our committed files are API-format equivalents.

- [ ] **Step 2: Read and record the loader node wiring for each template**

Read each file and note, for commit into a reference note `system/workflows/README.md`:
- The exact `unet_name`/`weight_dtype`, `clip_name`/`text_encoder` widget values.
- The sampler node class (`KSampler`/`KSamplerAdvanced`), `steps`, `cfg`, `seed` widget names.
- The VAE loader + `VAEDecode`, and the save node class (`SaveImage` or MP4 save).
- For Wan: node classes `UNETLoader` (×2 high/low noise), `WanImageToVideo`/`EmptyHunyuanLatentVideo` latent creation, and how `length` is expressed.

> If a template uses a custom-node-*looking* class (e.g., `QwenImageTextEncode`, `WanImageToVideo`), record it — presence in `/object_info` on a 0.37+ build proves it is core at the pinned revision. Any truly missing class fails in Task 2.6 and forces re-pinning the backend revision.

- [ ] **Step 3: Write `system/workflows/README.md` (reference + provenance)**

Create `system/workflows/README.md`:

```markdown
# Workflows

Provenance: all four production workflows derive from the Comfy-Org official
template gallery `Comfy-Org/workflow_templates` (URLs pinned in tasks). They
are trimmed to a minimal fixed node set and stored as **API-format** graphs.
No custom node repos are required (native Wan/Qwen support, backend >= 0.37.0).

Workflows are **server-side**: the control-plane mounts this directory and
`config/templates.schema.json` read-only and resolves workloads from there.
ComfyUI's own UI is never user-facing. There is no App Mode config anywhere.

## Pinned weight wiring (must match config/models.manifest.json)

| Workflow | Diffusion model(s) | Text encoder | VAE | Save node |
|---|---|---|---|---|
| qwen-t2i | (fill from /object_info) | (fill) | (fill) | SaveImage |
| qwen-edit | (fill) | (fill) | (fill) | SaveImage |
| wan-t2v-a14b | high+low fp8 | umt5_xxl_fp8_e4m3fn_scaled | wan_2.1_vae | (fill) |
| wan-i2v-a14b | high+low fp16 | (fill) | (fill) | (fill) |

## Param contract

Every parameter a user can set lives in `config/templates.schema.json`, keyed
by workflow id, and binds to a workflow widget via `bind={node,widget}`.
Schema and workflow must be kept in lockstep; `system/tests/workflow_schema.sh`
enforces this.
```

- [ ] **Step 4: Commit the README + provenance notes (not the vendored UI JSONs)**

```bash
git add system/workflows/README.md
git commit -m "docs: workflow provenance and pinned wiring notes (server-side)"
```
The `/tmp/comfy_templates/*.json` reference files are NOT committed.

---

### Task 2.2: Author `qwen-t2i.json` (API format) + schema entry

**Files:**
- Create: `system/workflows/qwen-t2i.json`
- Create: (`config/templates.schema.json` entry; consolidated in Task 2.6)

**Interfaces:**
- Produces: an API-format graph whose terminal save node is `SaveImage`; exposes params `prompt`, `seed`, `steps`, `cfg`, `megapixels`.
- Consumes (at runtime): `qwen_image_2.1_int8_convrot.safetensors` + Qwen text encoder + Qwen VAE from `MODELS_PATH`.

- [ ] **Step 1: Convert and trim the official Qwen T2I graph to API format**

From the vendored `image_qwen_image_2_1_t2i.json`, produce the API-format graph. Node classes to expect (verbatim from `/object_info` of a 0.37+ build — **verify exact class names during Task 2.6**):
- `UNETLoader` — `unet_name: "qwen_image_2.1_int8_convrot.safetensors"`
- `CLIPLoader` — `clip_name: "qwen_image_2.1_text_encoder.f16.safetensors"`, `type: "qwen_image"` (verify)
- `VAELoader` — `vae_name: "qwen_image_2.1_vae.safetensors"` (verify)
- `CLIPTextEncodeQwenImage` or `QwenImageTextEncode` (verify class name) — positive/negative
- `KSampler` — `steps`, `cfg`, `seed`, `sampler_name`, `scheduler`
- `EmptyLatentImage` / `EmptyHunyuanLatentImage` with megapixel-driven `width`/`height`
- `VAEDecode`, `SaveImage`

Create `system/workflows/qwen-t2i.json` in canonical API-format shape:

```json
{
  "1": { "class_type": "UNETLoader", "inputs": { "unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default" } },
  "2": { "class_type": "CLIPLoader", "inputs": { "clip_name": "qwen_image_2.1_text_encoder.f16.safetensors", "type": "qwen_image" } },
  "3": { "class_type": "VAELoader", "inputs": { "vae_name": "qwen_image_2.1_vae.safetensors" } },
  "4": { "class_type": "CLIPTextEncodeQwenImage", "inputs": { "clip": ["2", 0], "text": "{PARAM.prompt}" } },
  "5": { "class_type": "EmptyLatentImage", "inputs": { "width": "{PARAM.width}", "height": "{PARAM.height}" } },
  "6": { "class_type": "KSampler", "inputs": { "model": ["1", 0], "positive": ["4", 0], "negative": ["7", 0], "latent_image": ["5", 0], "seed": "{PARAM.seed}", "steps": "{PARAM.steps}", "cfg": "{PARAM.cfg}", "sampler_name": "euler", "scheduler": "normal" } },
  "7": { "class_type": "CLIPTextEncodeQwenImage", "inputs": { "clip": ["2", 0], "text": "{PARAM.negative_prompt}" } },
  "8": { "class_type": "VAEDecode", "inputs": { "samples": ["6", 0], "vae": ["3", 0] } },
  "9": { "class_type": "SaveImage", "inputs": { "images": ["8", 0], "filename_prefix": "qwen-t2i" } }
}
```

> `{PARAM.<name>}` is the control-plane's injection marker (Task 2.6 defines the resolution contract; `megapixels` resolves to concrete `width`/`height` in the schema's value map). The exact node set may shift with the verified class names; keep the marker convention stable.

- [ ] **Step 2: Define the `qwen-t2i` schema entry**

Enter this block into `config/templates.schema.json` (assemble whole file in Task 2.6):

```json
"qwen-t2i": {
  "display": "Qwen Image 2.1 — Text to Image",
  "workflow": "qwen-t2i.json",
  "params": {
    "prompt":          { "type": "string", "label": "Prompt", "required": true },
    "negative_prompt": { "type": "string", "label": "Negative prompt", "default": "" },
    "seed":            { "type": "int",    "label": "Seed", "min": 0, "max": 4294967295, "default": 999, "bind": { "node": "KSampler", "widget": "seed" } },
    "steps":           { "type": "int",    "label": "Steps", "min": 1, "max": 50, "default": 20, "bind": { "node": "KSampler", "widget": "steps" } },
    "cfg":             { "type": "float",  "label": "CFG", "min": 1.0, "max": 20.0, "default": 4.0, "bind": { "node": "KSampler", "widget": "cfg" } },
    "megapixels":      { "type": "enum",   "label": "Megapixel target", "values": [1.0, 2.0, 3.0, 4.0], "default": 1.0 }
  }
}
```

- [ ] **Step 3: Verify JSON parses**

Run:
```bash
jq empty system/workflows/qwen-t2i.json && echo "valid json"
python3 -c "import json;d=json.load(open('system/workflows/qwen-t2i.json'));print('nodes',len(d))"
```
Expected: `valid json`, `nodes 9` (or the actual count).

- [ ] **Step 4: Commit**

```bash
git add system/workflows/qwen-t2i.json
git commit -m "feat: qwen image t2i workflow (api format)"
```

---

### Task 2.3: Author `qwen-edit.json` (API format) + schema entry

**Files:**
- Create: `system/workflows/qwen-edit.json`

**Interfaces:**
- Produces: API graph; terminal `SaveImage`; params `prompt`, `image` (image-input flag), `seed`, `steps`, `cfg`.
- Consumes (runtime): same Qwen weights as T2I; image input injected via `LoadImage` fed by `/api/uploads` staging.
- Behavior contract: output dimensions must match the input image (template uses `GetImageSize` → `EmptyLatentImage`).

- [ ] **Step 1: Convert/trim the official edit template to API format**

From `image_qwen_image_2_1_image_edit.json`. Node classes to expect (subset):
- `UNETLoader`, `CLIPLoader`, `VAELoader` (same files as T2I),
- `LoadImage` (its `image` widget = `{PARAM.image}`),
- `GetImageSize` → feeds `EmptyLatentImage` `width`/`height`,
- the Qwen text-encode node, `KSampler`, `VAEDecode`, `SaveImage`.

Create `system/workflows/qwen-edit.json` with the same API-format shape and `{PARAM.*}` marker convention; `LoadImage` sits in the sampler path end-to-end.

- [ ] **Step 2: Define the `qwen-edit` schema entry**

```json
"qwen-edit": {
  "display": "Qwen Image 2.1 — Image Edit",
  "workflow": "qwen-edit.json",
  "params": {
    "image":           { "type": "image", "label": "Source image", "required": true, "bind": { "node": "LoadImage", "widget": "image" } },
    "prompt":          { "type": "string", "label": "Edit instruction", "required": true, "bind": { "node": "CLIPTextEncodeQwenImage", "widget": "text" } },
    "negative_prompt": { "type": "string", "label": "Negative prompt", "default": "" },
    "seed":            { "type": "int",    "label": "Seed", "min": 0, "max": 4294967295, "default": 999, "bind": { "node": "KSampler", "widget": "seed" } },
    "steps":           { "type": "int",    "label": "Steps", "min": 1, "max": 50, "default": 20, "bind": { "node": "KSampler", "widget": "steps" } },
    "cfg":             { "type": "float",  "label": "CFG", "min": 1.0, "max": 20.0, "default": 4.0, "bind": { "node": "KSampler", "widget": "cfg" } }
  }
}
```

- [ ] **Step 3: Verify JSON parses** (same jq/python check as Task 2.2)

- [ ] **Step 4: Commit** — `feat: qwen image edit workflow (api format)`.

---

### Task 2.4: Author `wan-t2v-a14b.json` and `wan-i2v-a14b.json` + schema entries

**Files:**
- Create: `system/workflows/wan-t2v-a14b.json`
- Create: `system/workflows/wan-i2v-a14b.json`

**Interfaces:**
- Produces: two API graphs; both save via the native MP4/`SaveVideo` path (verify node class in `/object_info`; fall back to frame-based `SaveImage` if the pinned template does so — record the choice in `workflows/README.md`).
- Consumes (runtime): Wan 2.2 fp8 (T2V) / fp16 (I2V) high+low noise diffusion models, `umt5_xxl_fp8_e4m3fn_scaled` TE, `wan_2.1_vae`.
- Wan latent: `EmptyHunyuanLatentVideo` (`length`, `width`/`height`) or `WanImageToVideo` (I2V) — params exposed.

- [ ] **Step 1: Convert `video_wan2_2_14B_t2v.json` → `wan-t2v-a14b.json`**

Map (subset, verify in `/object_info`):
- `UNETLoader` low noise = `wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors`
- `UNETLoader` high noise = `wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors`
- TE = `umt5_xxl_fp8_e4m3fn_scaled.safetensors`
- VAE = `wan_2.1_vae.safetensors`
- latent = `EmptyHunyuanLatentVideo` (`length`, `width`/`height`)
- sampler = `KSampler` (steps/seed exposed)

Params:

```json
"wan-t2v-a14b": {
  "display": "Wan 2.2 14B — Text to Video",
  "workflow": "wan-t2v-a14b.json",
  "params": {
    "prompt":    { "type": "string", "label": "Video prompt", "required": true },
    "negative_prompt": { "type": "string", "label": "Negative prompt", "default": "" },
    "seed":      { "type": "int", "label": "Seed", "min": 0, "max": 4294967295, "default": 999, "bind": { "node": "KSampler", "widget": "seed" } },
    "steps":     { "type": "int", "label": "Steps", "min": 1, "max": 50, "default": 20, "bind": { "node": "KSampler", "widget": "steps" } },
    "cfg":       { "type": "float", "label": "CFG", "min": 1.0, "max": 20.0, "default": 5.0, "bind": { "node": "KSampler", "widget": "cfg" } },
    "frames":    { "type": "int", "label": "Frames", "min": 17, "max": 121, "step": 8, "default": 81, "bind": { "node": "EmptyHunyuanLatentVideo", "widget": "length" } },
    "resolution": { "type": "enum", "label": "Resolution", "values": [[832, 480], [1280, 720]], "default": [832, 480], "bind": { "node": "EmptyHunyuanLatentVideo", "widget": "width" } }
  }
}
```

> `resolution` maps the enum to both `width` and `height` at injection time (schema-level `bind` targets `width`; the value resolver fills `height` from the SAME selected tuple — document this in `workflows/README.md`).

- [ ] **Step 2: Convert `video_wan2_2_14B_i2v.json` → `wan-i2v-a14b.json`**

Same wiring, but:
- Diffusion models = `wan2.2_i2v_high_noise_14B_fp16.safetensors` + `wan2.2_i2v_low_noise_14B_fp16.safetensors`
- Feeds from `LoadImage` (`{PARAM.image}`) via the Wan I2V latent node (verify class; e.g., `WanImageToVideo`).

Params:

```json
"wan-i2v-a14b": {
  "display": "Wan 2.2 14B — Image to Video",
  "workflow": "wan-i2v-a14b.json",
  "params": {
    "image":    { "type": "image", "label": "First frame", "required": true, "bind": { "node": "LoadImage", "widget": "image" } },
    "prompt":   { "type": "string", "label": "Motion prompt", "required": true },
    "negative_prompt": { "type": "string", "label": "Negative prompt", "default": "" },
    "seed":     { "type": "int", "label": "Seed", "min": 0, "max": 4294967295, "default": 999, "bind": { "node": "KSampler", "widget": "seed" } },
    "steps":    { "type": "int", "label": "Steps", "min": 1, "max": 50, "default": 31, "bind": { "node": "KSampler", "widget": "steps" } },
    "cfg":      { "type": "float", "label": "CFG", "min": 1.0, "max": 20.0, "default": 5.0, "bind": { "node": "KSampler", "widget": "cfg" } },
    "frames":   { "type": "int", "label": "Frames", "min": 17, "max": 121, "step": 8, "default": 81, "bind": { "node": "WanImageToVideo", "widget": "length" } }
  }
}
```

> **I2V FP16 caveat (spec §5.2):** the official guide text names fp8 files while the download cards name fp16 files. The graph here pins the **fp16** names; if the workflow template's wiring references fp8 names, trust the loader wiring (it defines what exists on disk). Reconcile with `models.manifest.json` in Phase 3 so loader + manifest always agree.

- [ ] **Step 3: Verify JSON parses for both** (jq + node-count check)

- [ ] **Step 4: Update `workflows/README.md` pinned-wiring table** (fill the blanks; record resolution-enum→width/height resolver note)

- [ ] **Step 5: Commit** — `feat: wan 2.2 t2v/i2v workflows (api format)`.

---

### Task 2.5: Author `smoke.json` (CPU-safe API workflow)

**Files:**
- Create: `system/workflows/smoke.json`
- Create: `system/tests/input/smoke.png` (1×1 black PNG)

**Interfaces:**
- Produces: a `LoadImage(smoke.png) → InvertImage → SaveImage` API graph that exercises `/prompt` → `/ws` → `/history` → `/view` through the control-plane with **zero** model weights, instantly on CPU.

- [ ] **Step 1: Write the smoke PNG and `smoke.json`**

```bash
mkdir -p system/tests/input
printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x91\xed\xe8\x8c\x00\x00\x00\x00IEND\xaeB`\x82' > system/tests/input/smoke.png
file system/tests/input/smoke.png   # expect "PNG image data, 1 x 1"
```

Create `system/workflows/smoke.json` (**API format** — the worker posts it verbatim):

```json
{
  "1": { "class_type": "LoadImage",  "inputs": { "image": "smoke.png" } },
  "2": { "class_type": "InvertImage", "inputs": { "image": ["1", 0] } },
  "3": { "class_type": "SaveImage",  "inputs": { "images": ["2", 0], "filename_prefix": "smoke-out" } }
}
```

- [ ] **Step 2: Define the `smoke` schema entry**

```json
"smoke": {
  "display": "Smoke test",
  "workflow": "smoke.json",
  "params": {}
}
```

- [ ] **Step 3: Verify JSON parses**

- [ ] **Step 4: Commit** — `feat: cpu-safe smoke workflow (api format)`.

---

### Task 2.6: Param schema + server-side wiring + validation

**Files:**
- Create: `system/config/templates.schema.json` (consolidates the per-task entries)
- Create: `system/tests/workflow_schema.sh`
- Deliver: control-plane mount wiring (compose) for `/opt/media/workflows` + `/opt/media/config`

**Interfaces:**
- Consumes: `system/workflows/*.json`, running compose stack (control-plane reaches ComfyUI on the internal network).
- Produces: a validated schema the control-plane serves via `/api/templates` and validates `POST /api/jobs` against; a regression script exit 0 when classes exist and params align.

- [ ] **Step 1: Assemble `config/templates.schema.json`**

Merge the per-workflow entries from Tasks 2.2–2.5 into one top-level file:

```json
{
  "$comment": "Typed param schema per workflow id. 'bind.node/widget' must resolve to a real node class + widget in the workflow file. 'type:image' params are uploaded via /api/uploads.",
  "templates": {
    "qwen-t2i":      { /* Task 2.2 */ },
    "qwen-edit":     { /* Task 2.3 */ },
    "wan-t2v-a14b":  { /* Task 2.4 */ },
    "wan-i2v-a14b":  { /* Task 2.4 */ },
    "smoke":         { /* Task 2.5 */ }
  }
}
```

`jq empty system/config/templates.schema.json && echo "valid json"`.

**Injection contract (control-plane worker, documented here and in `workflows/README.md`):**
- A `{PARAM.<name>}` marker in a workflow input is replaced with the validated user value.
- `type:image` params: worker stages the uploaded file (`UPLOAD_ROOT/<user>/…`) into ComfyUI's input dir (shared volume) and substitutes the resulting filename into `LoadImage`.
- Enum params resolve via the schema `values` array (preserving tuples like `resolution` → `[width, height]`).
- Known normalize: if any workflow widget references a model dir, use the exact manifest spelling `loras` (no typo).

- [ ] **Step 2: Mount workflows + schema into the control-plane (compose)**

Add to `system/deploy/compose/base.yml` `controlplane` service:

```yaml
    volumes:
      - ./../../workflows:/opt/media/workflows:ro
      - ./../../config:/opt/media/config:ro
```

and to the `Dockerfile` runtime stage keep `WORKDIR /opt/media`. The worker resolves template → `<GALLERY?>` workflow by reading `/opt/media/workflows/<workflow>.json`. (k8s: ConfigMap with the same two mount paths — Phase 5.)

- [ ] **Step 3: Write `system/tests/workflow_schema.sh`**

Fetch `/object_info` **internally** (ComfyUI is not on the public nginx route), then validate classes + schema alignment:

```bash
#!/usr/bin/env bash
# Validate workflows: (1) every class_type exists in ComfyUI /object_info
# (fetched on the internal network), (2) every schema param 'bind' resolves to
# a real widget on a node of that class, (3) no appMode / UI-format / "lo ras"
# leakage in committed workflow + schema files.
# Usage: bash workflow_schema.sh            # compose: one-shot curl on the net
#        NO_RESOLVE=1 bash workflow_schema.sh  # k3s: kubectl port-forward path (P5)
set -euo pipefail

SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # absolute system/
NET="${COMFY_NET:-comfy-internal}"
COMIFY_URL="http://comfyui:8188"

# Fetch object_info from inside the compose network via a throwaway curl container.
compose_net=$(cd "$SYS" && docker compose -f deploy/compose/base.yml config --networks 2>/dev/null | grep -oE '^  \w+:' | head -1 | tr -d ' :')
docker run --rm --network "${NET}" curlimages/curl:8.9.1 -s "${COMIFY_URL}/object_info" -o /tmp/object_info.json
[[ -s /tmp/object_info.json ]] || { echo "object_info fetch failed (compose net ${NET})"; exit 1; }

SCHEMA="$SYS/config/templates.schema.json"
fail() { echo "ASSERT FAIL: $*" >&2; exit 1; }

# 1) classes exist
for wf in "$SYS"/workflows/qwen-t2i.json "$SYS"/workflows/qwen-edit.json \
          "$SYS"/workflows/wan-t2v-a14b.json "$SYS"/workflows/wan-i2v-a14b.json \
          "$SYS"/workflows/smoke.json; do
  echo "-- classes in ${wf#$SYS/}"
  jq -r 'to_entries[].value.class_type | select(. != null)' "$wf" | while read -r cls; do
    jq -e --arg c "$cls" 'has($c)' /tmp/object_info.json >/dev/null \
      || { echo "MISSING class: $cls"; exit 1; }
  done || fail "unknown class in $wf"
  echo "  ok"
done

# 2) schema->workflow alignment
for tid in $(jq -r '.templates | keys[]' "$SCHEMA"); do
  wfile="$(jq -r --arg t "$tid" '.templates[$t].workflow' "$SCHEMA")"
  wf="$SYS/workflows/$wfile"
  [[ -f "$wf" ]] || fail "workflow $wfile missing for template $tid"
  echo "-- schema alignment: $tid"
  jq -r --arg t "$tid" '.templates[$t].params | to_entries[] | select(.value.bind != null) | "\(.key)\t\(.value.bind.node)\t\(.value.bind.widget)"' "$SCHEMA" \
    | while IFS=$'\t' read -r p node widget; do
        jq -e --arg n "$node" --arg w "$widget" \
          '[to_entries[].value | select(.class_type==$n)] | any(.inputs | has($w))' "$wf" >/dev/null \
          || fail "param $p binds $node.$widget not in $wfile"
      done
  echo "  ok"
done

# 3) leakage guards
rg -l "appMode|defaultView|nodes\"\s*:" "$SYS/workflows" 2>/dev/null && fail "UI-format/appMode content leaked into workflows/"
rg -n '"lo ras"|lo ras' "$SYS"/workflows "$SYS"/config && fail 'misspelled "lo ras" present'

echo "WORKFLOW/SCHEMA: all assertions passed"
```

> The one-shot curl uses the compose network; in k3s (P5) the same script is run with the object_info fetch swapped to `kubectl port-forward`. Keep the fetch step parameterized (`COMFY_FETCH` hook) rather than baking compose in.

- [ ] **Step 4: Run workflow_schema.sh against the compose stack**

```bash
cd /home/darshan.parmar/Desktop/video-model/system
docker compose -f deploy/compose/base.yml -f deploy/compose/compose.override.cpu.yml up -d
bash tests/workflow_schema.sh
```
Expected: all `ok`; exit 0. Fix any `MISSING class` by correcting the workflow JSON (or re-pin backend revision if truly absent from `/object_info`).

- [ ] **Step 5: Validate smoke through the control-plane (finalized schema)**

With the stack up (control-plane + postgres + comfyui CPU + dex-test from Phase 1.5), submit the smoke template via the control-plane API and assert a gallery result:

```bash
cd /home/darshan.parmar/Desktop/video-model/system
# reuse the e2e login helper (Phase 1.5) to get an admin session cookie
SID=$(bash tests/lib_login.sh admin@test adminpass)   # helper from P1.5 e2e
JOB=$(curl -skb "$SID" -H 'Content-Type: application/json' \
  -d '{"template_id":"smoke","params":{}}' \
  --resolve media.local:443:127.0.0.1 https://media.local:443/api/jobs | jq -r .job_id)
# poll until success (worker executes LoadImage->InvertImage->SaveImage via comfyui)
for i in $(seq 1 30); do
  st=$(curl -skb "$SID" --resolve media.local:443:127.0.0.1 https://media.local:443/api/jobs/$JOB | jq -r .status)
  [ "$st" = "success" ] && { echo "smoke job succeeded"; exit 0; }
  [ "$st" = "failed" ] && { echo "smoke job FAILED"; curl -skb "$SID" --resolve media.local:443:127.0.0.1 https://media.local:443/api/jobs/$JOB; exit 1; }
  sleep 1
done
echo "timed out waiting for smoke job"; exit 1
```

> `lib_login.sh` is created in P1.5's e2e task (extract the login sequence into a sharable helper); the smoke submit+poll sequence is what Phase 3's `smoke.sh` generalizes.

- [ ] **Step 6: Commit**

```bash
git add system/config/templates.schema.json system/tests/workflow_schema.sh system/deploy/compose/base.yml
git commit -m "feat: typed param schema, server-side workflow mount, schema validation"
```

---

## Phase 2 Exit Criteria

1. All five workflow JSONs exist as valid **API-format** JSON, contain **no** `appMode`/UI-format fields, and are committed.
2. `system/config/templates.schema.json` is valid JSON, typed per param, with `smoke` + the four production entries; every param that should expose a raw model setting appears.
3. `system/tests/workflow_schema.sh` passes: all classes present in `/object_info` on the pinned backend AND every `bind` resolves to a real widget AND no `"lo ras"` typo leaks.
4. `smoke.json` executes end-to-end **through the control-plane** (`/api/jobs` → `success` → gallery file), confirming the finalized schema + injection contract on this machine.
5. Workflows + schema are mounted read-only into the control-plane (`/opt/media/workflows`, `/opt/media/config`); no `install-workflows.sh` / user-dir writes exist anywhere.
6. Production workflows are validated by schema + shape only on this machine; real execution remains the deferred user step (Phase 4 runbook), re-asserted as shape checks in k3s (Phase 5).
7. `workflows/README.md` documents provenance, pinned wiring, and the param/`bind` contract with no blanks.
8. No custom-node repos introduced; image revisions unchanged from Phase 0 (control-plane image rebuilt only if its mounts/config changed).