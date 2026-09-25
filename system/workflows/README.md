# Kanonical Workflows (API format)

Five graphs in ComfyUI **API format** (no UI-format keys: `nodes`/`links`/`last_node_id` MUST NOT
appear). Published at `/opt/media/workflows/` (read-only mount). Sampled on this machine via the
mock backend; `/object_info` class verification + weight pinning is reconciled at the phase-3
manifest/weight-link pass and verified in the final consolidated run.

`{PARAM.<name>}` markers are injected by the control-plane worker at submit time. A param that is
not supplied by the caller falls back to its schema default (`config/templates.schema.json`); an
enum whose selected value encodes resolution injects BOTH `{PARAM.width}` and `{PARAM.height}`
(width from the tuple entry, height from the same tuple). `{PARAM.image}` is staged into ComfyUI's
shared input dir (the uploaded file's owner subdir under `/opt/media/uploads` → filename is mounted
under `/data/comfy-input`).

## Node/class references (pinned target)

| class | purpose |
|---|---|
| `UNETLoader` | weight loader (diffusion model) |
| `CLIPLoader` | text encoder loader (`type`: `qwen_image` / `wan`) |
| `VAELoader` | VAE loader |
| `CLIPTextEncode` / `CLIPTextEncodeQwenImage` | prompt encoder |
| `KSampler` | sampling (euler) |
| `VAEDecode` | latent → pixels |
| `SaveImage` | output PNG (writes to `/opt/media/output`) |
| `EmptyLatentImage` | latent canvas |
| `EmptyHunyuanLatentVideo` | video latent canvas |
| `WanImageToVideo` | i2v latent init |
| `LoadImage` / `GetImageSize` | uploaded-source input |

All nodes are ComfyUI built-ins. NO custom node repositories are required.

## Per-workflow

| file | classes | notes |
|---|---|---|
| `smoke.json` | LoadImage→InvertImage→SaveImage | CPU, no weights. `filename_prefix` = `{PARAM.seed}` (default `smoke-out`) so the e2e broken-workflow fixture can inject a rejection substring. |
| `qwen-t2i.json` | UNETLoader, CLIPLoader(qwen_image), VAELoader, CLIPTextEncodeQwenImage x2, EmptyLatentImage, KSampler, VAEDecode, SaveImage | width/height <- `megapixels` resolution table. |
| `qwen-edit.json` | LoadImage, GetImageSize, EmptyLatentImage, UNETLoader, CLIPLoader(qwen_image), VAELoader, CLIPTextEncodeQwenImage x2, KSampler, VAEDecode, SaveImage | canvas = source image size. |
| `wan-t2v-a14b.json` | UNETLoader low+high, CLIPLoader(wan), VAELoader, CLIPTextEncode x2, EmptyHunyuanLatentVideo, KSampler x2 (low 0.8 denoise → high 1.0), VAEDecode, SaveImage | two-stage cascade; `{PARAM.width}/{PARAM.height}` <- `resolution` tuple. |
| `wan-i2v-a14b.json` | UNETLoader high+low, CLIPLoader(wan), VAELoader, LoadImage, CLIPTextEncode x2, WanImageToVideo, KSampler x2, VAEDecode, SaveImage | two-stage cascade. |

**Deferred decisions (recorded, not declined):** MP4/`SaveVideo` export for video templates is
pinned later (Phase 4); this pass commits `SaveImage` (mock-composable, deterministic). Weights
(`unet_name`/`clip_name`/`vae_name`) are the phase-3 planned filenames and are reconciled against
the manifest before the final run.

## Validation (this pass, no runtime)

- JSON well-formed (json.tool) - verified above.
- `tests/workflow_schema.sh` validates: class_type membership (`/object_info` at the pinned backend
  — runs in the final pass), `bind` target widget presence per schema entry, no UI-format keys via
  rg. Wired into `make unit`'s static block and `make e2e`.
- `{"templates": {...}}` shape + typed params self-validated by the schema's `$schema`.