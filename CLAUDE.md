# Cartography Asset Pipeline — Working Directives

## Project end goal (IMMUTABLE — read before doing anything)

This project produces a complete, playable Foundry V14 asset set for
the Solenne Dark Heresy 2e campaign. The aesthetic target is the
existing deployed `SOLENNE_*.png` maps and the deployed character
portraits in `Characters/Edric Family/` (painterly oil, FFG-era Dark
Heresy tone, full painted detail to the surface of every plane).
Anything weaker than that bar is not a deliverable.

The full deliverable surface — every item below is in scope and
required:

1. **Battlemaps** — interior tactical maps (hab, manufactorum,
   chapel, medicae, scholam, garrison, bar, tunnel, lair, archive,
   etc.) at painterly Solenne-grade quality. **Layouts must be
   driven by the actual room geometry**, not defaulted to a square
   canvas. Rectangular halls, L-shaped suites, multi-room
   apartments with corridors, irregular tunnel networks, lopsided
   industrial bays — the canvas shape and aspect ratio follow the
   layout, not the other way around. A square render of a
   non-square location is wrong, regardless of how good the
   surfaces look.
2. **Battlemap overlays** — perfectly registered Foreground layers
   that stack on a base map (e.g. catwalks over a factory floor,
   walls-alpha over architecture, mezzanines, gantries). Pixel
   alignment with the base is mandatory; misregistration is data
   loss.
3. **Ships** — multi-deck spacecraft maps where every deck (bridge,
   engineering, barracks, cargo, medbay, hangar, etc.) shares an
   identical hull bbox so decks layer perfectly when the operator
   stacks them in Foundry. Aesthetic must match the rest of the
   battlemap line. **Wall textures, floor textures, and surface
   features (consoles, bunks, crates, machinery) all need to read
   as painted material at the same fidelity as the deployed
   interior battlemaps.** A deck rendered with flat fills, simple
   shapes, or schematic blocks does not advance this goal even if
   the deck-stack geometry is pixel-perfect — the geometry pass and
   the surface pass both have to land.
4. **City maps — districts** — hab district, manufactorum district,
   medicae district, scholam district, Mechanicum spire district,
   PDF/garrison district, transit, ore-processing, etc. District-
   scale top-down maps the operator can place tokens on for
   sub-tactical encounters. **A district must read as a hive city
   subsection**: dense vertical urbanism, stacked mega-blocks,
   trans-hive arteries, smog-choked spires, layered structures
   sharing walls and roofs across kilometres. A scattering of
   freestanding building stamps on an open canvas is not a
   district — that reads as a frontier settlement, not a hive.
   Reference: 40K hive city imagery, Necromunda Sector Mechanicus,
   Forge World hive cross-sections.
5. **Planetary maps** — full-planet views (hive locations,
   continents, terrain) for strategic-scale narrative.
6. **Star system maps** — system-scale charts (planets, orbits,
   warp routes) for travel and sector framing.
7. **Stamps** — extracted asset library with full **matrix
   variations** per subject:
   - Orientation: only when the variant requires actual
     re-rendering (different lighting, different visible faces,
     different perspective). **Pure 90/180/270° rotations of a
     top-down PNG are NOT stored as separate files** — Foundry's
     tile layer rotates freely at runtime, so saving four copies
     of the same pixels is 4× storage with zero gameplay benefit.
     Geometric rotation is a Foundry runtime concern, not a
     pipeline output.
   - Damage level (intact / damaged / destroyed) — these are real
     re-renders with different pixel content.
   - Activation level (active / inactive) — same; real re-renders.
   All variants of a subject are grouped (`group_id`) so Foundry's
   Mass Edit Preset Browser can search, filter, and present them
   as a coherent variant set. Missing variants in a group are
   filled by **supplemental generation** — when a group has e.g.
   intact + damaged but no destroyed, the pipeline generates the
   missing variant from the existing ones.
8. **Portrait generation** — character portraits in line with the
   deployed `Characters/Edric Family/*.png` and `Characters/Pell
   Osric.png` references. **Fidelity bar is the deployed portraits,
   not the current pipeline output.** The deployed references show
   sustained fine detail across face, fabric folds, embroidery,
   armor seams, and background environment. A portrait that reads
   as a low-resolution painterly thumbnail does not match. Tokens
   are 1:1 crops centered on the face.
9. **Scene generation with integrated iconography** — narrative
   scene art (chapels, sanctums, war rooms, audience halls, etc.)
   where Imperial / Inquisitorial iconography is rendered AS scene
   material: brass relief on stone, etchings in metal, embossings
   on armor, embroidered banners, gilt inlay, carved wood.
   **Iconography must be true to the canonical shape**: an
   Imperial Aquila is a two-headed eagle with wings spread
   horizontally (or slightly down-swept, in a heraldic stoop),
   never with arched-up wings or substituted with a generic angel
   silhouette. An Inquisitorial Rosette is the canonical
   skull-and-cross design, not a generic medal. If the integration
   pass repaints the silhouette but loses the canonical shape, it
   is a regression — high painterly fidelity does not excuse
   silhouette drift. Flat SVG-on-render compositing is NOT an
   acceptable terminal state for these scenes either.
10. **External layout ingestion via ControlNet** — a render path
    that takes a *finished* orthographic layout exported from an
    external tool (Dungeon Scrawl, Dungeondraft, hand-drawn floor
    plans, etc.) and renders it to Solenne-grade painterly quality
    while **honoring the source geometry structurally**. The source
    line art / wall strokes / room edges drive a ControlNet
    (lineart / canny / depth) img2img pass — the renderer follows
    the actual walls and openings of the export, not just a
    color-region mask. This is distinct from the current
    `spacecraft` mode, which is regional `ConditioningSetMask`
    prompting over a canonical-color mask we paint ourselves: that
    path honors *where* regions are but discards the source's
    drawn structure. No ControlNet node exists in either saved
    workflow today — building this is in scope and required. A
    pipeline that can only consume masks we hand-paint, with no way
    to ingest an external layout-tool export as structural
    guidance, does not satisfy this goal.

    **Chosen ingestion route (decided 2026-05-25).** Prefer a
    *semantic* path over a blind edge-tracing one. A raw canny /
    lineart ControlNet has zero semantics — it reproduces lines but
    does not know a gap is a door or a glyph is stairs, so doors and
    stairs render unreliably. Instead:
    - **Source: Dungeondraft → Universal VTT (`.dd2vtt`)**, not a
      flat PNG. The UVTT export is JSON carrying walls
      (`line_of_sight`), portals (doors + windows, with bounds /
      rotation / open-closed), and lights as explicit vector
      geometry — i.e. the semantics are labelled by the source tool,
      not guessed by a model.
    - **Converter (built): `dd2vtt_to_layout.py`.** `.dd2vtt` →
      canonical region-color PNG + `<stem>.placements.json` (door +
      light pixel coordinates for tile-layer auto-placement). Walls /
      lights map onto canonical colors; doors are carved as floor
      openings by default (`--door-as`) since the door leaf is an
      interactive tile, not base-map architecture. Output is aliased
      and palette-checked (no AA fall-through, gotcha #11). **Stairs
      are not a first-class UVTT type** — tag them as a Dungeondraft
      object layer mapped to a region color, or hand-paint after
      conversion. `uv run dd2vtt_to_layout.py --self-test` verifies
      the path with no real export needed.
    - **Render: feed the region map to the existing `spacecraft`
      regional-conditioning mode** (`BattlemapSpacecraft.json`) — it
      already assigns each color region its own prompt, which is
      exactly per-class treatment — or to a segmentation ControlNet
      on Flux.1-dev / Qwen-Image. Both are zero-training (see
      "Tooling decisions"). Canny/lineart on Flux/Qwen is the dumb
      fallback only when the source is raster-only (e.g. a flat
      Dungeon Scrawl PNG with no vector layer).
    - **Points are NOT a ControlNet input.** "Drop a point, put a
      toilet here" is a separate placement step (generate-and-place
      a stamp on the tile layer, or SAM2-point → inpaint into the
      base). The click feeds the placement/inpaint step as a
      coordinate; it never touches the base ControlNet/region map.

These requirements are immutable. They are not subject to
reinterpretation, scope reduction, or "diminishing returns"
arguments. If a current pipeline cannot meet one of these bars,
the response is to identify the missing capability and either build
it or escalate to the operator — NOT to redefine the bar downward.

When uncertain whether work-in-progress is on track, re-read this
list. Every commit, every render, every helper exists to advance
one of these ten items toward shippable Solenne-grade quality.

---

## Tooling & workflow goals

The ten items above are the *deliverable* goals — the asset **types**
the project must ship. This section records *tooling* goals: the
production **capabilities** that serve those deliverables. Tooling
goals are a separate axis (a *how*, not a *what*); they do **not**
renumber, replace, or dilute the immutable ten.

T1. **Krita generative-editing integration.** A first-class,
    interactive round-trip between Krita and the lab ComfyUI backend
    (`http://198.51.100.11:8188`) via the `krita-ai-diffusion` plugin,
    so any deployed asset — battlemap, portrait, scene, stamp — can be
    inpainted / outpainted / refined / live-painted **in-canvas**
    against the same Chroma-Flux + IPAdapter (and, once trained, the
    campaign LoRAs) that the batch pipeline uses. This is the
    interactive complement to the scripted `generate_battlemap.py` /
    `generate_character_portrait.py` paths and to the SAM2-point →
    inpaint and localized-inpainting levers already named throughout
    this doc: the fidelity fixes those bullets describe (canonical
    Aquila repaint, portrait fine detail, damage-state stamp variants)
    become hand-guided operator moves instead of blind batch reruns.
    - **File convention (decided 2026-07-24).** Working masters are
      `.kra` files kept **beside their exported PNG deliverable** —
      `Maps/FinalChapel.kra` ↔ `Maps/FinalChapel.png`,
      `Characters/<Name>.kra` ↔ `Characters/<Name>.png`. The **PNG
      export is the tracked, deployed asset**; the `.kra` is a
      **gitignored, local-only** layer-stack master (`*.kra` in the
      vault `.gitignore`). Autosaves and editor backups
      (`*-autosave.kra`, `*~`) are never tracked.
    - **Acceptance.** A round-trip is proven when an operator opens a
      deployed `SOLENNE_*.png` in Krita, runs a masked inpaint through
      the ComfyUI backend, and exports a PNG that matches the
      Solenne-grade bar with the edit integrated as painted material
      (not a pasted overlay). Notebook: `docs/krita-workflow.md`.

Related tooling already recorded elsewhere, cross-referenced here so
the tooling axis is legible in one place:
- **ControlNet layout ingestion** — deliverable goal **#10** is itself
  tooling-flavoured (a render *path*), but stays numbered in the
  deliverable list because it directly gates a deliverable
  (external-layout export → Solenne-grade map). See its own entry and
  "Tooling decisions".
- **Gemini Imagen ("nano-banana") path** for iconography-critical
  surfaces — see "Tooling decisions" and `TODO.md`. Chosen because
  local Chroma-Flux lacks aquila / rosette / cog as concept tokens.

---

## Goals ↔ LoRA-bin crosswalk

The 15 LoRA training bins under `lora-training/<bin>/` are *means*;
each serves one or more deliverable goals above. This table keeps the
two lists reconciled (bins with a populated `raw-references/` or
`train/` are corpus-ready; see `pipeline_status.py` for live counts).

| Deliverable goal | Serving LoRA bin(s) |
| --- | --- |
| #1 Battlemaps (interiors) | `scenes`, `seamless-tiles`, `tile-structure`, `stamps`, `terrain-references` |
| #2 Battlemap overlays | *(pipeline: walls-alpha / `--keep-only`; no dedicated bin)* |
| #3 Ships (multi-deck) | `voidship-hulls`, `voidship-layouts` |
| #4 City / district maps | `hive-city`, `terrain-references` |
| #5 Planetary maps | `planet-textures` |
| #6 Star-system maps | `sector-maps`, `strategic-icons` |
| #7 Stamps | `stamps` |
| #8 Portraits | `portraits`, `iconography` (worn heraldry) |
| #9 Scenes w/ integrated iconography | `scenes`, `iconography`, `chaos-iconography`, `xenos-iconography` |
| #10 ControlNet layout ingestion | *(tooling render-path; no bin)* |
| T1 Krita generative editing | *(consumes every trained bin at inference; no bin of its own)* |

---

## Pipeline overview

This directory turns Gemini-generated stamp-grid PNGs into a Foundry V14
tile/asset library for the Solenne campaign.

End-to-end stamp pipeline:

```
PNG grids ─►  extract_stamps.py     ─►  stamps/<stem>_NN.png
              make_sidecars.py      ─►  stamps/<stem>_NN.yaml
              classify_stamps.py    ─►  populates name/description/tags/orientation/state
              assign_groups.py      ─►  populates group_id (variant clustering)
              build_mass_edit_pack  ─►  dh-cartography/mass-edit-presets.json
              stage_module.py       ─►  dh-cartography/stamps/  (hardlinks, prunes orphans)
              validate_preset_pack  ─►  pre-deploy contract check
              deploy.sh cartography ─►  rsync to Foundry server
              (manual)              ─►  Mass Edit Preset Browser → Import
```

`pipeline_run.py` chains all stages serially; `pipeline_status.py`
gives an at-a-glance health snapshot.

Battlemap rendering pipeline (orthogonal to stamps):

```
make-room / make-corridor / hand-paint  ─►  layouts/<slug>.png  (canonical region colors)
dd2vtt_to_layout.py <export>.dd2vtt    ─►  layouts/<slug>.png + .placements.json  (Dungeondraft UVTT ingest)
quantize-layout (optional)              ─►  snaps hand-painted colors to canonical palette
generate_battlemap.py interior --style  ─►  txt2img map for an empty interior at any scale
generate_battlemap.py spacecraft        ─►  img2img map driven by region-colored layout
generate_battlemap.py …  --keep-only    ─►  alpha-mask the render to one role; foreground layer
generate_battlemap.py mask-by-layout    ─►  generic alpha-mask helper (e.g. txt2img scaffold → floor-only)
generate_battlemap.py compose           ─►  preview the layered stack before Foundry import
```

Every script has an inline `# /// script` block declaring its uv
dependencies; run with `uv run <script>.py`.

**Architecture-only by default — but not as dogma.** The driver
renders **only** walls / floor / ramps / viewports / lighting in the
base map by default. The real distinction (operator-confirmed
2026-05-25) is *what the object does at the table*, not stamps-vs-
baked:
- **Tile layer:** interactive props (a crate the players search, a
  door, a chair that gets knocked over) and anything needing
  **variant cycling** (intact → damaged → destroyed via Active
  Tiles). Flattening these into the base destroys their purpose.
- **Bake into the base is fine — often more organic:** fixed set-
  dressing that never moves and benefits from sitting *in* the
  lighting (built-in fixtures, wall grime, rubble, ambient clutter).
  Painted in by the same model in the same light avoids the pasted-
  sticker look a composited stamp can have. This is the operator's
  call, not a rule violation.
The saved `BattlemapSpacecraft.json` includes furniture region
nodes; the driver auto-neutralizes them (prompt rewritten to "empty
deck plating") unless the operator opts in with
`--render-furniture chair|locker|console`. Point-grounded inpaint
(SAM2-point → inpaint, ComfyUI-Angelo, Qwen-Image-Edit) is the other
supported bake-in path.

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
11. **Layout regions for the spacecraft workflow are
    architecture-only.** Five canonical region colors:
    `wall #303030`, `floor #808080`, `ramp #A0A0A0`,
    `windscreen #1A2750`, `lighting #D4B260`. The saved workflow
    file *also* declares `chair`/`locker`/`console` color codes for
    backward compat, but the driver auto-rewrites those region
    prompts to "empty deck plating" by default. Hand-painted
    layouts should not paint chair/locker/console colors —
    furniture goes on the stamp layer.
12. **Wide-scale archetypes use the same Chroma-Flux txt2img path
    as interior renders.** `--style district|region|planet|system`
    are just different prompts; no separate workflow needed.
    Quality varies: district + system render convincingly, region
    + planet currently mediocre on the saved seeds — iterate
    prompts and seeds before declaring deploy-ready.
13. **PromptGen v2.0 has a silent-fail mode on certain art styles.**
    Clean line-drawn isometric subjects — arcade-cabinet kiosks,
    plain metal desks, drink trays, white canisters — return EMPTY
    captions across `caption`/`detailed_caption`/`more_detailed_caption`/
    `prompt_gen_tags` regardless of payload (native+transparent OR
    768+white). The base `microsoft/Florence-2-large` captions the
    same images correctly with its "image is a 3D rendering of …"
    preamble. `classify_one()` now does three passes: default →
    retry → tertiary fallback to base Florence-2. Recovered 111 of
    128 silent-fail stamps in one verification run. The remaining 17
    are genuinely caption-resistant (abstract patterns, near-empty
    images) — both models empty.
14. **`assign_groups` regenerates group_id deterministically from
    canonical_name + sorted member set.** If you manually edit a
    member's name and re-run assign_groups, the group's uuid5 hash
    changes and so do all its members' group_id values. This is OK
    because uuid5 is idempotent on identical inputs, but it means:
    (a) don't quote a specific group_id in code or docs as a stable
    identifier; (b) Foundry's Mass Edit Preset Browser may show
    "broken variant link" warnings after a re-classify if a stamp
    moved to a new group. Importing a fresh preset pack resolves it.
15. **Phase 2 grouping over-merges at scale.** With 600+ stamps the
    default `MERGE_THRESHOLD = 0.92` produces large false-positive
    superclusters (97- to 121-member clusters of unrelated subjects
    that share art-style background). `group_audit.py` flags
    clusters with low pairwise caption overlap AND no shared
    concrete subject token; the operator clears their group_ids
    via the snippet in `docs/battlemap-workflow.md`. Lower the
    threshold or cap cluster size at the source for a permanent fix.
16. **Florence-2 docvqa is for documents, not natural images.**
    Tested: returns empty on every stamp regardless of question.
    Don't use it for object Q&A. For object classification, use
    CLIP zero-shot via `classify_orientation.py`.
17. **CLIP > SigLIP for binary contrastive classification on
    stylized illustrations** in this domain. SigLIP-so400m's
    sigmoid scoring biases toward whichever label has the more
    verbose / specific paraphrase set, collapsing all stamps to
    one label. CLIP-ViT-L-14's softmax over a small label set
    (top-down vs isometric) discriminates ~64% on hand-grounded
    test data — much better than SigLIP's ~0% (everything
    top-down) on the same prompts.
18. **Phase 2 merge: median cross-pair similarity, not best.**
    Best-pair MERGE_THRESHOLD=0.92 chained unrelated clusters into
    superclusters of 100+ members (one coincidentally-similar pair
    triggered a merge, snowballing transitively). Median requires
    the bulk of cross-pair similarity to exceed 0.92. Cap on
    cluster size after this fix: ~17 in a 615-stamp vault, down
    from 121.
19. **Caption-resistant stamps were all gutter artifacts.** The
    16% of stamps that resisted Florence-2 (PromptGen + base) all
    had fill ratios 0.013-0.041 — i.e. they were grid-line
    networks captured before MIN_FILL_RATIO=0.15 was added to
    extract_stamps.py. Retroactive cleanup script removes them by
    fill ratio; after that, real-stamp classification rate is 100%.
20. **PromptGen captions need preamble stripping for usable names.**
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

## Tooling decisions — when local Chroma-Flux is the wrong tool

The local ComfyUI / Chroma-Flux pipeline has a hard ceiling on
iconography fidelity that no parameter sweep on the existing scripts
will lift. The 2026-05-08 review made this explicit: Gemini-Imagen
("nano-banana") nails canonical 40K iconography on the first try
because it has the symbol vocabulary trained in; our local Chroma-
Flux doesn't, and the workarounds we've layered on (silhouette-paste
+ img2img integration, anti-symbol negative prompts) produce either
flat overlays or repainted silhouettes that drift off the canonical
shape.

### Where local Chroma-Flux is appropriate

- Battlemap interiors where iconography is incidental ambient detail
  (floor mosaics, ceiling beams, wall plating). The chapel floor
  rosette in `SOLENNE_district4_chapel.png` is an example of this
  working natively.
- Wide-scale archetypes (district / region / planet / system) where
  the visual language is geography and atmosphere, not iconographic
  precision.
- Multi-deck ship layout geometry (the spacecraft mode workflow
  produces correct hull bbox alignment, even when the surface pass
  needs to come from a different tool).

### Where local Chroma-Flux must NOT be the terminal tool

- **Portraits with named symbols on armor / fabric / collars.** The
  silhouette-paste-then-img2img approach loses canonical aquila
  shape under high denoise and reads as a flat sticker under low
  denoise.
- **Scenes with hero-symbol focal points** (chapel apse aquila, ship
  hull aquila, banner of the Inquisition, Mechanicus shrine cog).
  Same root cause.
- **Any surface where the symbol shape itself carries the meaning**
  — heraldry, sigil-laden documents, signet rings, ceremonial
  regalia.

### What to use instead — validated 2026-05-08

For iconography-critical surfaces, use **Gemini 2.5 Flash Image**
("nano-banana") via the AI Studio API. Free tier on the API is
gone as of mid-2026 (paid-only); AI Studio web UI still gets ~500
free renders/day but is not programmatic. Image gen on the API is
billed per image (~$0.04 at gemini-2.5-flash-image rates). Confirmed
working with the operator's API key after billing was enabled.

**Reference-image conditioning is the architecture that works.** A
canonical-shape reference image is fed to Gemini alongside the
prompt; the prompt drives surface treatment (material, context),
angle, and lighting. Result: the canonical silhouette is preserved
across every variant because the reference supplies it; only
material / context / angle / lighting vary. This decouples shape
fidelity from prompt engineering.

Validated pipeline:
- `gen_iconography_corpus.py` — manifest-driven generator
- `lora-training/manifest.yaml` — DRY: common_treatments shared
  across symbols + per-symbol extra_treatments + global angle and
  lighting pools sampled round-robin
- Per-variant prompt template:
  `"Preserve the exact heraldic silhouette ({shape}) from the
  reference image. Render it as {treatment}. View: {angle}.
  Lighting: {lighting}. Single symbol focal subject filling most of
  the frame, full silhouette visible, no text, no caption."`
- Reference image: each symbol's `*_isolated.png` plate
- Output: PNG + sibling `.txt` caption (trigger + shape + treatment)
  paired for kohya/ai-toolkit ingestion

Generation discipline lessons:
- **Manifest must be append-only.** Output filenames embed the
  sequential treatment index. Reordering shifts indices, orphans
  existing files, and re-bills the whole corpus on next run. New
  treatments go at the END of `common_treatments` or in
  `common_treatments_extended`.
- **Handle Gemini's IMAGE_SAFETY blocks.** Some prompts return
  `candidate.content == None` with `finish_reason=IMAGE_SAFETY`
  (e.g., body-modification + sigil combinations). The generator
  must check for None content and skip gracefully rather than
  AttributeError out mid-corpus.
- **Round-robin angle/lighting sampling.** Pure Cartesian product
  is combinatorial; round-robin (treatment[i] × angle[i mod n] ×
  lighting[i mod m]) gives even axis coverage with linear cost.
- **Same canonical reference for all variants.** Don't pass scene-
  context references — the LoRA needs to bind the trigger to the
  shape, not to a specific scene. Use the cleanest isolated plate
  available.

Validated 2026-05-08 corpus: 11 Imperial symbols × 29 variant
slots = 319 planned, 317 generated (2 safety-blocked), ~$12.60
spent on the $20 budget.

Untried local levers (in case Gemini becomes unavailable or the
operator wants an all-local pipeline):
- **40K iconography LoRA** — train Chroma-Flux on a curated set of
  isolated canonical-shape references (Imperial Aquila, Inquisitorial
  Rosette, Mechanicus opus cog, Astra Militarum winged skull,
  Adepta Sororitas fleur-de-lys, Adeptus Custodes lightning bolt,
  Adeptus Ministorum sigil, Chapter heraldry, Eldar runes, Ork
  glyphs, etc.) on neutral backgrounds. Captions describe SHAPE,
  not style ("Imperial Aquila, two-headed eagle, wings spread
  heraldic, isolated on white"). At inference, stack with whatever
  style anchor the render needs:
  `<lora:wh40k_iconography:0.8>, painterly oil portrait, ...`. This
  is the **portable artifact** that benefits this campaign AND the
  whole `wh40k-rpg` Foundry system across all 7 game lines (BC,
  DH1, DH2, DW, OW, RT, IM). Style is per-campaign; iconography is
  a 40K constant. **Do not** train a campaign-specific LoRA that
  fuses Solenne style and iconography — that locks the shape
  vocabulary to one aesthetic.
- IPAdapter image conditioning using the deployed Vigil Ledger /
  test_inquisitor_v2 / Corvin Edric portraits as references. We
  have CLIP-ViT-H + ip-adapter-plus_sdxl_vit-h installed and used
  for `assign_groups`; the same encoder can feed image embeddings
  as generation conditioning, not just clustering input.
- Localized inpainting with a tight mask on the symbol region so
  the surrounding scene is untouched and only the symbol gets
  repainted.

These levers stay listed because some future session may re-approach
them; they are NOT a defense for shipping the current local-only
pipeline output as iconography deliverables.

---

## Quality acceptance rules (added after 2026-05-07 review)

The operator reviewed a presentation bundle and rejected nearly all of
it: symbology was still flat SVG with surrounding noise, decks still
read as MS-Paint not painterly, the hab floor was bland, and the hex
overlay was demoed on an image where it made no narrative sense. The
common thread: I claimed aesthetic wins I had not earned and did not
compare against the campaign's existing deployed art. These rules
exist to prevent that recurrence. Full post-mortem in
`docs/battlemap-workflow.md` under
"2026-05-07 — Review post-mortem".

- **The operator is the aesthetic judge, not me.** Never describe an
  output as "reads as X", "matches campaign tone", "looks polished",
  "integrated", "convincing", or any other subjective quality claim
  in a status update or presentation. State what was rendered
  (model, workflow, prompt anchor, denoise, seed) and leave the
  judgment to the operator.
- **Compare against deployed maps before shipping.** Before placing
  any new render in `_presentation/`, `_deliverables/`, or any
  operator-facing folder, open at least one already-deployed
  `SOLENNE_*.png` battlemap or portrait and view them side-by-side.
  If the new render is visibly weaker on style, texture, or
  cohesion, it does NOT ship. Document the comparison in the commit
  message.
- **Visual claims require side-by-side proof OR they do not exist.**
  "Chapel Aquila reads as brass relief" requires (a) a brass relief
  reference image in the same view, AND (b) operator agreement. A
  belief that the integration worked is not evidence the integration
  worked. `denoise=0.45` will not repaint a high-contrast black
  silhouette into scene material — this is a hard property of the
  pipeline. Do not claim otherwise.
- **No "accepted artifact" cope.** When prompt iteration plateaus,
  the response is NOT "accept the limitation". The response is:
  list the alternative approaches that have not yet been tried,
  ranked by confidence (e.g. switch workflow, use proper ControlNet,
  localized inpainting, train a LoRA, source reference art), and
  let the operator pick. The operator decides whether to escalate
  or drop, not me.
- **Generic helpers need real demos, not nearest-image demos.** A
  new tool's demo composite must answer a real campaign need
  (district control overlay on a district map, fleet movement on a
  sector chart at the appropriate scale). Demoing a hex grid on a
  parsec-scale system chart because it was open in the next tab is
  scope drift. If there is no obvious real demo, do not invent one;
  ship the helper without a demo and ask the operator what it should
  be applied to.
- **Don't propose "session checkpoint" or "deliverables bundle"
  commits without operator review of the contents.** A bundle is a
  request for review, not a finished product. Frame it as such in
  the commit message and in chat ("candidates for review", not
  "deliverables").
- **Closing a TODO requires operator confirmation when the success
  criterion is aesthetic.** Mechanical TODOs (e.g. "verify pixel
  alignment") can be closed by passing tests. Aesthetic TODOs
  (e.g. "chapel trim", "floor texture punch", "symbology
  integration") cannot be self-closed — they go to the operator.
- **Re-read this section before writing a status summary.** "Wins
  and fails" framing tempts overclaiming on the wins side. The
  operator-reviewed honest version is almost always smaller than
  the version I want to write. Default toward describing the work
  done in mechanical terms; let the artifacts speak for the
  aesthetic outcome.

---

## Hard rules

- **Never silently drop a stamp.** If extraction fails on an image,
  log it and leave the source untouched.
- **Never write image-specific overrides into `extract_stamps.py`.**
  Tunables are CLI flags or per-image YAML sidecars, never branches by
  filename.
- **Never deploy stamps from this directory directly.** Use
  `../../deploy.sh cartography`. The deploy script is authoritative.
- **Never run two GPU jobs concurrently.** Classify, assign, and any
  battlemap render all share the 3090's ComfyUI queue. Serialize.
- **Default furniture to the tile layer when the object is
  interactive or needs variant cycling** (searched crate, door,
  knocked-over chair, intact/damaged/destroyed sets). Fixed set-
  dressing (built-in fixtures, grime, rubble, ambient clutter) MAY
  be baked into the base when that reads more organically — the
  operator's call, not a violation. `--render-furniture` and
  point-grounded inpaint are the supported bake-in paths. Do NOT
  lecture the operator that architecture-only is absolute; it isn't.
- **Never edit a sidecar by hand and then re-run `classify_stamps.py
  --force`** — `--force` overwrites the script-owned fields. Use
  `--force` only when you intend to re-classify.
- **Never store pure 90/180/270° geometric rotations as separate
  stamp PNGs.** Foundry rotates tiles freely at runtime; saving four
  copies of identical pixels is 4× storage with zero gameplay
  benefit. Only persist rotation variants when the variant requires
  actual re-rendering (different lighting, different visible faces,
  different perspective). `generate_stamp_variants.py rotate
  --method generative` is the conditional path; `--method geometric`
  is for one-off scratch use, not for persisted assets.
- **Never default a battlemap canvas to square.** Pick the canvas
  shape from the actual room geometry. A square render of a
  rectangular room (or vice-versa) is a regression even if the
  surfaces look painterly.
- **Never ship iconography candidates from local Chroma-Flux without
  side-by-side comparison against the canonical shape.** An aquila
  with arched-up wings is not an aquila; an inquisitorial rosette
  rendered as a generic medal is not an inquisitorial rosette.
  See "Tooling decisions" above for when to switch to Gemini.
- **Never reorder a treatment-list manifest.** Output filenames
  embed the sequential treatment index; reordering renames every
  downstream file and re-bills the corpus on next run. Append new
  entries to the END of `common_treatments` or in
  `common_treatments_extended`. The same rule applies to per-symbol
  `extra_treatments`.
- **Never commit `.env`.** API keys are in `.env`; the file is
  gitignored. `.env.example` documents the required variables. If
  you find a key in a committed file, rotate it immediately.
- **Never assume Gemini will return content on every call.** Image-
  generation responses can have `candidate.content == None` with
  `finish_reason=IMAGE_SAFETY` on prompts the safety filter blocks
  (body modifications, blood, etc.). Defensive parsing — check for
  None content, log the finish_reason, mark the job as a failure,
  continue. Without this guard the generator AttributeErrors out
  on the first blocked prompt and burns no work.
- **Never render Imperial voidships with forward-facing pursuit guns
  as their primary armament.** Imperial Navy ships fight broadside —
  primary batteries run along the port and starboard flanks of the
  midsection, firing outward. Forward-facing bow turrets are
  characteristic of specific outliers (Corvus Blackstar etc.), NOT
  the standard frigate/destroyer/cruiser/battleship line. Any voidship
  render or prompt that places the primary battery at the bow is wrong.
- **Never use a single shared style reference across visually-distinct
  ship classes (or any other class axis we want differentiated).**
  Gemini's reference-image conditioning locks silhouette as well as
  style, so a shared reference collapses class differentiation. For
  source-material LoRA corpora, prefer text-only generation with strong
  per-class silhouette descriptors. For refinement work on a single
  class, a per-class reference image is fine.
- **Never `--no-verify` past pre-commit gates** in the parent repo.
