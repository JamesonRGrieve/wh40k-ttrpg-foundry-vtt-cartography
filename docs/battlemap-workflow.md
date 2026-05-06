# Battlemap generation — operator's notebook

This is the running record of what works and what doesn't when driving
the ComfyUI battlemap workflows. Update it after every successful or
failed run; freeze nothing. The working hypothesis at any moment is
whatever this file currently says.

The goal: **bare top-down architectural battlemaps** (floor + walls,
maybe doors / ramps / windows) suitable for Foundry V14 scene
backgrounds. Props are NOT generated here — they're stamped on top
later via the `multi-token-edit` Mass Edit pipeline. A second
foreground/walls-only pass for stackable layered scenes is in scope as
an optional step but is NOT implemented yet.

---

## What's saved on the ComfyUI server

Pulled into `workflows/` from the server's `userdata/workflows/`:

| File | Type | Notes |
| --- | --- | --- |
| `BattlemapInteriorV1.json` | txt2img | Chroma-unlocked-v35, 1024² EmptyLatent, single pos/neg pair. No spatial control. |
| `BattlemapSpacecraft.json` | img2img | Same Chroma model, but loads `layout.png` and runs 8 `ImageColorToMask` + `CLIPTextEncodeFlux` + `ConditioningSetMask` chains for per-region conditioning. Strong spatial control. |

Re-pull when the canonical prompts on the server are edited:

```sh
for f in BattlemapSpacecraft.json BattlemapInteriorV1.json; do
  curl -s -o "workflows/$f" "http://198.51.100.11:8188/api/userdata/workflows%2F$f"
done
```

The driver loads these as templates and never edits them. Local
overrides happen in memory.

## How `generate_battlemap.py` drives them

`uv run generate_battlemap.py interior` — overrides `pos.t5xxl` and
`pos.clip_l`, EmptyLatentImage dimensions, KSampler seed, and
SaveImage prefix on `BattlemapInteriorV1`, then submits and downloads.

`uv run generate_battlemap.py spacecraft --layout layouts/foo.png` —
uploads the layout PNG to ComfyUI's `input/battlemap_layouts/`,
rewrites the `LoadImage` node to point at it, sets seed and prefix,
submits.

Outputs land in `battlemaps/`.

## Color codes used by `BattlemapSpacecraft.json`

The eight color->prompt regions baked into the saved workflow (decimal
values match the `color` input on each `ImageColorToMask` node):

| Color (dec) | Hex | Region | Default t5xxl prompt |
| --- | --- | --- | --- |
| 3158064 | `#303030` | walls | thick spacecraft hull bulkhead wall |
| 8421504 | `#808080` | floor | metal deck plating, floor panels with seams |
| 10526880 | `#A0A0A0` | ramp | rear loading ramp, corrugated metal surface |
| 1716304 | `#1A2750` | windscreen | cockpit windscreen viewport, reinforced |
| 9132587 | `#8B5E2B` | chair | pilot command chair, worn brown leather |
| 4876928 | `#4A6F40` | locker | tall metal storage locker, steel blue |
| 2771536 | `#2A4250` | console | instrument console panel, control dials |
| 13934624 | `#D4B260` | lighting | amber lumen strip light, glowing warning |

**Important**: the color match is exact. Anti-aliased edges between
regions in your layout PNG won't match any color and will fall through
to the unmasked base prompt. Either paint with hard edges (Krita →
Pixel Art brush, GIMP → no-AA pencil), or post-process the layout
through nearest-neighbor color quantization to the eight colors above.

## Successes

### 2026-05-05 — Layered/multi-deck stacking VERIFIED

**Same-footprint multi-deck**: painted two layouts (engineering
deck + bridge deck) sharing the same outer hull region. Walls
coincide pixel-perfectly: exact-color IoU = 0.946 (deck1 walls are
a complete subset of deck2 walls; the 5% delta is deck1's
loading-ramp opening punching through the hull on purpose). A
token at (x,y) on deck1 lands at the same (x,y) on deck2. Foundry
multi-deck scenes can use either deck as the active scene without
re-positioning.

**Independent-render layered overlay**: rendered a metal-grate
scaffold via interior txt2img, masked it to the floor region
using the layout PNG as the alpha source, alpha-composited over a
separately-rendered base map. Walls + lights from base show
through the perimeter; scaffold occupies the floor area exactly.
Pixel-perfect alignment because both renders share the same
layout, and the layout drives the alpha mask deterministically.

The walls-only mode (`spacecraft --walls-only` / `--keep-only
wall`) is the simplest case of this pattern. The new
`mask-by-layout` subcommand generalizes it to any role and any
input render — letting you produce arbitrary stackable layers
(scaffolding, water, fog, second-floor cutaways) by rendering them
independently and masking.

### 2026-05-05 — Group-membership audit (visual inspection)

Manually inspected all 9 multi-member groups in the current vault:

| group | members | verdict |
| --- | --- | --- |
| `3380ef7e` | 2 | ✅ TRUE variants — battered office chair pair |
| `3b58afaa` | 2 | ✅ TRUE variants — paperwork pile (intact / aged) |
| `7e090f37` | 2 | ✅ TRUE variants — locker pair (intact / weathered) |
| `b00219a2` | 2 | ✅ TRUE variants — sealed dossier (intact / bloodied) |
| `fbdc4f25` | 3 | ✅ TRUE state-variants — cogitator console (active / inactive / destroyed) |
| `309afa52` | 4 | ⚠ same family (pipe fittings) but different junction shapes — not strict variants |
| `861baff5` | 4 | ⚠ partially correct: 3 bed variants + 1 false-positive locker pair (cleared) |
| `f3df525c` | 3 | ❌ FALSE-POSITIVE merge: 3 distinct container types (case/locker-door/footlocker) — cleared |
| `83fd8256` | 5 | ❌ FALSE-POSITIVE merge: 5 distinct bulkhead panels — cleared |

Took action:
- Cleared `group_id` to null on 9 stamps confirmed as
  false-positive merges.
- Manually filled name/description/state on 6 yamls where visual
  inspection revealed information missing from captions
  (e.g. cogitator console state — captions said "televisions
  arranged" but the images clearly show active/inactive/destroyed
  CRT terminal variants).

The Phase 2 merge threshold (`MERGE_THRESHOLD = 0.92` in
`assign_groups.py`) is too generous for stamps that share a
common art-style background (beige/grimdark palette pulls
unrelated subjects close in CLIP-ViT-H embedding space).
Operationally, manual yaml inspection is required for any group
the operator wants to use as a strict state-variant cluster.
Future: extend `pipeline_status.py` with a "group sanity check"
that flags suspicious merges (e.g. groups whose member captions
share <50% of content tokens).

### 2026-05-05 — Florence-2 unrecoverable failures (some stamps)

A small fraction of stamps (`_08.png`, `_09.png` in 4lrua5 — both
battered office chairs in a slightly cartoonish 3/4-from-above
style) consistently caption empty across every Florence-2-
PromptGen-v2.0 configuration tried: native+transparent,
native+white-bg, 768+white-bg, multiple tasks (caption,
detailed_caption, more_detailed_caption, prompt_gen_tags), and
single-task vs dual-task workflows. Confirmed reproducible.

The grouping pipeline RECOVERS these stamps via CLIP-ViT-H image
embedding — the two chairs landed in the same Phase 2 cluster
even though both have empty descriptions. Operationally:

* For visually-similar variants of the same object, the embedding
  step produces correct group ids regardless of caption.
* For names/tags on these stamps, the operator can edit the yaml
  manually. The pipeline preserves manual yaml edits across re-
  runs (classify_stamps only writes script-owned fields when
  --force is passed and the script can produce text).

Non-leverage paths attempted (don't retry):
* Bigger upscale (1024, 1536) — same empty result.
* Gray background instead of white — same.
* Model swap to base Florence-2 — produces hallucinations on
  unrelated stamps; net regression.

Possible future improvement: fall back to a different VLM (e.g. a
small LLaVA or Qwen-VL) on Florence-2 empty-output retries. Out
of scope for now; Phase-2 embedding rescue is sufficient.

### 2026-05-05 — Quantizer v2 (modal-background detection)

The first quantizer needed the input layout's region colors to be
within ~25 channels of canonical, which the hand-painted reference
layout violated (windscreen / lighting got swept to background).
v2 splits the work into two stages: detect the modal color via
16-step binning and treat that as background; then force-snap every
non-background pixel to the nearest canonical color WITHOUT a
distance cap. Result on `spacecraft_default.png`: 69.4% of pixels
detected as background, all 7 painted regions snapped cleanly to
canonical colors. The walls-only render against the quantized
layout produces a continuous bulkhead outline (10.1% kept) vs. the
raw layout's gappy antialiased outline (7.6% kept).

Use this to pre-process any hand-painted layout before feeding it
to ComfyUI's `ImageColorToMask` regional-conditioning nodes.

### 2026-05-05 — End-to-end pipeline aligned with deploy.sh

`stage_module.py` now prunes orphaned staged stamps (those whose
source has been deleted, like the gutter artifact `_05.png` from
4lrua5). `build_mass_edit_pack.py`'s default `--out` writes to
`dh-cartography/mass-edit-presets.json` so dev runs produce the
same artifact `deploy.sh cartography` ships. After running both:
632 presets across all sheets, 14 for the 4lrua5 sheet (gutter
gone), names like "Empty Ceramic Bowls With Handles" with
orientation/state suffixes ("— east", "— active, west") and
populated tag arrays. Pipeline is ready to deploy on user
instruction.



### 2026-05-05 — Interior workflow, bare room (1024²)

Command:

```sh
uv run generate_battlemap.py interior --seed 42 --prefix map_interior_bareroom
```

Result: `battlemaps/map_interior_bareroom_00001_.png` (1.9 MB, 1024²).

The driver's bare-architecture default prompt (no tables / chairs /
counters / barrels — explicit "completely empty room with no
furniture, no props" in the positive prompt because Flux ignores
negative-prompt furniture exclusions) produced exactly the target
deliverable: top-down orthographic empty room, bulkhead walls around
the perimeter with rivets and weld seams, corroded deck plating with
visible seam lines and rust, amber lumen lights at the corners. No
props, no characters, no decorations on the floor. Drop a Foundry
scene background underneath this and stamp props on top.

The image isn't a perfect orthographic projection — there's a slight
parallax tilt (corners appear higher than the center) — but it's
close enough that tokens placed on it read as "in the room". Pure
orthographic would require ControlNet depth conditioning, not in
scope yet.

### 2026-05-05 — Interior workflow, first end-to-end run

Command:

```sh
uv run generate_battlemap.py interior --seed 42 --prefix map_interior_smoketest --width 768 --height 768
```

Result: `battlemaps/map_interior_smoketest_00001_.png` (1.1 MB, 768²).

The HTTP plumbing works: workflow loaded, prompts mutated, dimensions
overridden, seed fixed, prompt submitted, history polled,
`SaveImage` output downloaded. Visual quality on the saved
canonical prompt was good — recognizable top-down grimdark sci-fi
interior with bulkhead walls, deck plating, amber/teal lighting, slight
isometric tilt rather than pure orthographic.

### 2026-05-05 — Stamp pipeline (4lrua5 sheet)

Not battlemaps, but the same ComfyUI plumbing — recording here so the
gotchas don't get lost when this file is the canonical operator's
notebook.

**Two-pass classifier**. Florence-2-large-PromptGen-v2.0 succeeds at
captioning native-size transparent stamps for ~80% of cells and
upscaled-to-768 white-bg stamps for a different ~80% — they're
complementary, not strictly better/worse. `classify_stamps.classify_one`
now runs the default native-transparent pass first; on empty caption,
retries with the upscale + white-bg payload uploaded under a
`__retry`-suffixed filename. Result on the 4lrua5 sheet: 12/15 vs
9/15 with single-pass.

**Token floor**. The dual-task workflow (`more_detailed_caption` +
`prompt_gen_tags` simultaneously) returns empty text for some images
when `max_new_tokens<1024`. Single-task workflows are fine at 256.
Codified at 1024 in `build_workflow()`.

**Caption-preamble stripping**. PromptGen reliably emits captions
like "The image is a digital illustration of [subject]". A
single-regex extractor lands on garbage ("Is A Digital Illustration",
"Set", "Collection"). `_strip_preamble()` peels
medium/multiplicity/article words iteratively until what remains
starts with the actual subject noun. Names went from "Stack" →
"Papers Tied Together With Twine"; from "Is A Digital Illustration"
→ "Empty Ceramic Bowls With Handles".

**CLIP-ViT-H rescues Florence-2 failures**. Stamps 08/09 of the
4lrua5 sheet (battered office chairs) caption empty on every
Florence-2 path tried. Phase-2 image embedding clustered them
together correctly anyway — visual similarity carries when language
fails. The Phase 1 / Phase 2 split is load-bearing; don't collapse
either side into the other.

**Extraction fix landed**: `extract_stamps.MIN_FILL_RATIO = 0.15`
rejects sparse components. Real stamps fill 0.55-0.82 of their
bbox; grid-line networks captured as a single huge component fill
~0.011. The filter logs `[reject] <file> label=N: fill=X.YYY <
0.15` for visibility. Verified on the 4lrua5 sheet — gutter
artifact rejected, 14 real stamps extracted (down from 15 with
the gutter inflating the count). Re-extracting an already-
processed sheet renumbers, so don't `--force` re-extract on
already-classified sheets — manually delete the offending
`_NN.{png,yaml}` pair instead. Done for 4lrua5 — gap at index 05
is intentional and harmless to downstream tools.

## Failures and gotchas

### Saved canonical prompt embeds props

The `BattlemapInteriorV1` template's pos.t5xxl describes "round wooden
tables with metal stools, long bar counter with taps, barrel storage
alcove with crates" — i.e., a furnished bar. The first smoketest
faithfully rendered all of those.

For our use case (bare maps, props via stamp), the script's
`INTERIOR_DEFAULT_T5` is now overridden to an architecture-only
prompt with explicit negative-of-furniture in positive ("completely
empty room with no furniture, no props, no objects, no tables, no
chairs"). Flux's t5xxl ignores `neg.t5xxl` instructions like "no
chairs", so the avoidance has to live in the positive prompt. We have
not yet validated this works — pending a second smoketest.

The saved server template was left untouched (it's the canonical
"furnished bar" exemplar). Stripped-architecture variants live in the
script's defaults; if they prove out, they should be cloned to the
server as `BattlemapInteriorV2_BareRoom.json` via:

```sh
uv run generate_battlemap.py clone BattlemapInteriorV1.json BattlemapInteriorV2_BareRoom.json
```

then edited in the ComfyUI web UI.

### Filename prefix double-printed

The first download landed as `map_interior_smoketest_map_interior_smoketest_00001_.png`
because `_download_first()` prepended our prefix to ComfyUI's saved
name (which already starts with the SaveImage prefix). Fixed: the
saved filename is used verbatim. `--prefix` only sets the SaveImage
node's `filename_prefix`, which becomes the saved name's stem.

### GPU contention with classify_stamps

Running `generate_battlemap.py interior` while
`classify_stamps.py` was iterating over the 4lrua5 sheet caused
multiple Florence-2 prompts to time out at 300s and several to come
back with empty captions. CLAUDE.md's "Never run two classify or
assign processes concurrently" rule extends to battlemap generation —
the 3090 is one queue, all jobs are siblings. **Serialize.** Don't
launch a battlemap render while a classify or assign run is in
progress, and vice versa.

## Layered foreground pass

`uv run generate_battlemap.py spacecraft --layout … --walls-only`
produces a transparent-background walls layer suitable for Foundry's
scene foreground / overlay tile.

### Implementation

The driver runs the canonical spacecraft workflow unchanged (no
prompt overrides, no chromakey shenanigans). Post-render, it uses
**the original layout PNG as an alpha mask over the rendered PNG**:
pixels whose layout-image color is within tolerance of the target
region's color stay opaque; everything else gets `alpha=0`. The
output goes to `<prefix>_alpha.png`.

This is deterministic in a way the chromakey approach was not — the
layout is the source of truth for "where is the wall," not Flux's
attempt to render a magenta region. See the failure log below for
what didn't work.

### What didn't work (recorded so we don't redo it)

**Magenta-prompt chromakey**: first attempt overrode every non-wall
region's `CLIPTextEncodeFlux` to "solid pure magenta `#FF00FF`,
featureless flat color, no detail" and tried to chromakey magenta
out post-render. Flux's t5xxl encoder mutes saturated out-of-gamut
prompts to a neutral mid-tone — the rendered output had ~zero
magenta pixels, so the chromakey filter ate nothing. Confirmed by
running the full pipeline with `--walls-only` (chromakey variant)
on the spacecraft layout: 0/2,073,600 pixels keyed. Walls-only mode
now uses the layout-as-mask approach instead.

### Edge artifacts (open improvement)

Hand-painted layouts have anti-aliased edges between regions. Those
mid-tone pixels don't match any region's exact color, so the alpha
mask passes them through as transparent — leaving thin gaps in the
walls outline of the produced layer. Two ways to fix:

1. **Pre-process the layout** through nearest-neighbor color
   quantization to the eight canonical region colors before feeding
   it to the script. Krita / Photoshop / GIMP all support this.
2. **Increase the mask tolerance** (currently `tol=40` Chebyshev) but
   that risks bleeding into adjacent regions. Per-role tolerance
   would be needed.

Option 1 is the cleaner fix because it also improves the input to
ComfyUI's `ImageColorToMask` nodes (which require exact match);
the regional conditioning becomes more reliable AND the alpha mask
becomes pixel-perfect at the same time.

`generate_battlemap.py quantize-layout <input>` snaps each pixel of
the layout to the nearest canonical region color (within a tight
Chebyshev tolerance) and forces background to black. Known
limitation as of 2026-05-05: works only when the input layout's
sampled colors are within ~25 channel distance of the canonical
palette. The shipped reference layout (`spacecraft_default.png`,
pulled from the ComfyUI server) is hand-painted with approximate
colors that drift further than that — windscreen and lighting
regions get swept to background. Two workable paths going forward:

1. Paint future layouts with the exact canonical colors (an
   eyedropper-snap palette in your image tool, or a fresh layout
   built from colored rectangles directly in Python).
2. Extend the quantizer with a per-region tolerance map or a
   clustering pass that learns the layout's actual region colors
   and maps them to the canonical palette by proximity.

For the current `spacecraft_default.png` layout, the
unmodified-layout-as-mask path in `--walls-only` is sufficient —
the thin anti-alias gaps in the wall outline are cosmetic and
don't break the layered scene.

## Source-of-truth contract

The saved workflows are authoritative. Don't edit `workflows/*.json`
in this repo by hand — those are pulls. Edit on the ComfyUI server
(via the web UI, save, then re-pull). The driver script asserts
nothing about node ids; if a node is renamed on the server, the
script fails loudly with `KeyError`.
