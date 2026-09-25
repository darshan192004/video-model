# License determination — model weights used by the media system

Dates and revs are pinned so re-verification is reproducible.

## Wan 2.2 (text-to-video + image-to-video)

- **Weight repo:** `Wan-AI/Wan2.2` (HuggingFace `Wan-AI/Wan2.2-T2V-14B`, `Wan-AI/Wan2.2-I2V-14B-480P`); ComfyUI consumption via the pinned `Comfy-Org` repack if used.
- **License:** Apache-2.0 (per the known Wan releases; verified at spec write time — spec §3 "Wan 2.2 Apache-2.0 (confirmed)").
- **Commercial use:** PERMITTED (Apache-2.0 grants commercial use). No separate license required.
- **Attribution:** keep the Apache-2.0 `NOTICE`/attribution if weights or derived assets are redistributed. Serving the model privately / internal use does not re-trigger redistribution obligations.
- **Determination:** Wan 2.2 → **GO** for commercial use.

## Qwen-Image-2.1 (text-to-image + image editing)

- **Weight repo:** `Qwen/Qwen-Image-2.1` (HuggingFace).
- **Captured at:** `LICENSE` file, commit `f52e6a529129fff6a994469561673ea45a84043d` (the "Create LICENSE" commit), captured 2026-09-25.
  URL: `https://huggingface.co/Qwen/Qwen-Image-2.1/blob/<captured-rev>/LICENSE`
  (ComfyUI repack `Comfy-Org/Qwen-Image-2.1` declares `license: other` / `license_name: qwen-research`, link → the Qwen LICENSE above.)
- **License type:** custom source-available license — the **Qwen Research License Agreement** (dated Sep 20, 2026), NOT an OSI open-source license and NOT Apache-2.0; `Non-Commercial` is defined as "for research or evaluation purposes only" (def. 1.i).

1. **Classification:** source-available, custom; not Apache/MIT/BSD.
2. **Commercial use: RESTRICTED.** Verbatim, sec. 2:
   - `2.a … royalty-free limited license … to use, reproduce, distribute, copy, create derivative works of, and make modifications to the Materials FOR NON-COMMERCIAL PURPOSES ONLY.`
   - `2.b You shall not use the Materials for any commercial purpose without obtaining a separate commercial license from us. If you wish to use the Materials commercially, you shall request a license from us at model-business@notice.qwencloud.com.`
3. **Attribution / trailing clauses:** §3.c requires distributing a copy of the Agreement and the notice `"Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) 2026 Hangzhou Tongyi Laboratory Technology Co., Ltd. All Rights Reserved."` with any redistribution; §4.b requires displaying "Built with Qwen"/"Improved using Qwen" when the model or its outputs are used to create/train/fine-tune a distributed AI model; §4.c forbids using "Qwen" as the primary name of derivatives (descriptive use like "fine-tuned from Qwen Image" is allowed).
4. **Transferability notes:**
   - **Outputs are not "Materials".** Qwen's own clarification (official Qwen Developers account, X post 2026-09; mirrored in model-page discussion #40): "Outputs are not part of the licensed Materials. Users retain the rights to images and other content they generate using the model." — i.e. generated images are the user's property. **However**, producing those images still required running the model, and §2.b bars using the Materials (the model/weights) for *any* commercial purpose without a separate license — so commercial content generation through the model is not licensed.
   - **Private/internal use** (the current deployment shape: self-hosted LAN box, org SSO, personal media use): non-commercial use is permitted on its face. Internal-use systems must still respect §3/§4 if anything is redistributed.
   - **Commercial launch** of a service that runs Qwen-Image-2.1 (including internal-ish but revenue/entity-driven commercial content output) requires a separate commercial license from Qwen.

## Determination (dating for the blocker gate)

> Determination (2026-09-25): Qwen-Image-2.1 is licensed under the **Qwen Research License Agreement** which **restricts** commercial use. Commercial launch is: **NO-GO** — §2.b requires a separate commercial license (request via `model-business@notice.qwencloud.com`) before any commercial purpose, including commercial content generation. Wan 2.2 (Apache-2.0) carries **GO** for commercial use.

### NO-GO mitigation (recorded per plan §6.1 step 3)

- **Deploy today as a private/internal media system** (non-commercial): compliant with the Qwen Research License. This is the current intent and unsatisfied-deferred items are tagged accordingly.
- **Before any commercial use of Qwen-Image-2.1:** obtain the separate commercial license from Qwen (email `model-business@notice.qwencloud.com`), OR swap the T2I/edit templates to an Apache-style/permissive T2I model. Wan 2.2 remains usable commercially under Apache-2.0 in either case.
- Gate behavior: the final `gate.sh` does not *run* the weights; it records this determination in `docs/LICENSES.md`. No automatic license enforcement — human gate only.