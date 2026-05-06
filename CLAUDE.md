# Cartography Asset Pipeline — Working Directives

This directory turns Gemini-generated stamp-grid PNGs into a Foundry V14
tile/asset library for the Solenne campaign.

End-to-end flow:

```
PNG grids ─►  extract_stamps.py     ─►  stamps/<stem>_NN.png
              make_sidecars.py      ─►  stamps/<stem>_NN.yaml
              classify_stamps.py    ─►  populates name/description/tags/orientation/state
              assign_groups.py      ─►  populates group_id (variant clustering)
              build_mass_edit_pack  ─►  mass-edit-presets.json
              stage_module.py       ─►  dh-cartography/stamps/  (hardlinks)
              deploy.sh cartography ─►  rsync to Foundry server
              (manual)              ─►  Mass Edit Preset Browser → Import
```

Every script has an inline `# /// script` block declaring its uv
dependencies; run with `uv run <script>.py`.

---

## External services

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Foundry VTT | `https://vtt.jamesonrgrieve.ca` (V14 Build 359, world `dark-heresy`, system `wh40k-rpg`) | Cartography deploy target. Modules under `/opt/foundry-vtt/data/Data/modules`. |
| ComfyUI | `http://198.51.100.11:8188` (v0.18.1, RTX 3090 24 GB) | Florence-2 captioning + CLIP-ViT-H + IPAdapter image embedding. Manager v3.39.2 with security level locked (no remote installs). |
| Kanka | `https://wiki.jamesonrgrieve.ca` | Out of scope for cartography. |

Credentials and CT addresses live in `../../VTT_WIKI.md`.

---

## Source image expectations

- Grids are NOT uniformly sized. Cell dimensions vary within a single
  source image and definitely across images.
- Grid lines (gutters) are NOT always contiguous; a stamp can bleed into
  what would otherwise be a separator.
- Gutter color is image-dependent: most images use a near-white or cream
  background; some use medium gray; some dark-toned sets use a dark
  gutter where stamp content is visually similar in tone. The extractor
  samples the gutter color from the image border.
- `extract_stamps.py` therefore uses **connected-components on a
  not-gutter mask** with **4-connectivity for stamp components** (so
  diagonally-touching stamps don't fuse at grid intersections) and
  **8-connectivity for the background hole-detection pass**. Per-image
  `GUTTER_TOL` is **auto-tuned** by trying a candidate set and picking
  the tolerance that yields the most "stamp-plausible" components.
  Small interior gutter-colored holes are filled (capped by
  `MAX_HOLE_AREA`) so stamps with internal gutter-toned regions don't
  develop alpha craters.

---

## Foundry plugin selection — Baileywiki Mass Edit (`multi-token-edit`)

It's the only V14-loadable module providing a preset/tile browser with
folder + tag indexing, drag-to-scene placement, and prefab/variant
grouping. Manifest:
`compatibility: { minimum: 13, verified: 13 }` with no `maximum`, so it
loads cleanly on V14 Build 359; depends on `lib-wrapper` (already
installed). Repo: <https://github.com/Aedif/multi-token-edit>.

Pair with the already-installed `monks-active-tiles` for state-machine
texture swaps (`Image Cycle` action) — see ADR-001 for variant cycling.

### Mass Edit preset JSON schema (verified against source)

The preset pack is a **flat top-level JSON array** of preset objects —
no wrapper. Required fields per preset (validator in
`browser/browserApp.js:902-917`):

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Auto if omitted; we generate stable per-stamp ids. |
| `name` | string | Displayed in browser. We use `"<Canonical> — <state>, <orientation>"`. |
| `documentName` | string | `"Tile"` for our case. |
| `img` | string | Path inside Foundry user-data (`modules/dh-cartography/stamps/<file>.png`). |
| `tags` | flat string[] | Includes `group:<uuid>` so variants join via tag filter. |
| `gridSize` | int | `100`. |
| `data` | non-empty array | Each entry is a placeable; we emit one. |
| `data[].texture.src` | string | Same path as `img`. |
| `data[].x/y/width/height/rotation` | numbers | `width`/`height` are real PNG dims via PIL. |

Optional `spawnRandom: true` collapses `data[]` entries into a random
pick at spawn — we DO use it for visually-interchangeable stamps, do
NOT use it for orientation/state variants (those are deliberate picks
or runtime cycling via Active Tiles).

Import path: **Preset Browser → Import** (UI dialog, no filesystem
drop). Default extension `.json`.

---

## ComfyUI integration — verified working configuration

### Required custom nodes (already installed on server)

- **kijai/ComfyUI-Florence2** — exposes `Florence2Run`, `DownloadAndLoadFlorence2Model`, `Florence2ModelLoader`.
- **ComfyUI-Manager** v3.39.2 (informational; remote installs blocked by security level).
- **ComfyUI_IPAdapter_plus** — exposes `IPAdapterEncoder`, `IPAdapterSaveEmbeds`, `IPAdapterModelLoader`.
- Built-in `LoadImage`, `CLIPVisionLoader`, `CLIPVisionEncode`, `PreviewAny`.

### Required model files (already on server)

| File | Used by |
| --- | --- |
| `MiaoshouAI/Florence-2-large-PromptGen-v2.0` (HF download triggered by `DownloadAndLoadFlorence2Model`) | classifier |
| `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | embedding pass |
| `ip-adapter-plus_sdxl_vit-h.safetensors` | embedding pass |

### Footguns (read these before changing the workflow)

1. **Florence-2 requires SQUARE input.** Non-square images trip
   `AssertionError: only support square feature maps for now` deep in
   the model's image-pre-processor. We pad to square (content
   centered) **locally** before uploading — see
   `square_png_bytes()` in both `classify_stamps.py` and
   `assign_groups.py`. Note: `classify_stamps.py` ALSO upscales to
   ≥768 on the long edge AND flattens onto white before upload (see
   gotcha #9 below); `assign_groups.py` does not.
2. **`Florence2Run` is NOT an `OUTPUT_NODE`.** ComfyUI rejects a
   workflow whose only sink is `Florence2Run` with
   `prompt_no_outputs`. Wrap each `Florence2Run` in `PreviewAny`
   (which IS an output node) to surface the caption / tag string
   in `/history.outputs.<node_id>.text`.
3. **Florence-2-base captions are unusable for our domain.** Base
   model hallucinates `"a set of ..."`, `"No object detected"`, ASCII
   art with underscores, and frequently captions the background
   instead of the foreground stamp. Use
   `MiaoshouAI/Florence-2-large-PromptGen-v2.0` instead — same
   architecture, fine-tuned for clean noun-phrase + tag output, and
   unlocks the `prompt_gen_tags` task that returns real tags rather
   than the `<loc_X>` region tokens base produces.
4. **`/history` returns the full recent-prompt set, not just yours.**
   Filter by `prompt_id` AND check `status.completed == True` before
   reading `outputs`. A naive `if hist: return hist[prompt_id]` will
   return mid-run state with empty outputs.
5. **`IPAdapterSaveEmbeds` does NOT surface its filename in
   `/history.outputs`.** The `outputs` dict is empty even on success.
   Predict the filename instead: it's
   `{filename_prefix}_{counter:05d}.ipadpt` (note: NO trailing
   underscore before `.ipadpt` — that pattern would be wrong). Use a
   unique `filename_prefix` per stamp so `counter` is always `00001`
   and the filename is fully deterministic.
6. **The `.ipadpt` file is a `torch.save()` pickle of a single tensor**,
   not safetensors. Loading requires `torch` (CPU is fine; the wheel
   is ~200 MB and uv caches it once). For our CLIP-ViT-H +
   `ip-adapter-plus_sdxl_vit-h` combo it's shape `(1, 257, 1280)`;
   mean-pool over the token axis to get a 1280-d vector.
7. **ComfyUI dedupes by content hash.** Identical workflows submitted
   in quick succession may not re-execute on the GPU. We use a unique
   `filename_prefix` per stamp specifically to break this dedup AND
   to make filenames predictable.
8. **Don't run two classify/assign runs concurrently.** Both contend
   for the same ComfyUI prompt queue and create cross-collisions.
   This rule extends to ANY GPU consumer (Florence-2 classify,
   IPAdapter embedding for assign, Chroma battlemap renders) — the
   3090 is one queue, all jobs are siblings. Use the harness's task
   tracking to see what's already running before launching another.
9. **Florence-2 success depends on payload, but the right payload
   varies by stamp.** A/B testing on `Gemini_Generated_Image_4lrua5*`:
   - At native size + transparent background: ~80% of cells caption
     correctly (most furniture, equipment, documents).
   - At 768px upscale + white background: SOME small/intricate
     subjects (e.g. parchment-with-wax-seal `_02.png`) caption only at
     the larger size, but OTHER subjects that worked at native size
     (e.g. simple bowls `_00.png`) return empty captions at 768.
   The two transforms are complementary, not strictly better/worse.
   `classify_one()` runs a two-pass strategy: default pass at native
   transparent first; on empty result, retry with the upscale + white
   payload. Verified to recover ~80% of previously-failing cells while
   keeping ~80% native-pass success. The retry payload is uploaded
   under a `__retry`-suffixed filename so it doesn't share a cache
   slot with the default upload. `assign_groups.py` does NOT need
   either transform — CLIP-ViT-H reads at 224² internally and
   clusters fine on the transparent-padded payload.
10. **Don't set `max_new_tokens` below 1024 on the dual-task
    workflow.** `classify_stamps.build_workflow()` runs
    `more_detailed_caption` and `prompt_gen_tags` simultaneously on
    one Florence-2 prompt. At 256 tokens, generation truncates
    mid-sequence and PromptGen returns empty text for some stamps —
    interaction unique to the dual-task graph; single-task workflows
    work fine at 256. Always 1024+ in this codebase.
11. **PromptGen captions need preamble stripping for usable names.**
    PromptGen-v2.0 reliably emits captions like "The image is a
    digital illustration of [subject]" or "A set of three 3D
    rendering illustrations of [subject]". A naive head-noun
    extractor lands on "Image", "Illustration", "Set" — all useless.
    `_strip_preamble()` peels medium/multiplicity/article words
    iteratively until what remains starts with the actual subject
    noun. Extend its `_PREAMBLE_PHRASES` list when new opener phrases
    show up in captions; the patterns are designed to chain
    (idempotent fixed-point). Don't rely on a single regex — the
    chains are unboundedly long.

### Phase 1 vs Phase 2 grouping

Phase 1 (caption-name canonicalization) is the structure layer —
it's how we know the *concept* of the cluster. Phase 2 (CLIP-ViT-H
image embedding) is the truth layer — it tells us when two stamps
that captioned differently are actually the same object, or when
two stamps that captioned the same are actually different objects.

Thresholds in `assign_groups.py`:
- `SPLIT_THRESHOLD = 0.78` — within a name-cluster, pairs below this
  are split into separate components.
- `MERGE_THRESHOLD = 0.92` — across name-clusters, the best
  cross-cluster pair sim above this triggers a merge.

These are starting points; tune after inspecting actual output on
your domain.

### `group_id` is deterministic

`uuid5(GROUP_NAMESPACE, "<canonical_name>:<sha1(sorted_member_filenames)>")`
— same canonical name + same member set always yields the same
group_id. Re-runs are stable as long as cluster membership doesn't
change.

---

## Sidecar schema (per-stamp YAML)

Documented in `make_sidecars.py`'s template. Fields:

```yaml
name: null                       # noun-phrase from caption (Title-Cased)
description: null                # full caption
tags: []                         # lowercase-hyphenated; first ~10 content words
orientation: null                # north|south|east|west|top-down|isometric
state: null                      # intact|damaged|destroyed|active|inactive
group_id: null                   # UUID (uuid5 deterministic)

source: <stem>.png               # original grid PNG
source_index: <int>              # 0-based position within the source grid
extracted_at: <iso-8601>         # set once at sidecar creation
classified_at: null              # set when classify_stamps.py runs
classified_by: null              # model id used for classification
```

Field ordering and comments are preserved across re-runs by line-level
YAML rewriting (no PyYAML round-trip). Manual edits to any field are
preserved unless the field is overwritten by a script that has
authority over it (e.g. `assign_groups.py` owns `group_id` only).

---

## Hard rules

- **Never silently drop a stamp.** If extraction fails on an image,
  log it and leave the source untouched.
- **Never write image-specific overrides into `extract_stamps.py`.**
  Tunables are CLI flags or per-image YAML sidecars, never branches by
  filename.
- **Never deploy stamps from this directory directly.** Use
  `../../deploy.sh cartography`. The deploy script is authoritative.
- **Never run two classify or assign processes concurrently.** They
  collide on the ComfyUI queue.
- **Never edit a sidecar by hand and then re-run `classify_stamps.py
  --force`** — `--force` overwrites the script-owned fields. Use
  `--force` only when you intend to re-classify.
- **Never `--no-verify` past pre-commit gates** in the parent repo.
