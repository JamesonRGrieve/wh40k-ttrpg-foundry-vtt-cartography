# Cartography TODO

Open work, in priority order. Items are removed from this file as they
are completed (not merely struck through).

## 1. ComfyUI image-classification driver

Server reachable at `http://198.51.100.11:8188` (ComfyUI 0.18.1, RTX 3090,
~23 GB VRAM free). 989 nodes installed but **no captioner / VLM custom
nodes** — the install is currently configured for image *generation*, not
classification. Available vision nodes are limited to CLIPVisionEncode /
CLIPVisionLoader (zero-shot via cosine similarity, but no prebuilt
similarity-scoring node).

### Step 1a — install a captioner custom node on the ComfyUI server

Pick one. In order of recommendation:

- **`ComfyUI-Florence2`** — Microsoft Florence-2 base/large; supports
  `<MORE_DETAILED_CAPTION>` and `<DENSE_REGION_CAPTION>` plus
  classification via `<OD>`. Small (~1 GB), fast, runs comfortably on a
  3090. Repo: <https://github.com/kijai/ComfyUI-Florence2>.
- **`ComfyUI-WD14-Tagger`** — booru-style multi-label tagger; great for
  category tags but irrelevant for our domain (anime-trained), skip.
- **`ComfyUI-Janus-Pro`** or **`ComfyUI-LLM-API`** — heavier VLMs; only
  worth it if Florence-2 accuracy is insufficient.

Install Florence-2, restart ComfyUI, confirm via `/object_info` that
`Florence2Run` (or similar) appears.

### Step 1b — author the workflow

A workflow JSON that, given a single image, runs Florence-2 with three
prompts:

1. Region/orientation prompt → maps Florence-2's spatial reasoning to one
   of {north, south, east, west, top-down, isometric, null}.
2. Damage/activation prompt → maps text response to one of {intact,
   damaged, destroyed, active, inactive, null}.
3. Category prompt → free-text caption parsed into our tag vocabulary
   (furniture, weapon, container, document, machinery, ...).

Save the JSON in this directory as `comfy_classify_workflow.json`.

### Step 1c — write `classify_stamps.py`

For each `stamps/*.png` whose sidecar's `classified_at` is null (or
`--force`), POST the workflow with the image to `/prompt`, poll
`/history/<id>` for completion, parse the outputs, and write the three
classification fields back into the sidecar plus `classified_at` /
`classified_by`. Must be idempotent and resumable.

### Step 1d — variant `group_id` assignment

Same in-fiction object across orientations / states should share
`group_id`. Approach: run Florence-2's CLIPVision embedding over every
stamp, cluster by cosine similarity above a tunable threshold, assign a
UUID per cluster. Manual override remains possible by editing sidecars
(the writer skips already-set fields).

## 2. LoRA training corpus (see ADR-002)

Closes the Gemini-only loop: train style-locked LoRAs on the extracted
corpus so the generation-configured ComfyUI server can expand the library
locally. Decision record and rationale in `ADR-002-lora-training-corpus.md`.

**Hard dependency: §1 must run first** — captions are built from the
classified sidecars (`description`, `tags`, `orientation`, `state`,
`group_id`); no separate labelling pass.

### Step 2a — corpus builder `build_lora_corpus.py`

For a named LoRA, query sidecars for its slice (category / orientation /
state / group_id per ADR-002), reuse §1d CLIPVision embeddings to drop
near-duplicate stamps, and emit
`lora-corpus/<lora-name>/{images,captions}` + `manifest.json` with
stamp→caption→source provenance. Idempotent; logs every excluded stamp
with a reason (no silent drops). Never writes into Foundry paths.

### Step 2b — gap report

Same tool, `--report` mode: list target slices with < ~60 unique images.
Each thin slice becomes a new TODO item + a Gemini prompt-recipe entry so
grids can be authored to fill it and re-enter the normal extract→classify
flow.

### Step 2c — pick & install a trainer node on the ComfyUI host

SDXL LoRA is the default (fits 24 GB comfortably, well-tooled). Confirm a
training custom node loads on ComfyUI 0.18.1 without disturbing the
generation/Florence-2 config. Flux-dev LoRA is a later quality bump.

### Step 2d — train tiers in order

Tier 0 `dhcarto-style` first (prerequisite; evaluate before proceeding),
then Tier 1 projection LoRAs, then Tier 2 `dhcarto-state` (unblocks the
ADR-001 variant-generation gap), then Tier 3 domain LoRAs as corpus depth
allows.

Acceptance: a held-out prompt through `dhcarto-style` produces an asset a
reviewer cannot distinguish from a hand-picked corpus stamp; it survives
`extract_stamps.py` cleanly and browses in Mass Edit.

## 3. Deploy stamps as a Foundry module

`build_mass_edit_pack.py` emits `mass-edit-presets.json` referencing
asset paths under `modules/dh-cartography/stamps/`. The corresponding
module needs to exist on the Foundry server. Plan:

- Create a tiny module shell `dh-cartography/` with a minimal
  `module.json` (id, version, V14 compatibility, no scripts/styles, just
  a static asset directory).
- Stage the 633 PNGs under `dh-cartography/stamps/`.
- Either zip + install via Foundry UI, or push directly into
  `Data/modules/dh-cartography/` on the VTT CT (path is in
  `../../VTT_WIKI.md`).
- After install, import `mass-edit-presets.json` via Mass Edit's Preset
  Browser → Import.

Acceptance: a stamp is browseable in Mass Edit's Preset Browser, draggable
onto a scene, and renders correctly.

## 4. Install Baileywiki Mass Edit on the VTT

Audit complete — server reachable at V14.359 with world `dark-heresy`,
system `wh40k-rpg`. `lib-wrapper` is already installed (per
`../../VTT_WIKI.md`); `multi-token-edit` is NOT. Install it:

- Manifest URL: `https://github.com/Aedif/multi-token-edit/releases/latest/download/module.json`
- Install via Foundry's Add-on Modules → Install Module → paste manifest URL.
- Requires the world to be shut down or the install must happen via
  /setup; do NOT do this during a live session.
- After install, verify `compatibility.verified` and that the module
  loads without console errors on world boot.
