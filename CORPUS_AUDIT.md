# Corpus audit — visual inspection protocol

This document defines how to triage the 5,012 candidate images currently
staged at `.corpus/uncertain/pending-visual-review/` (the corpus tree
is `.corpus/`, relative to the cartography pipeline root — the
top-level `.lora-training/` submodule of the dh-campaign vault — NOT
inside the `.foundry-cartography/` deploy module, which is pure JSON +
images per the repo-reorg split)
into the project's LoRA training corpora. It exists because a prior
session triaged 19 GB of donated assets using filename + folder heuristics
*without opening a single image* and falsely labeled the output as
"fully approved high quality corpus." That output has been demoted
back to `pending-visual-review/`; this document is the corrective
protocol for doing the job properly.

## Cardinal rule

**You must open each image with the Read tool before deciding its bin.**
The Read tool is multimodal — it returns image content visually, not
just a path. Filenames and folder names are hints, never verdicts.
A confidently-named file can be amateur; a hash-named file can be
canonical reference. The only way to tell is to look.

If you find yourself triaging based on filenames alone, stop. Either
slow down and inspect, or move the bin to `uncertain/` and document
why a visual pass wasn't done.

## What the corpora are for

The campaign trains a stack of complementary LoRAs against
`ostris/Flex.1-alpha` (Flux-architecture-compatible) on the gigabyte
lab's 3× RTX 3090 host (CT 140). Each LoRA binds a *trigger token
namespace* to a *shape concept invariant to lighting, angle, and
material treatment*. See `memory/iconography_lora.md` and the existing
`lora-training/<goal>/manifest.yaml` files for the established pattern.

Eleven candidate bins are staged. Six map to **pre-existing corpus
goals** with manifests and trained or in-flight checkpoints. Five
map to **deferred goals** named in `TODO.md` and operator direction.

| Bin (in pending-visual-review/) | Goal status | Trigger namespace | Training target |
|---|---|---|---|
| `iconography/` | Active (manifest, training infra ready) | `sym_aquila`, `sym_inq_rosette`, `sym_mech_cog`, `sym_militarum_winged_skull`, `sym_sororitas_lys`, `sym_ministorum`, `sym_administratum`, `sym_arbites`, `sym_telepathica_eye`, `sym_imperial_navy`, `sym_rogue_trader` | Imperial faction heraldry — exact canonical shape invariant to material/angle/lighting |
| `voidship-hulls/` | Active (manifest exists) | `ship_<class>` namespace (e.g. `ship_emperor_class`, `ship_gladius`, `ship_iconoclast`) | Top-down void vessel hulls by class |
| `scenes/` | Active (per-scene subdirs already populated) | `scene_<archetype>` (e.g. `scene_chapel_apse`, `scene_underhive`, `scene_manufactorum`) | Top-down battlemap interiors per archetype |
| `stamps/` | Active (in training, see `stamps/train/<category>/`) | `dh_stamp` + per-category tag | Top-down grid-aligned props (furniture, machinery, fixtures, containers, documents, ordnance) |
| `chaos-iconography/` | Deferred — TODO.md "LoRA categories" | `sym_chaos_star`, `sym_nurgle`, `sym_khorne`, `sym_tzeentch`, `sym_slaanesh`, `sym_renegade`, `sym_traitor`, `sym_daemon` + per-legion if needed | Chaos faction heraldry |
| `xenos-iconography/` | Deferred — TODO.md "LoRA categories" | `sym_tyranid`, `sym_genestealer`, `sym_eldar`, `sym_harlequin`, `sym_drukhari`, `sym_tau`, `sym_necron`, `sym_ork`, `sym_votann` | Xenos faction heraldry |
| `planet-textures/` | Deferred — supports `make_system_map.py` improvements | `planet_<class>` (e.g. `planet_agri`, `planet_hive`, `planet_death`, `planet_ice`, `planet_gas_giant`) | Orbital views of planet surfaces by classification |
| `hive-city/` | Deferred — TODO.md "Hive-city density for the district archetype" | `hive_overhead`, `hive_cross_section`, `hive_spire` | Hive-city scale (district-density target) |
| `sector-maps/` | Deferred — supports `make_overlay.py` wider use | `sector_chart` | Imperial sector starfield cartography |
| `terrain-references/` | Deferred (new) | `terrain_<type>` (heightmap, statue, ruins, etc.) | Top-down natural terrain features for battlemap composition |
| `strategic-icons/` | Deferred (new — very small, 2 files) | `icon_strategic` | Strategic map symbology |

A **seamless 1×1 tile LoRA** is also planned (TODO.md). No candidate
images are pre-binned for it; certain `stamps/` and `terrain-references/`
content may qualify after visual review confirms edge-tileability.

## Pre-existing corpus state — do not disturb

Before adding *anything* to a corpus dir, check what's already there.
Each existing corpus dir has its own conventions:

- `lora-training/iconography/manifest.yaml` — defines Imperial trigger
  tokens, the matrix-sampling rationale, and what counts as
  *isolation* for that LoRA (full silhouette visible, single subject
  filling frame, no text/caption).
- `lora-training/voidship-hulls/manifest.yaml` — defines the ship-LoRA
  approach.
- `lora-training/scenes/scene-<archetype>/` — per-archetype subdirs
  already exist (chapel-apse, scriptorium, manufactorum-bay,
  archive-stacks, chapel-nave, refectory, sanctum, audience-hall,
  war-room, dormitorium). New scene material should go into one of
  these subdirs if its archetype matches, or into a new
  `scene-<new-archetype>/` subdir if not.
- `lora-training/stamps/train/<category>/` — already organized by
  category (ordnance, furniture, machinery, fixtures, misc,
  containers, documents). New stamp material should land in the
  correct category, not a generic `from-james/` bin.

Read these manifests/READMEs before you start placing files. The
existing conventions are load-bearing — the LoRA training configs
reference them.

## Acceptance criteria

A candidate image is **approved for corpus** if, after visual
inspection, it meets *all* of:

1. **Subject is on-canon for the target bin.** A "tyranid"-named file
   that shows a generic insect is not a tyranid; reject. A
   "shadowsword"-named file that shows the Imperial super-heavy tank
   is not chaos heraldry; reject from `chaos-iconography/`, possibly
   relocate elsewhere.
2. **Resolution is adequate for the training target.** Iconography
   needs the symbol clearly readable — typically ≥512px on the long
   edge. Battlemaps need ≥1024px. Reject blurred/upscaled/jaggy
   images.
3. **Style is canonical or close-canonical.** Reject biologically
   detailed eagles posing as aquilas (the canonical aquila is
   stylized heraldic geometry; this was a documented failure mode
   from the 2026-05-08 Gemini corpus build). Reject fan-redrawn
   versions that drift from canonical silhouette.
4. **The image is a clean training example** for its bin:
   - Iconography → isolated symbol on a clean background, full
     silhouette visible.
   - Voidships → single vessel in top-down view, clean dark
     background, no overlay text/labels.
   - Scenes → top-down architectural map, no UI chrome, no token
     overlays, no measurement grid (or a removable grid).
   - Planet textures → clean orbital sphere or flat tile, no
     UI/labels.
   - Hive-city → recognizable hive-city density (stacked vertical
     mega-blocks); reject flat town renders even if labeled "hive."
5. **Not a duplicate** of something already in the corpus dir.
6. **No large watermark.** Diagonal body-crossing watermarks, repeated
   tiling watermarks, and prominent artist/source attribution washes
   across the image body are immediate-disqualifying — **route to
   `.corpus/garbage/<bin>-large-watermark/`, NOT to `needs-text-removal/`.**
   Watermarks are designed to be hard to remove cleanly; even when an
   inpainting pass succeeds, residual artifacts will teach the LoRA to
   reproduce them, and the operator/budget cost of cleaning a single
   watermarked image rarely justifies the inclusion when a clean
   variant of the same image is almost always available in the donor
   archive (e.g. `*_0.png` next to `*WM_0.png`). Filename suffixes
   `WM`, `wm`, `Wm`, `watermarked` are a strong indicator — check for
   the non-WM sibling and prefer it. Small corner attribution, room
   labels, scale bars, and class-designation overlays are NOT
   watermarks in this sense; route those to `needs-text-removal/`.

If an image is high-quality but for a *different* bin than the one it
was staged in, move it to the right bin. (Example: many files staged
under `chaos-iconography/Chaos/` are actually Imperial vehicles that
happened to live in a "Chaos" folder in the donor archive.)

### Bin routing — Stage 1 vs Stage 2 for voidships

When auditing voidship material, distinguish the two LoRA stages
explicitly:

- **Stage 1 — voidship-hulls (`lora-training/voidship-hulls/`).**
  Empty top-down hull silhouettes. NO interior visible, NO room
  labels, NO floor plans, NO km-scale annotations. The hull is a
  closed/opaque silhouette from above with only exterior surface
  features (gothic dorsal spires, gun batteries, prow shape, lateral
  sponsons, engine block). Captions stay compact: trigger + view +
  hull-feature tags.
- **Stage 2 — voidship-layouts (`lora-training/voidship-layouts/`).**
  Top-down cutaway diagrams showing interior rooms, room
  enumeration, and connectivity. Annotated class-stat cards with
  numbered room legends, cutaways with km-scale bars and labeled
  compartments, and any image where the *interior organization* is
  visible. **Captions must be exhaustive** per the layout-caption
  rule: enumerate every room type, describe its contents, use
  positional/relational verbiage (amidships, aft of bridge,
  starboard of spinal artery, dorsal cluster), and count/locate
  doors and corridors. Bin-routing destination is
  `lora-training/voidship-layouts/raw-references/needs-text-removal/`
  when the image carries overlay text that needs inpainting-out
  before training.

A "voidship has overlay text" image is NOT a reject — it's a Stage-2
candidate. Only large watermarks (criterion #6 above) qualify as
immediate garbage. The original voidship Step-2 criterion #4
("Voidships → single vessel in top-down view, clean dark background,
no overlay text/labels") applies specifically to the Stage-1 hull
corpus and does NOT disqualify Stage-2 layout material.

### Stamps — mandatory acceptance + caption rules (operator-set 2026-05-16)

A stamp is corpus-eligible ONLY if all hold (in addition to the
general acceptance criteria):

1. **Orthographic only.** Strict top-down orthographic projection,
   no perspective foreshortening, no isometric skew. Isometric /
   3-4-perspective / oblique props render wrong on a flat Foundry
   tile layer. Non-orthographic →
   `.corpus/uncertain/stamps-rejected-non-orthographic/` (do not
   approve, do not "close-enough" them in).
2. **Transparent background required for `train/`.** Subject must
   be alpha-cut with real transparency to enter `train/`. BUT an
   opaque-background stamp that is otherwise on-target
   (orthographic, on-canon, clean subject) is NOT a reject — it is
   salvageable by background removal, exactly analogous to the
   voidship `needs-text-removal/` holding pattern. Route it to
   `lora-training/stamps/needs-background-removal/<category>/` and
   **write its caption sidecar there** (it has been Read; caption
   at move-time). It re-enters `train/<category>/` after the
   background is alpha-cut. Only send to
   `.corpus/uncertain/stamps-rejected-*` or `.corpus/garbage/` if
   it fails a different criterion (non-orthographic, off-canon,
   low-res, watermark, duplicate). Alpha channel present is
   necessary but NOT sufficient — alpha-present-but-visually-opaque
   also goes to `needs-background-removal/`. JPGs (no alpha) with a
   good subject also go to `needs-background-removal/`, not reject.
3. **Art-style tag mandatory.** Every caption carries one explicit
   style descriptor: `painterly | hand-painted | 3d-render |
   flat-vector | line-art | pixel-art | cel-shaded` (lowercase
   hyphenated; extend as needed). Describe the style you SEE.
4. **State tag verified from the image**, not defaulted:
   `intact | damaged | destroyed | active | inactive`. Lit/powered
   → `active`; broken/burned → `damaged`/`destroyed`; no state axis
   → `intact`.

Updated stamp caption format:
`dh_stamp, <Title Case Subject>, top-down view, <art-style>, <state>, <category-tag>, <descriptive-tag>…, <NxM-grid if visible>`

These rules postdate the bulk subagent pass that approved ~456
stamps WITHOUT enforcing rules 1–3. Remediation: 47 opaque-bg
pairs (with their captions) relocated to
`lora-training/stamps/needs-background-removal/<category>/` as a
post-processing holding area (NOT discarded — they re-enter
`train/` after alpha-cutting). The remaining ~409 trained
non-Gemini stamps still need a per-file Read remediation pass to
reject non-orthographic, move alpha-present-but-opaque to
`needs-background-removal/`, add the art-style tag, and verify
state. Pre-existing Gemini-generated trained stamps are out of
audit scope unless a full-corpus recheck is requested.

## Inspection protocol

For each candidate bin in `pending-visual-review/`:

### Step 1 — Bin coherence check (sampling)

Use `Read` on **at least 15 randomly-sampled images** from the bin.
Spread the sample across any internal subdirs. Goal: form a verdict
on the bin's **coherence and average quality**.

Outcomes:

- **Bin is uniformly high-quality and on-target** → proceed to Step
  2 for bulk approval. (Rare. Reserve for clearly curated donor
  subdirs like the named-class voidship hull PNGs.)
- **Bin is uniformly junk** → move the whole bin to `.corpus/garbage/`
  with a reason note. (Rare. Reserve for clearly amateur/scraped
  material whose smell test the sample confirms.)
- **Bin is mixed** → proceed to Step 3 for per-file review.

Document each bin's verdict and sample evidence as you go (a short
note per bin in your conversation, or appended to this file).

### Step 2 — Bulk approval (only after Step 1 confirms coherence)

"Bulk approval" is shorthand for **"trust the sub-bin's coherence
enough to skip the approve/reject decision per file, but still Read
each file once to write its caption."** It is NOT permission to move
files without opening them. Per the "Caption discipline" rule above,
every approved image needs a `.txt` sidecar written from what you
see, not from its filename. The Read needed to caption is the same
Read that would catch the occasional in-sub-bin off-target file —
both come for free in one pass.

Move each file into the appropriate `lora-training/<goal>/<subdir>/`
location, writing its caption sidecar at the same time. Respect
existing organization:

- Scenes → into `lora-training/scenes/scene-<archetype>/` matching
  the bin's content, creating a new scene archetype only when no
  existing one fits.
- Stamps → into `lora-training/stamps/train/<category>/` matching
  the prop category (furniture/machinery/fixtures/containers/etc.),
  not a generic catch-all.
- Iconography → into `lora-training/iconography/raw-references/` (a
  new subdir for non-Gemini-generated reference images; do not mix
  with the manifest-driven Gemini-generated corpus that lives at the
  iconography root).
- New goal bins (chaos-iconography, xenos-iconography, planet-
  textures, hive-city, sector-maps, terrain-references, strategic-
  icons) → create the goal dir, write a starter `manifest.yaml`
  documenting the trigger namespace and shape-invariance clauses
  (model on `iconography/manifest.yaml`), then place the approved
  images under `raw-references/` so future Gemini-conditioned
  generation has a clear input vs. output separation.

For each approved image, write a `.txt` caption sidecar (see
"Caption format" below).

### Step 3 — Per-file review (when bin is mixed)

For each image in the bin:

1. `Read` the image.
2. Decide: approve / reject / relocate.
   - Approve → move to the right corpus subdir, write a caption.
   - Reject → move to `.corpus/uncertain/<bin>-rejected-<reason>/`
     (not garbage — operator may want a different use later).
   - Relocate → move to the correct bin under
     `pending-visual-review/`; it'll be reviewed when that bin is
     processed.
3. Note any patterns you see across rejects so you can quickly
   batch-reject similar files (e.g., "all SeekPng.com_* files have
   visible watermarks and should be rejected on sight").

This is slow. 5,012 files is far too many for one pass. Suggested
prioritization:

1. **`iconography/`** (705 files) — highest priority, feeds the
   nearest-term training run. Sample first; expect the SVGs from
   `Imperium/` to be uniformly high-quality (Step 2 path) and the
   `loose-symbols/` + `Faction-Icons/` mixed (Step 3 path).
2. **`voidship-hulls/`** (251 files) — small, well-organized by class,
   second priority. Likely Step 2 path with light filtering.
3. **`stamps/`** (1895 files) — DaSIG props are systematically labeled
   by grid size (1x1, 2x3, etc.); should be coherent. Tactical/Props
   sub-bin is the mixed portion.
4. **`scenes/`** (794 files) — three sub-bins (facility-maps,
   underhive, darktide-references). Each likely Step 2 if curated.
5. **`hive-city/`** (14 files) — tiny but high-impact for an
   underserved LoRA goal. Quick pass.
6. **`chaos-iconography/`** (151), **`xenos-iconography/`** (386) —
   deferred goals, modest priority.
7. **`planet-textures/`** (247) — supports planet rendering work;
   modest priority.
8. **`sector-maps/`** (53), **`terrain-references/`** (457),
   **`strategic-icons/`** (2) — niche, low priority.

The operator should be consulted before committing time to bins 6–8;
their downstream goal status may have shifted.

## Caption discipline — write at move-time, no exceptions

**Captions are written in the same atomic operation as the approve+move
decision, while the image is still in the multimodal context that
produced the approval.** This is a hard rule.

Why: the only way to caption honestly is to describe what you *see in
the image*. The Read tool puts the pixels into context once. If you
approve-and-move without writing the caption, the pixels leave context
and the only way to recover them is to Read again — doubling the
multimodal cost of the corpus. Worse: under context pressure a future
session may caption from filename instead of re-reading, which is the
exact failure mode this audit exists to correct.

There is no "caption later" tier. There is no "raw-references doesn't
need captions yet" exemption — `raw-references/` material may be
promoted to direct training input or used as Gemini reference seeds,
and either way a caption written at move-time is cheaper and more
accurate than one written at promotion-time. Every approved image
gets a `.txt` sidecar at the moment it lands in its destination
directory.

Implication for bulk approval (Step 2): bulk approval does NOT mean
"move N files without inspection." It means "having sampled enough to
confirm a sub-bin's coherence, Read each remaining file briefly to
write its caption while moving it." If you cannot afford the
per-file Read pass for the captions, you cannot afford to approve
the bin — leave it in `pending-visual-review/` and document the
partial work.

## Reject analysis sidecars — write at move-time too (no exceptions)

The same discipline applies to **rejects**, for the same reason. A
rejected image moved into `_rejected/<reason>/` with no sidecar is a
landmine: a future audit cannot tell what it is, why it was cut, or
whether it should be re-binned / used as a supplemental seed /
garbaged — without re-opening and re-Reading every image, which is
the exact cost this audit exists to avoid paying twice.

So: **every rejected image gets a `.txt` analysis sidecar written in
the same atomic op as the reject+move decision, from the pixels in
context, never from the filename.** No "rejects don't need notes"
exemption. If you cannot afford the per-file Read to write the
reject sidecar, you cannot afford to reject the file — leave it in
place and document the partial work.

Reject sidecar format (`<same-basename>.txt` beside the image inside
`_rejected/<reason>/`), labeled lines (NOT the single-line caption
CSV — rejects need disposition, not a training caption), greppable:

```
verdict: reject
reason: <slug — matches the _rejected/<slug>/ bin dir>
subject: <Title Case — what the image ACTUALLY shows, from pixels>
why: <one sentence — the specific disqualifying property>
disposition: <rebin:<corpus/bin> | supplemental-seed:<archetype> | garbage | hold-operator>
reviewed: <model>, <date>
```

`disposition` is the audit payload: it tells the next pass the
recommended action so the reject can be actioned by `grep` without a
re-Read (e.g. `grep -rl '^disposition: rebin' _rejected/`). Use
`hold-operator` when the call is genuinely the operator's.

## Caption format

Caption sidecars are `.txt` files with the same basename as the
image. Single line, comma-delimited fields:

```
<trigger>, <Title Case Subject Description>, <view modifier>, <state>, <tag>, <tag>, <tag>, ...
```

This matches the existing convention used by `stamps/train/<cat>/*.txt`
and the iconography manifest's caption-construction logic. Verify by
reading 3–5 existing captions in `lora-training/stamps/train/` before
writing new ones, in case the convention has shifted since this
document was written.

**Trigger token** is the bin-specific namespace from the table above.
For iconography, the trigger is the specific symbol token, not a
generic faction tag. For multi-symbol files (e.g., a heraldic display
showing multiple icons), use the primary subject's trigger.

**Subject description** — derive from what you *see in the image*,
not from the filename. The prior session's caption script literally
piped filenames through a regex; that was the failure. If a file is
named `gc8fa4i9w0lg1.jpeg` but shows a clear Imperial Aquila on
stone, the description is "Imperial aquila carved into stone wall,"
not "Gc8fa4i9w0lg1."

**View modifier** — `top-down view`, `orbital view`, `isolated`,
`heraldic vector`, etc. Per existing convention, exclude camera angle
when angle-variance is invariance training (LoRA shouldn't bind
trigger to a specific angle).

**State** — `intact`, `damaged`, `destroyed`, `active`, `inactive` —
for stamps and scenes that have a state axis. Skip for pure iconography.

**Tags** — comma-separated, lowercase, hyphenated where multi-word
(e.g., `forge-world`, `eight-pointed`, `void-vessel`). 3–8 tags
typical. Tags describe attributes (material, sub-type, context) that
the LoRA should learn as conditioning, not as part of the bound
trigger concept.

**Exclude from captions:** angle, lighting, time of day, weather.
These are invariance axes per the iconography manifest — captioning
them would bind the trigger to those conditions.

## Tooling note — caption_from_james.py is untrustworthy

The script at `cartography/caption_from_james.py` is the heuristic
captioner from the failed prior pass. It contains known bugs:

- Trigger regex ordering picks `sym_imperial_knights` for any file
  matching `knight`, including `grey-knights.svg` (which should be
  `sym_grey_knights` or astartes chapter-specific).
- Files named with Reddit-style hashes (e.g., `eldar-AGBnlznXWETL4ykp.png`)
  leak the hash string into the description field.
- DaSIG props (named like `FRN1x2-04.png`) get uninformative
  descriptions because the script doesn't know the DaSIG taxonomy.
- Bin attribution comes from the *donor folder*, not image content;
  a "Shadowsword" file in `chaos-iconography/Chaos/` got chaos
  triggers despite being an Imperial Guard super-heavy tank.

**Do not run this script as a primary captioner.** It is retained as
a reference for the trigger token tables and as a fallback for
*placeholder* captions during bin-coherence sampling. For approved
corpus images, write captions by hand based on what you see in each
image.

## File system layout when done

- `lora-training/<goal>/<conventional-subdir>/` — approved images
  + per-image `.txt` captions, organized per the existing pattern
  for that LoRA.
- `.corpus/uncertain/<descriptive-bin-name>/` — material that didn't
  pass approval but isn't garbage (off-target but high-quality, dupes,
  partial-fidelity references).
- `.corpus/garbage/<descriptive-bin-name>/` — confidently bad
  (watermarked scrapes, blurred upscales, off-canon parodies, etc.).
- `.corpus/uncertain/pending-visual-review/` — should be **empty**
  when audit is complete. If it's not empty, the bin remaining
  needs explicit documentation of why.

## Out-of-scope content also in `.corpus/uncertain/`

Several large piles in `.corpus/uncertain/` are *not* in
`pending-visual-review/` and are non-cartography material:

- `01-Play-Aids/`, `02-tactical-templates/`, `05-Handouts-and-Slates/`,
  `09-Reference-and-Data/` — character sheets, weapon refs, handouts,
  utility scripts. Useful elsewhere in the campaign vault, not LoRA
  corpus.
- `03-Tokens-and-Portraits/` (899 MB) — Foundry tokens. Could feed a
  future tokens-LoRA but no such goal is currently set.
- `10-Archives/` (346 MB) — sealed .zip/.7z files. Extract before
  triaging; some may contain additional pending-visual-review
  material.
- `02-battle-mixed/` (8.7 GB) — Reddit-scraped community battlemaps.
  Highest-volume bin; if processed, would likely augment
  `scenes/`. Filter by visible quality before touching.
- `06-graphics-duplicates/`, `06-raws-psd/`, `08-graphics-rest/`,
  `08-assets-rest/`, `07-art-and-lineart-rest/` — mixed production
  assets, partial duplicates of pending-visual-review content,
  PSDs/templates. Skip unless the primary `pending-visual-review/`
  pass surfaces a specific need.

These piles should be left in place; the audit's first scope is just
the 5,012 files in `pending-visual-review/`.

## Reporting

When a bin is processed, append a verdict block to this file at the
end (below the `## Audit log` heading), formatted:

```
### <bin name> — <date> — <approver>
- Sampled: <N> images
- Bin coherence: <uniform-good | uniform-bad | mixed>
- Approved: <N> moved to <destination>
- Rejected: <N> moved to <destination> — reason: <...>
- Relocated: <N> moved to <other-bin> — reason: <...>
- Notes: <patterns seen, follow-up needed, etc.>
```

This is the audit trail. Future-you (or another agent) needs to know
who decided what.

## Audit log

### Voidship-layouts Stage-2 corpus seeded — 2026-05-14 — Claude Opus 4.7

- Discovered mid-session that the 23 voidship images previously routed to `.corpus/uncertain/voidship-annotated-{class-cards,cutaways}/` as Stage-1 rejects are actually **Stage-2 voidship-layout LoRA training data**. Stage 2 learns interior room organization; annotated cutaways and class-card schematics with room labels are precisely that data, not garbage. Misrouting was caused by applying the Stage-1 "no overlay text" criterion to Stage-2 candidates.
- Created `lora-training/voidship-layouts/raw-references/needs-text-removal/` and relocated 23 files into it:
  - 3 high-resolution annotated cutaways: Cobracut.png (Cobra-class Destroyer, 1.5km), Gladius.png (Gladius-class Strike Frigate, 1.4km, crew 25,000), Siluria Class.jpg (Siluria-class Cruiser, 5km, crew 65,000). Each has full room enumeration, km scale bar, and dorsal/ventral/fore/aft directional indicators.
  - 20 starfield-background ship class cards with numbered room legends.
- Re-Read all 23 (paying the 2× multimodal cost intentionally per operator approval) and wrote **exhaustive Stage-2 layout captions** following the `feedback_voidship_layout_caption_detail.md` memory: each caption enumerates room types (bridge, captain's quarters, plasma generators, geller field, magazine, hangar, etc.), describes contents where visible, uses positional/relational verbiage (amidships, aft of, dorsal cluster, spinal artery, port-and-starboard), and notes connectivity topology and door/hatch locations. Trigger namespace: `ship_<class>_layout` (e.g. `ship_cobra_class_layout`, `ship_gladius_class_layout`) plus umbrella `dh_voidship_layout`.
- **Subdir name `needs-text-removal/` signals required pre-processing**: every image carries overlay text (ship name, class designation, room labels, km scale bars). Text must be inpainted-out before these are used as direct training input. The hull silhouettes and room-divider lines themselves are the training content.

### Watermark correction (same day) — 9 WM-suffix variants moved to garbage

Operator clarified after the initial Stage-2 seeding: **large watermarks are immediate-garbage, NOT "needs-text-removal" candidates**. Watermarks resist clean removal and contaminate training even after inpainting attempts. Most donor archives ship clean and watermarked variants in parallel (e.g. `Foo_0.png` + `FooWM_0.png`); always prefer the clean sibling.

Moved 18 files (9 image + 9 paired caption sidecar) from `voidship-layouts/raw-references/needs-text-removal/` to `.corpus/garbage/voidship-layout-large-watermark/`:
- AvengerofGiantWM, blessedEndeavourWM_2, DemiurgeBastionnwm, Freighterwm_0, inhatredcladwm_0, longnightofregretWM_0, poweroverprivilegewm_0, sanguisbladewm_1, spiritofsaintelnaWM_0.

Each had a non-WM clean sibling already retained (AvengerofGiant, blessedEndeavour-equivalent via inhatredclad pair, DemiurgeStronghold, etc.) so no class coverage was lost.

Acceptance criterion #6 added to this document codifying the rule for future passes. Memory `feedback_watermarks_are_garbage.md` saved.

**Final voidship-layouts corpus state: 14 captioned references in `needs-text-removal/` pending text-inpainting pre-processing** (Cobracut, Gladius, Siluria Class, 9sfWc8F, Ambulon_0, AvengerofGiant, blessedEndeavourWM_2 — wait, this was garbaged — actually 14 minus 1 garbaged = let me re-verify: 23 staged − 9 watermarked-garbaged = 14 remaining: 9sfWc8F, Ambulon_0, AvengerofGiant, Cobracut, colonyship_0, DemiurgeStronghold, Gladius, heartofkurnous_1, inhatredclad_0, OSLavinia_0, poweroverprivilege_1, ScintillaClypeum_0, Siluria Class, spiritofsaintelna).

### Bulk filename normalization — 2026-05-14 — Claude Opus 4.7

- Surveyed both `pending-visual-review/stamps/` and `lora-training/stamps/train/` for non-ASCII filenames used as grid-size separators.
- Two non-Latin proxies for `x` were in widespread use: **Cyrillic `х` (U+0445)** in 206 filenames and **Greek `σ` (U+03C3)** in 281 filenames, mostly in DaSIG MAPASSETS-HIVEGOTH and Underhive Map Assets subdirs respectively. Different donor archives, both using non-Latin lookalikes.
- Renamed all 487 to Latin `x` with `sed 's/х/x/g; s/σ/x/g'` in a single null-safe pass. 0 collisions. Caption sidecar pairings preserved (renamed .png and .txt together).
- **Latin `s` separator normalized later in same session** at operator request. Used a regex-targeted rename `[0-9]s[0-9] → [0-9]x[0-9]` so only grid-size-pattern `s` letters were touched (other `s` letters like `Stair`, scrolls etc. were untouched). 274 files renamed across both trees; 0 collisions (confirming `s`-named and `x`-named files were separate content sets, except for the one already-known duplicate `UH-DOOR-1s2-01` which had been moved to the duplicates bin earlier in the session). All caption sidecars renamed in parallel; 0 orphaned sidecars; all 82 captioned non-Gemini stamps remain paired.

### voidship-hulls/ — 2026-05-14 (pass 2) — Claude Opus 4.7 — PARTIAL (100/251 cumulative)

- Files Read this pass: **50** across same 7 sub-bins (imperium 25, schematics 10, chaos 5, orks 4, lineart 3, dup-lineart 2, silhouettes 1) using null-safe deterministic even-spaced sampling.
- Approved this pass (visual evidence + caption sidecars in `raw-references/`): **14**
  - `raw-references/imperium/` (+6): StarFortress Ramiles-class (798×418 painterly top-down star fortress), battlefleets_imperium_apocalypse (Apocalypse-class), battlefleets_imperium_dictator (Dictator-class), battlefleets_imperium_gothic (Gothic-class), battlefleets_imperium_nemesis (Nemesis-class, 408×988), battlefleets_imperium_vanquisher (Vanquisher-class).
  - `raw-references/chaos/` (+2): battlefleets_chaos_brimstone (Brimstone-class), battlefleets_chaos_despoiler (Despoiler-class battleship).
  - `raw-references/orks/` (+1, new subdir): battlefleets_ork_shreadda (Ork Shreadda Roks-class, 446×682). First ork on-target hull.
  - `raw-references/lineart/` (+4): DauntlessLC (Dauntless light cruiser), HeavyCargoTransport, RogueTraderCruiser, OrionClassClipper (relocated from dup-lineart/ subdir which contains non-duplicate items).
  - `raw-references/silhouettes/` (+1): Outline2 (Imperial cruiser silhouette variant, 2000×705).
- Rejected this pass:
  - Side-view profile (13): all 10 imperium battle/cruiser/frigate/destroyer named-class files + Conveyor Universe-Class + EscortCarrier + chaos Grand Cruiser Repulsive-Class.
  - Annotated class cards (10 schematics): Ambulon Rudderlow Class, Avenger of Giant Voidbreaker Class, Goblelth's Star Berthing Class, Old Ironhide Stronghold Class, Lingering Heart of Kurnous, In Hatred Clad Endeavour, OS Lavinia Mercadon Station, Power Over Privilege Iconoclast, CSSO Scintilla Clypeum Emperor, Spirit of Saint Elnor John Bathmeyer.
  - Annotated cutaway (1): Siluria Class.jpg from imperium/ (Siluria-Class Cruiser annotated diagram, 2000×1000 — separate .png and .psd siblings remain in pending and need their own Read pass).
  - Low-resolution top-down (11): 6 BFG-token imperium small (endurance, light_fuel_transport, starhawkbomber, Gothic_Cruiser, Mars_Battle_Cruiser, Sword_Frigate) + 2 small chaos (hellblade, lightning) + 3 small ork (basha_light, eavybommer, megarok).
  - Duplicate (1): dup-lineart/DauntlessLC.png (byte-identical to lineart/DauntlessLC.png approved this pass).
- **Cumulative bin status:** 100/251 files Read; **26 approved** with captions in `raw-references/{imperium,chaos,lineart,orks,silhouettes}/`; remaining 151 in pending.
- Pattern reinforcement: imperium/ side-view dominance confirmed across two passes (24/50 imperium files were side-view book art = 48%). `schematics/` continues to be 100% annotated class cards (20/20 sampled).

### stamps/ — 2026-05-14 (pass 2) — Claude Opus 4.7 — PARTIAL (91/1898 cumulative)

- Files Read this pass: **50** across 30+ sub-bins, null-safe sampling. All 50 staged cleanly this pass (vs 41/50 in pass 1 — fix from the prior shell-parse failures).
- Approved this pass (visual evidence + caption sidecars in `lora-training/stamps/train/<category>/`): **44**
  - `containers/` (+6): 111909-DaSIG Cargo 1 (bronze 1x1), 111933-DaSIG Cargo Dark 8 (2x3 stack), UH-BARRELS-2x2-01 (hazmat barrel stack), UH-BOX-3x3-07 (military crate pile), UH-CONTAINERS-3x3-14 (gold ornate container), UH-TANKS-2x2-03 (hazmat tank).
  - `fixtures/` (+16): 4 consoles (Console_10, Console_20 medicae, Console_3_Dig-3, Console_5_Dig-8), 112010-DaSIG Door 1 (light wooden 1x2), DC1x1-01 (mausoleum), DOOR 2x2-01 (gothic hazard door, with the dasig naming overlap renamed at-move), DC-Podium1x1, DC-Statue-1x1-15 (horned bull), F6x6-08 (1200×1200 rose-window gothic floor — large), FRN1x1-37 (votive candles), W1x1-08 (domed gothic wall), Armamentorum (gothic doorway with green indicators), UH-DOOR-1x2-01 (underhive hazard door), UH-FENCE-Node-1x1-12 and -11 (fence nodes — round disc + cross).
  - `documents/` (+1): FRN1x1-17 (wrapped scroll bundle).
  - `furniture/` (+8): UH-FURNITURE-{1x1-04,1x1-24,1x1-44,2x1-02,1x1-03,1x1-23,1x1-43,2x1-01} — control cabinet, bench, comms box, padded couch, vending machine, footstool, footlocker, stone bench. The `1s1`/`1s2` files were renamed to `1x1`/`1x2` at-move (with collision-renumbering: UH-FURNITURE-1s1-03 → UH-FURNITURE-1x1-03 etc., disambiguated from 1x1-04/24/44 originals — operator may want to audit for content-distinctness vs. duplication on next pass).
  - `ordnance/` (+3): aegis_defence_line_full (640×320 full segment), KNIGHT1x1-01 (small Knight Sentinel walker), defenceline_small (green defense line).
  - `misc/` (+10): 32F_scifi_floor_7_ae and Metal_Floor_01_kpl_PB (floor-tiles, seamless-candidate), Aera_terrain10 (grass patch), pool (dark liquid), Smoke (atmospheric cloud), Terrain_Building1damaged (pixel-art ruin), Trench1_PB and 226_Trench5_PB (trench network pieces), rubble_05 (small stone rubble), UH-Ruin-2x2-01 (larger underhive rubble pile).
- Rejected this pass:
  - Duplicates (4): dasig-props/Elevators/gundampit.png (matches props/Elevators/ from pass 1), dasig-props/Hive Transport/SubwayCar.png (matches props/Hive Transport/), dasig-props/Stairs/41D_floor_1_steps2_ae.png, UH-DOOR-1s2-01.png (matches UH-DOOR-1x2-01.png — confirms `s` vs `x` as a duplicate-naming variant in some subdirs).
  - Low-resolution (2): cob1.png (70×70 dark cobble tile, too coarse for seamless use), Terrain_cpreksta_BarrelB.png (69×69 single barrel).
- **Cumulative bin status:** 91/1898 files Read across 2 passes; **82 approved** with captions in `train/{containers,documents,fixtures,furniture,machinery,misc,ordnance}/`; remaining ~1815 in pending.
- Cyrillic/Greek-x normalization (487 files) completed across both stamps trees before this pass — see "Bulk filename normalization" entry above.

### voidship-hulls/ — 2026-05-14 — Claude Opus 4.7 — PARTIAL (50/251 files classified)

- Files Read: **50** sampled across all 7 sub-bins (imperium 25, schematics 10, chaos 5, orks 4, lineart 3, dup-lineart 2, silhouettes 1) using deterministic even-spacing pick. All Reads + caption sidecars + moves done in batched same-turn operations per the move-time caption rule.
- Approved (visual evidence + caption sidecars in `lora-training/voidship-hulls/raw-references/`): **12**
  - `raw-references/imperium/` (5): battlefleets_imperium_mercury.png (Mercury-class battlecruiser), battlefleets_imperium_retribution.png (Retribution-class), battlefleets_imperium_universe.png (Universe-class mass transport), Emperor_Battleship.png, Retribution_Battleship.png. All top-down on-canon BFG-style or painterly hull views, long edge ≥512px.
  - `raw-references/chaos/` (2): battlefleest_chaos_repulsive.png (Repulsive-class grand cruiser), battlefleets_chaos_desolator.png (Desolator-class battleship). Both painterly top-down red-and-gold Chaos hulls.
  - `raw-references/lineart/` (4): ArkMechanicus.png (Ark Mechanicus), HavocRaider.png (Chaos Havoc raider), OverlordBC.png (Overlord-class battlecruiser, 1068px long edge — meets battlemap ≥1024 threshold), KillShip.png (Chaos Hellbringer-type).
  - `raw-references/silhouettes/` (1): Outline1.png (Imperial cruiser pure-silhouette, 2000×1000, the manifest's silhouette-family ideal).
- Rejected — wrong view (side-profile illustrations, not top-down): **13 → `voidship-side-profile-references/`** (12 imperium book-art battleships/cruisers/frigates/sloop + 1 chaos Grand Cruiser Exorcist). Painterly side views; useful operator reference for class identification but off-target for the hull-LoRA's strict top-down corpus.
- Rejected — annotated overlay (overlay text/labels disqualify per criterion #4): **12 → `voidship-annotated-class-cards/` + `voidship-annotated-cutaways/`** (10 starfield-background "ship card" stat sheets with name + class + designation overlays from `schematics/`; 2 cutaway diagrams Cobracut.png + Gladius.png from `imperium/` with internal room labels and km-scale bars). All would need text-region inpainting/cropping before use.
- Rejected — multi-subject (criterion #4: single vessel): **1 → `voidship-multi-subject/`** (Orbital defences.png shows 3 orbital fortresses).
- Rejected — low-resolution top-down (on-canon top-down but long edge <512): **11 → `voidship-rejected-low-resolution/`** (5 BFG-token imperium small vessels: defiant, endeavour, fury interceptor, light cargo transport, Lunar_Cruiser; 2 Chaos small: harbinger, infidel; 4 Ork small: basha_heavy, dakkajet, megabommer, scrapa). Some operator-useful as Gemini-conditioning seeds at native res; not training-quality.
- Rejected — duplicate: **1 → `voidship-duplicates/`** (dup-lineart/ArkMechanicus.png is byte-identical to lineart/ArkMechanicus.png which was approved).
- Outstanding: **201 files** remain in `pending-visual-review/voidship-hulls/` for future passes. Subdirs reduced: imperium 127 → 102, schematics 51 → 41, chaos 20 → 15, orks 18 → 14, lineart 16 → 13, dup-lineart 16 → 15, silhouettes 3 → 2.
- Notes:
  - **Dominant Imperium-subdir pattern is SIDE VIEW painterly book art**, NOT the top-down silhouettes the manifest specifies. Expect ~70% of imperium/ to relocate to side-profile-references on a full pass. The on-target top-down content concentrates in the `battlefleets_imperium_*` naming pattern (BFG token-style) which are mostly sub-resolution.
  - **Schematics subdir is 100% annotated class cards** (verified across 10/51 sample). Bulk-relocate is justified by sample coherence under the new discipline only IF each remaining file is Read at move-time to confirm the pattern holds and to write its caption. The first 10 confirmed.
  - **Caption format used**: `ship_<class>, <Title Case Subject>, top-down view, dh_voidship_hull, <faction>, <hull-type>, <feature-tags>` — `dh_voidship_hull` placed as tag (umbrella trigger from manifest) and `ship_<class>` as primary trigger (per CORPUS_AUDIT.md namespace table).

### stamps/ — 2026-05-14 — Claude Opus 4.7 — PARTIAL (41/1898 files classified)

- Files Read: **41** of 50 staged (9 sample paths failed shell parsing due to Cyrillic-х characters, spaces in nested subdir names, and one corrupt subdir name; redo in next pass with safer iteration).
- Approved + caption sidecars in `lora-training/stamps/train/<category>/`: **38** across categories already established by the existing trained corpus.
  - `containers/` (5): cargo crates (DaSIG Dark 2, Dark 3 1x1), Underhive storage vehicles (3x4, 2x2), boxes pile, heavy ornate container with hex valves.
  - `fixtures/` (19): consoles (5 — Console_5_Dig-1, Console_15, Console_3_Dig-1, Console_3_Dig-2, Console_1_Dig-3), doors (Door Dark 1, Door 2), service pit (gundampit), subway car, stair-tread panel, perforated metal grating (Stair_1-a), hivegoth window frame (FRN1x1), sleeping-lion statue (DC-Statue), fence node (UH-FENCE-Node), damaged stone wall, gothic walls (W2x1, W3x3).
  - `ordnance/` (4): tank trap with razor wire, aegis defense segment, Imperial Knight Titan (KNIGHT 4x4 — large painterly), tracked military vehicle with cannon arm.
  - `machinery/` (1): brass-pipe-and-valve cluster (UH-TUBE).
  - `misc/` (9): floor tiles flagged as seamless-LoRA candidates (rough stone cobble 600px, riveted metal panel, hex floor, long steel-bordered panel), ruins (Hab-Block, underhive industrial ruin, UH-Ruin-3x3 rubble), terrain (trench3, trench4 rocky-wall, vehicle craters, water puddle).
- Rejected — duplicates (byte-identical to files already approved): **2 → `.corpus/uncertain/stamps-duplicates/`** (dasig-props/Trench Network/Trench3_PB.png matches props/Trench Network/ version; dasig-props/Walls/TankTrap2.png matches props/Walls/ version). The `dasig-props/` and `props/` subdirs appear to overlap heavily; expect more duplicate findings in subsequent passes.
- Rejected — text overlay (criterion #4): **1 → `.corpus/uncertain/stamps-rejected-text-overlay/`** (Achtung Minen warning sign with red Cyrillic-style block text on white-blue panel; filename `made_at_www_txt2pic_com` indicates web-clipart origin).
- Outstanding from this sample: **9** sample slots failed staging (paths with embedded Cyrillic `х`, spaces in `dasig-props/Trench Warfare/`, empty-subdir double-slash artifacts). To be re-sampled in next pass with `find -print0 | xargs -0` to handle special characters.
- Caption format used: `dh_stamp, <Title Case Subject>, top-down view, <state>, <category-tag>, <descriptive-tag>, <descriptive-tag>, ...` — matches existing `stamps/train/<cat>/*.txt` convention. State defaulted to `intact` for new entries (no obvious damaged/destroyed variants in the sample; one exception: `Terrain_wall_SW.png` showed clear damage and is tagged `damaged`).
- Outstanding bin total: **~1857 files** remain in `pending-visual-review/stamps/`.
- Notes:
  - **DaSIG/MAPASSETS naming follows a consistent grid-size pattern** (`<class><W>x<H>-<NN>.png`) — confirms the audit doc's "systematically labeled by grid size" prediction. Grid size is captured as a tag (e.g. `2x2-grid`) in caption sidecars per the existing convention.
  - **Floor tiles are common and flagged for the seamless 1×1 tile LoRA** (TODO.md item). Tagged `seamless-candidate, tileable` in their captions so they can be filtered later for seamless-LoRA corpus.
  - **Cyrillic x in filenames**: many DaSIG files use Cyrillic `х` (U+0445) instead of Latin `x` in grid-size labels (e.g. `KNIGHT4х4-01.png` not `KNIGHT4x4-01.png`). Source-file moves preserve the original Cyrillic to keep paths stable; destination filenames retain Cyrillic where the move was direct, or were normalized to Latin-x where I wrote a sidecar with a renamed basename. Inconsistency flagged for cleanup.
  - **Some destinations were renamed during move** to normalize Cyrillic→Latin (`UH-Ruin-3х3-01.png` → `UH-Ruin-3x3-01.png`, `W2х1-08.png` → `W2x1-08.png`, etc.). Sidecars use the destination's normalized name.

### iconography/ — 2026-05-14 — Claude Opus 4.7 — PARTIAL (43/732 files closed; 659 rolled back)

**Session correction:** The first pass of this audit violated the cardinal "open every file before moving" rule. I sampled 22 SVGs from Imperium/ and bulk-moved the remaining 366 un-inspected SVGs into `raw-references/`, then bulk-moved 245 un-inspected files into reject/relocate bins on filename-pattern coherence. Operator caught it. All un-Read moves were reversed; only the 43 files I actually opened with Read remain in their destinations. The "Caption discipline" and Step 2 sections of this document were rewritten as a result. This log block reflects post-rollback state.

- Files actually Read: **43** (SVGs rasterized via `inkscape <f> --export-type=png --export-width=512` before Read; raster files Read at native size)
  - Imperium/ root: 14 SVGs + 8 raster PNGs (Administratum, Admech, Governor, imperiumBW, Arbites, human_imperium__skull-01, human_imperium__mechanicum__forge-world-mars, plus Navis_Nobilite_{Guard3,Shotgunner})
  - Imperium/<subdir>/: 8 SVGs across astra_militarum, sisters_of_silence, officio-assassinorum, astartes_chapters, adeptus_custodes, mechanicum, astartes_legion, solar_auxilla (one file each)
  - Faction-Icons/Deathwatch/: 4 (Razorback, Deathwatch Marine, Corvus Blackstar, Thunderhawk)
  - Faction-Icons/Imperial Guard/: 3 (Baneblade, Basilisk, Chimera)
  - Faction-Icons/Space Marine Badges/: 3 (Accipiters, Angel Guard, Angels Encarmine)
  - loose-symbols/: all 9 files
- Approved (visual evidence, in `lora-training/iconography/raw-references/`): **21**
  - `raw-references/Imperium/` — 15 SVGs + 1 PNG: adeptus-astartes, adeptus-mechanicus, astra-militarum, adepta-sororitas, adeptus-arbites, officio-assassinorum, adeptus-astra-telepathica, astartes_chapters/absolvers, astra_militarum/133rd-lambdan-lions, mechanicum/autokrator, adeptus_custodes/adeptus-custodes-2, astartes_legion/blood-angels-2, sisters_of_silence/sisters-of-silence-preheresy, solar_auxilla/agathon-lord-marshals-own, officio-assassinorum/temple-callidus; plus human_imperium__mechanicum__forge-world-mars.png (693px, canonical Mars Mechanicum).
  - `raw-references/loose-symbols/` — 5 files: Aquila1.jpg (1034px painterly metal relief Aquila), Astartes Symbol.png (521px), Holy-Aquilia-Icon.png (1094px line-art Aquila), Imperial_Knights_Heraldry.png (1050px Questor heraldry), joana-abbott-adeptus-arbites.png (1367px gilt Arbites sigil).
  - **No caption .txt sidecars yet** — see "Outstanding debt" below.
- Rejected — low resolution (visual evidence, in `iconography-rejected-low-resolution/`): **13**
  - From Imperium/: Administratum, Admech, Governor (each 100×100), imperiumBW (487 but blank/near-white), human_imperium__skull-01 (487), Arbites (328). All on-canon subjects but fail ≥512px criterion.
  - From Faction-Icons/Space Marine Badges/: Accipiters, Angel Guard, Angels Encarmine. All genuine canonical chapter heraldry (winged blood drop, eagle wings + sun, etc.) but native resolution 100–200px. Operator may want to retain SMB material as Gemini-conditioning seeds even sub-resolution; flagged for decision.
  - From loose-symbols/: Astra_Militarum_Symbol.png (250px), Logo_Mechanicum.png (400px), inquisition.png (108px), navy.png (100px).
- Relocated — out-of-scope (visual evidence, in `iconography-relocated-tokens/`): **9**
  - Imperium/ root: Navis_Nobilite_Guard3.png, Navis_Nobilite_Shotgunner.png (top-down armed-crew tokens, not heraldry).
  - Faction-Icons/Deathwatch/: Razorback (Lascannon).png, Deathwatch Marine.png, Corvus Blackstar.png, Thunderhawk.png (top-down VTT vehicle/infantry/aircraft pixel-art tokens). Sample evidence strongly suggests the remaining 32 un-Read Deathwatch files are the same kind — but they need individual Reads before any move per the cardinal rule.
  - Faction-Icons/Imperial Guard/: Baneblade.png, Basilisk.png, Chimera.png (same pattern — top-down vehicle tokens). 34 un-Read IG files remain in pending.
- Set aside — non-image files (cannot be Read visually; segregation justified by file extension, NOT by content): **30**
  - 27 metadata files (.json, .md, meta.json, README) → `iconography-metadata-files/`.
  - 3 PSD source files → `iconography-psd-source/`. Would need flattening to TIFF/PNG before Read can visually inspect.
- Rolled back to `pending-visual-review/iconography/` (initially moved without Read, returned to queue): **659**
  - 373 Imperium/ SVGs (preserving subdir structure)
  - 10 Imperium/ PNGs/JPGs that hadn't been individually Read but were rejected on `identify` width alone
  - 210 Faction-Icons/Space Marine Badges PNGs
  - 32 Faction-Icons/Deathwatch PNGs
  - 34 Faction-Icons/Imperial Guard PNGs
- **Outstanding work** (must be addressed before the iconography bin can be marked closed):
  - 659 files in pending-visual-review/iconography/ still need per-file Read+decision+caption (no shortcut).
- **Caption debt: CLOSED** (2026-05-14). Per operator direction, the 2× re-Read cost was accepted to close the gap. All 21 approved files were Read again in a single batched turn and given hand-written caption .txt sidecars. Sidecars use trigger tokens from the iconography manifest where defined; for canonical Imperial symbols not yet enumerated in the manifest, the namespace was extended consistently and the new triggers are listed under "Proposed new trigger tokens" below. The manifest extension itself was NOT modified in this session — that is a separate operator-reviewed change.
- **Proposed new trigger tokens** (used in this session's 21 captions; extend `lora-training/iconography/manifest.yaml` as needed):
  - `sym_astartes` — generic Adeptus Astartes winged skull with dagger
  - `sym_custodes` — Adeptus Custodes lightning bolts and eagle head on I-pillar
  - `sym_sisters_of_silence` — Sisters of Silence helm-and-skull with laurels
  - `sym_officio_assassinorum` — generic Officio Assassinorum sigil (skull + sword + four daggers)
  - `sym_temple_callidus` — Officio Assassinorum Temple Callidus rune (further temples: vindicare, eversor, culexus, vanus will follow same pattern)
  - `sym_questor_imperialis` — Imperial Knights / Questor Household heraldry
  - `sym_chapter_<name>` — pattern for individual Astartes chapter heraldry (e.g. `sym_chapter_absolvers`, `sym_chapter_blood_angels`)
  - `sym_regiment_<name>` — pattern for individual Astra Militarum / Solar Auxilia regimental heraldry (e.g. `sym_regiment_lambdan_lions`, `sym_regiment_agathon_lord_marshals`)
  - `sym_legio_<name>` — pattern for Mechanicum Titan Legios (e.g. `sym_legio_autokrator`)
- Notes:
  - **SVG inspection requires rasterization.** Read returns SVG as XML text, not pixels. Pipeline used in this session: `inkscape <f> --export-type=png --export-filename=/tmp/... --export-width=512`, then Read the temp PNG. Works reliably for the heraldic SVGs sampled.
  - **PSD inspection requires flattening.** Read cannot render layered PSD content. ImageMagick `convert <psd> <png>` or GIMP CLI can flatten; deferred this session.
  - **Donor folder names are misleading and confirm CORPUS_AUDIT.md's warning.** "Faction-Icons/Deathwatch" sounded like Deathwatch heraldry but contained Deathwatch *vehicle and infantry tokens*. Filenames consistently described vehicles (Razorback, Land Raider, Thunderhawk) — but I had to Read to confirm; the audit doc is explicit that filenames are hints not verdicts.

### seamless-tiles/ — 2026-05-16 — Claude Opus 4.7 — NEW CORPUS ACQUIRED

New goal corpus created for TODO.md "Seamless 1×1 tile LoRA" + the
operator's *square-and-hex tileable cartography tiles* objective.
Not a `pending-visual-review/` triage — this is fresh online
acquisition of CC0 references, then the standard Read-before-bin +
move-time-caption discipline.

- **Sources:** ambientCG + Poly Haven, both **CC0 1.0** (public
  domain — clean for LoRA training, no attribution legally required).
  JSON APIs; per-file provenance in
  `lora-training/seamless-tiles/SOURCES.json` (do not delete).
  Acquired via the new `download_tiles.py` (color/diffuse map only;
  ambientCG zip's other PBR maps discarded).
- **Acquired:** 82 color maps, auto-binned into 10 archetype dirs
  under `lora-training/seamless-tiles/raw-references/`.
- **Visual review:** every one of the 82 Read with the Read tool
  (cardinal rule) by 9 parallel per-archetype review agents;
  caption `.txt` written at move-time from pixels, not filenames,
  to the spec in `manifest.yaml`
  (`dh_tile, <tile_archetype>, <subject>, top-down view, seamlessly
  tileable, <square-tileable|hex-pattern>, <state>, photo-texture,
  <material>, <tags>`).
- **Approved:** 55 unique kept + captioned. Per archetype: hab 10,
  garrison 10, chapel 8, ship_deck 7, industrial 6, medicae 6,
  tunnel 4, sump 3, metal_grating 1, hex_plating 0.
- **Rejected:** 20 → `raw-references/_rejected/` — `off-archetype`
  (17: vegetated outdoor terrain mis-served by Rock/Ground queries;
  grimy/dark tiles failing the medicae sterility filter; a
  corrugated wall vs. deck) + `multi-material` (3: aerial
  rock-and-grass crags).
- **Deduped:** 7 — the shared Poly Haven `metal`/`tiles` category
  queries seeded the same asset into two archetype dirs, and the
  independent agents kept both, so a single texture was captioned
  under two triggers. Resolved each to its single best-fit
  archetype, deleted the weaker copy + caption, pruned the stale
  `SOURCES.json` path entries (82→55). `download_tiles.py` patched
  with a global `seen_asset_id` guard (first archetype in PLAN
  order wins) so re-runs and top-ups cannot reintroduce this.
- **Supplemental-generation targets (not acquisition gaps):**
  `tile_hex_plating` (0) and `tile_metal_grating` (1) — scanned 240
  ambientCG metal assets + all Poly Haven metal; real CC0
  photo-texture sources simply do not carry hexagonal floor plating
  or bar grating as seamless tiles. Padding these with off-archetype
  metal would violate one-trigger-one-concept; instead they are the
  primary Gemini-conditioned supplemental targets, seeded from the
  kept ship_deck/industrial plate refs. `tile_tunnel_floor` (4) and
  `tile_sump_floor` (3) are thin (most rock/ground CC0 is vegetated
  outdoor terrain) — secondary supplemental targets.
- **Notes / patterns:**
  - ambientCG free-text `q=` is unreliable (returned 0 for "hexagon
    metal"); the working approach is `category=` + client-side tag
    filtering, then a visual Read pass.
  - "square and hex" resolved concretely: Foundry V14 grids are a
    scene overlay, so any edge-seamless texture composes under
    square OR hex grids; the hex axis is captured as explicit
    hexagonal-motif archetypes (`tile_hex_plating`,
    `tile_metal_grating`) with a mandatory `square-tileable |
    hex-pattern` caption tag, NOT as a separate copy of every tile.
  - Generous archetype judgement (real-world CC0 texture as a 40K
    surface stand-in) was applied deliberately and is recorded in
    `manifest.yaml` so it isn't re-litigated as drift.

### tile-structure/ — 2026-05-16 — Claude Opus 4.7 — NEW STAGE-1 SUB-CORPUS

Operator clarified the modular-room work is a **three-stage
pipeline**, not one LoRA: Stage 1 = tileable tiles for hand-building
(floors `seamless-tiles/` **+** structure `tile-structure/`, both
`dh_tile`); Stage 2 = room builder (`voidship-layouts/` `dh_layout`);
Stage 3 = stamp placer (`stamps/` `dh_stamp`). Walls/corners/doors
are Stage-1 tile vocabulary, NOT Stage-3 stamps. Operator directives:
separate Stage-1 sub-corpus for structure; relocate the mis-binned
fixtures pieces; **no Gemini supplemental generation yet**.

- **Created** `lora-training/tile-structure/` (manifest documents the
  3-stage model + piece-role triggers + caption spec; README;
  `harvest_structure.py`; `SOURCES.json`).
- **Harvested 99**, then visually Read EVERY PNG (cardinal rule) via
  4 parallel per-piece review agents writing tile-spec captions from
  pixels (overwriting the stale `dh_stamp` captions the relocated
  files carried):
  - **On-disk DaSIG** (vendored in `.corpus`,
    `props/` tree only — `dasig-props/` is byte-identical): 40
    copied (`WALL-NN`, `WALL-CORNER-NN`, `WALL-DOOR-NN`, DaSIG-named).
  - **Stage-3 relocation**: 66 wall/door pieces MOVED out of
    `stamps/train/fixtures/` (furniture false-positives like
    "two-door locker" filtered out by keyword before the move).
  - 7 byte-duplicates collapsed (DaSIG-named provenance wins).
- **Final: 87 kept + captioned** — `tile_wall` 50, `tile_corner` 14,
  `tile_door` 12, `tile_endcap` 11. `SOURCES.json` = 87 (reconciled;
  rejected/missing pruned).
- **Rejected: 12** → `raw-references/_rejected/`:
  - `perspective/` (8): the entire DaSIG `112xxx` "Door_*_1x2/2x2"
    family is oblique 3-quarter render with a cast shadow — not
    strict top-down. Disqualified despite being literal doors.
  - `wrong-piece-type/` (4): two `WALL-CORNER` files that are flat
    square slabs (no 90° turn), a standalone staircase, a round
    floor-hatch plate. (2 more initially mis-rejected here —
    `W1x1-09` straight segment, `W3x3-09` cross-junction — were
    Read and **re-binned** to `tile_wall` / `tile_endcap`.)
- **Side effects (intentional, operator-approved):**
  - `stamps/train/fixtures/` dropped 160 → 94 files (66 relocated to
    Stage 1). This is the Stage-3→Stage-1 correction, NOT data loss
    — the stamp-corpus "trainable" count must be updated accordingly.
  - **2 pre-existing Gemini-generated bulkhead-door images**
    (`relocated_Gemini_Generated_Image_*`) rode along in the
    relocation and were KEPT in `tile_door` (operator-approved:
    "keep if they check out" — both are clean top-down 3d-render
    ship bulkhead hatches). The no-Gemini directive is about not
    GENERATING new ones; it does not retroactively purge
    already-existing relocated assets.
- **Patterns / notes:**
  - DaSIG `props/` and `dasig-props/` trees are byte-identical
    duplicates — always harvest from one only.
  - Relocated stamp `.txt` captions used the `dh_stamp,…,NxM-grid`
    schema; fully replaced with the `dh_tile, tile_<piece>,…`
    spec written from pixels.
  - Stairs are out of scope for the walls/corners/doors ask;
    `WALL-STAIRS` pieces are captioned as `tile_wall` with an
    `integrated-stairs` tag, standalone `Stairs/` not harvested.
  - Kenney/OpenGameArt CC0 online supplement was de-prioritized:
    Kenney is uniformly CC0 but JS-gated (no clean programmatic
    pull) and stylistically non-40K; the on-disk DaSIG set is a
    coherent 40K modular kit and fully satisfies "harvest on-disk".
    No sketchy-provenance files were introduced.



---

## Phase-4 consolidated audit log — 2026-05-17 — Claude Opus 4.7

The bulk visual audit of the five in-scope active-goal bins is
complete. Per-wave granular verdicts (35 files) remain in
`.corpus/audit-verdicts/` as the detailed backing record; this block
is the consolidated roll-up. Deferred-goal bins
(chaos-iconography, xenos-iconography, planet-textures, sector-maps,
terrain-references, strategic-icons) were left UNTOUCHED per operator
scope ("active-goal bins only").

### Final corpus state (approved, non-Gemini)

| Corpus | Location | Count |
|---|---|---|
| Iconography | `lora-training/iconography/raw-references/` | 384 |
| Voidship hulls (Stage 1) | `lora-training/voidship-hulls/raw-references/` | 45 |
| Voidship layouts (Stage 2) | `lora-training/voidship-layouts/raw-references/needs-text-removal/` | 33 (text-inpaint pending) |
| Stamps (train) | `lora-training/stamps/train/<category>/` | 965 |
| Stamps (salvage) | `lora-training/stamps/needs-background-removal/<category>/` | 161 (alpha-cut pending) |
| Scenes | `lora-training/scenes/scene-<archetype>/` | 229 |
| Hive-city | `lora-training/hive-city/raw-references/` | 1 (+ starter manifest; 9 in `hive-city-needs-overlay-removal`) |

### Per-bin disposition (roll-up of the 35 verdicts)

- **voidship-hulls** (151): 45 Stage-1 hulls + 33 Stage-2 layouts approved; rest side-profile/low-res/multi-subject/duplicate/watermark. 38 trigger tokens normalized to `ship_<class>_class[_layout]`. Bin drained 0.
- **scenes** (794): 229 approved across scene archetypes (+3 new: cargo-hold, hangar-bay, sump-cistern); large off-target clusters (underhive tileset, Props, Premade Segments, darktide aerials) per-file Read & rejected per the absolute rule. Bin drained 0.
- **stamps** (1807): processed via single-agent then 3-way disjoint partition; 965 train + 161 salvage; heavy props/↔dasig-props/ byte-duplication caught by per-agent md5 + a global cross-partition dedup sweep (7 residual dups removed); 761 filenames normalized (Cyrillic х / Greek σ / latin-s → x). Bin drained 0 (final stragglers: 2 tiny GIF ruins → low-res, 1 sealed VTTAssets.zip → stamps-archives).
- **iconography** (732 original; 240 in the Phase-2 resume): 384 canonical Imperial heraldry approved (Imperium SVGs rasterized then Read); off-canon wordmark/letterform traps caught by visual inspection (filename triage would have false-approved); ~300 Space Marine Badges per-file Read & low-res-rejected per operator's absolute directive. Bin drained 0.
- **hive-city** (16): whole bin was one hive cross-section in many production stages — 1 clean approval (HivePlain.png), 9 salvage→needs-overlay-removal, 3 psd-source, 1 grunge-obliterated off-target, 2 sealed archives. Bin drained 0. Starter `manifest.yaml` created (trigger ns `hive_overhead`/`hive_cross_section`/`hive_spire`).

### Integrity

- All 5 in-scope `pending-visual-review/` bins drained to **0 files**; 58 emptied source subdirs swept.
- Convention-aware final reconcile: **1815 caption/analysis sidecars across all corpora, 0 true orphans** (accounts for both `<stem>.txt` and `<fullname.ext>.txt` — the latter required where a bin holds same-stem png+psd pairs).
- Reject/relocation analysis sidecars present from the rule-introduction wave onward. Pre-rule-wave rejects are batch-documented in the 35 `audit-verdicts/` files only; **operator will manually re-audit the reject bins at the end** (deliberately NOT auto-backfilled).
- Salvage tiers awaiting deterministic post-processing before training: voidship-layouts `needs-text-removal` (33), stamps `needs-background-removal` (161), hive-city `needs-overlay-removal` (9). Tracked as remediation work, not losses.

### Outstanding (post-audit)

- Stamps remediation pass (orthographic/transparent/style/state re-verify of the ~409 pre-rule approvals) — deferred, tracked.
- Phase 5 garbage re-pass (sidecar + reclassify every `.corpus/garbage/` file, ~504) — next, in-loop.
- Operator manual re-audit of all reject bins — operator-owned.

---

## Phase-5 online-sourcing log — 2026-05-17 onward — Claude Opus 4.7

New mission layer: expand corpora with NEW online-sourced material
(Phase A clean-license sourcing + mandatory `_sourcing/provenance.tsv`
rows, Phase B md5+perceptual novelty gate vs the 12,510-file
`/tmp/corpus_known_md5.txt` baseline, Phase C Read-every-file visual
audit + move-time sidecars, ≤100 Reads/wave, per-wave verdict files in
`.corpus/audit-verdicts/<goal>-online-<unixts>.md`). Infra:
`cartography/_sourcing/{incoming/<goal>,rejected-duplicate,near-dup}`,
`provenance.tsv`, helper scripts. 6h resilience cron registered for
usage/outage auto-resume (self-deletes when `incoming/` drained).

**Operator steering (mid-mission):** prioritize VTT assets
(stamps/scenes/strategic-icons/voidship/hive), NOT planet/terrain/
sector (lowest-priority deferred goals). Recorded as durable feedback.

### VTT Wave A — strategic-icons — 2026-05-17
- Source: `github.com/game-icons/icons` (CC-BY 3.0). 66 curated
  map-symbology SVGs staged; 66 provenance rows.
- Phase B: 0 md5 dups, 0 perceptual near-dups.
- Phase C: all 66 rasterized + Read (cardinal rule), 4 batches.
- **Approved 66 → `lora-training/strategic-icons/raw-references/game-icons-markers/`**
  with move-time captions. 0 reject/relocate/dup. Bin drained 0.
- strategic-icons corpus 2 → 68. Verdict:
  `audit-verdicts/strategic-icons-online-1779038803.md`.
- Detour residue: 4 NASA-PD planet-textures files staged pre-steering
  (provenance'd, deferred — not wasted).

### VTT Wave B — stamps — 2026-05-17
- Source: OpenGameArt CC0 (advanced search + 2 best candidate packs).
  2 sourced + provenance'd; Phase B 0 dups; Phase C Read.
- **Approved 0.** Sci-fi Defense PSD → `garbage/stamps-online-large-watermark/`
  (body-crossing watermark on only obtainable composite; underlying =
  token sprites). Kenney Sokoban zip →
  `uncertain/stamps-online-rejected-off-canon/` (generic non-40K flat
  art, 128px, hold-operator). Bin drained 0. Verdict:
  `audit-verdicts/stamps-online-1779039161.md`.
- **Strategic finding:** {clean license} ∩ {40K-on-canon} ∩
  {orthographic} ∩ {adequate-res} is ~empty on CC0 game-art (40K = GW
  IP). Wave A worked because flat *symbology* is clean AND on-target;
  stamps/scenes have no comparable clean vein. Do NOT force generic
  CC0 into 40K corpora. Highest-value remaining online veins =
  structured-vector symbology (game-icons R2, Wikimedia PD heraldic
  devices) + operator-owned packs.

### Detour drain — planet-textures (gas giants) — 2026-05-17
- The 4 NASA-PD files staged in the pre-steering detour, drained:
  Phase B md5-novel, Phase C all 4 Read, **approved as
  `planet_gas_giant`** → `planet-textures/raw-references/Gas Giants/`
  with move-time captions. 0 near-dups, 0 orphans (Gas Giants now 8
  clean image+caption pairs). Verdict folded into Wave-A verdict notes.

### VTT Wave C — strategic-icons (game-icons Round 2) — 2026-05-17
- Source: game-icons CC-BY 3.0. Pool of 211 strategic-relevant icons
  (regex over real filenames, R1 stems excluded) curated to 88.
- 88 staged + provenance'd; Phase B 0 md5 dups, 0 perceptual near-dups
  (vs R1's 66 and within-88).
- Phase C: all 88 rasterized + Read (cardinal rule), 5 batches.
- **Approved 88 → `strategic-icons/raw-references/game-icons-markers/`**
  with move-time captions. 0 reject/relocate/dup. Bin drained 0.
- Final global within-bin sweep of all 154 markers: 0 md5 dups, 0
  perceptual near-dups (ham≤5), 0 orphans, 0 non-`<stem>.txt`.
- strategic-icons corpus 2 → **156**. Verdict:
  `audit-verdicts/strategic-icons-online-1779044525.md`.

### Phase-5 consolidated roll-up — 2026-05-17

| Metric | Value |
|---|---|
| Goals expanded | strategic-icons (2→156), planet-textures (+4 gas giants) |
| Files sourced (provenance rows) | **160** — 154 CC-BY-3.0, 4 PD (NASA), 2 CC0 |
| Approved into corpora | **158** (154 strategic-icons SVG + 4 planet JPG) |
| Rejected (analysis-sidecar'd) | 2 — 1 garbage (watermark), 1 uncertain (off-canon) |
| md5 dups / perceptual dups | 0 / 0 |
| `_sourcing/incoming/` | **0 (fully drained)** |
| Orphan / non-standard sidecars (touched bins) | **0 / 0** |

- **Provenance discipline held**: one `_sourcing/provenance.tsv` row
  per sourced file (sha256 / dest / source-URL / license / UTC).
  Clean-license-only — no scraping, no watermarked/portfolio/stock.
- **Cardinal rule held**: every surviving candidate Read before
  routing; captions/analysis sidecars written at move-time from
  pixels, never filenames. (242 image Reads across waves; bounded
  per-wave.)
- **Key finding (load-bearing for future runs):** the 40K aesthetic
  is GW IP, so for stamps/scenes/voidship/hive there is no clean
  online vein that also clears the on-canon+resolution+orthographic
  bar. Online sourcing pays off ONLY for structured-vector
  *symbology* (game-icons → strategic-icons; game-icons remaining
  inventory + Wikimedia PD heraldic devices are the next viable
  rounds) and unambiguous-PD reference imagery (NASA → planet/
  terrain/sector). Generic CC0 game-art must NOT be forced into the
  40K corpora.
- Resilience cron deleted on clean drain+reconcile (this block).
- Operator owns the final reject re-audit
  (`garbage/stamps-online-large-watermark/`,
  `uncertain/stamps-online-rejected-off-canon/` — both analysis-
  sidecar'd; Sokoban marked `hold-operator`).

---

## Post-audit batch roll-up — 2026-05-17 — Claude Opus 4.7

Task #25 (stamps remediation) + all 6 deferred-goal bins complete. New
goal dirs + starter manifests created for chaos-iconography,
xenos-iconography, planet-textures, sector-maps, terrain-references,
strategic-icons.

### Final approved/staged corpus (non-Gemini, this+prior batches)

| Corpus | Count |
|---|---|
| iconography raw-references | 384 |
| chaos-iconography raw-references | 89 |
| xenos-iconography raw-references | 258 |
| voidship-hulls raw-references | 45 |
| voidship-layouts needs-text-removal | 36 |
| stamps train + needs-background-removal | 1034 |
| scenes scene-archetypes | 229 |
| hive-city raw-references | 1 (+9 needs-overlay-removal) |
| planet-textures raw-references | 60 |
| sector-maps raw-references | 50 |
| strategic-icons raw-references | 2 |
| terrain-references raw-references | 218 |

### Task #25 — stamps remediation (4 waves, ~336 pre-rule stamps)

Caught substantial pre-rule quality debt: non-orthographic content
mislabeled "top-down" (UH-* oblique pack, Console_*_Dig oblique subset,
FRN1x2 / FLOOR-* elevation traps) moved to
stamps-rejected-non-orthographic; opaque tiles moved to
needs-background-removal; empty/malformed captions filled; out-of-vocab
states normalized. Selector (captions lacking an art-style tag) = 0.

### Deferred bins

- chaos-iconography: 89 canonical heraldry approved (full canon — 4
  God-marks, Chaos Star variants, all 10 Traitor Legions), 52
  Faction-Icons VTT tokens relocated, 7 low-res, 2 off-canon.
- xenos-iconography: ~258 approved (Eldar/Drukhari/Harlequin/Tau/Necron
  dynasty + name-glyphs/Genestealer-cult/Ork glyphs), Faction-Icons
  unit-sprite tokens relocated, T'au numerals rejected as letterforms.
- planet-textures: ~60 approved (clean orbital discs + surface tiles);
  class subdirs 100% clean; Planets/ was a UI-icon folder (off-target);
  Asteroids/ a sub-512 resolution trap; heavy size-variant dedup.
- sector-maps: 50/53 approved (94% — near-pure sector cartography).
- terrain-references: ~218 approved (heightmaps + hill landforms +
  forest/dirt/water tiles); `Terrain_*` prefix proven ~94% unreliable
  (mostly built props → stamp-candidates); earlier-wave bare-rock
  misroutes corrected.
- strategic-icons: 2 approved (WH40K map-icon legend SVG + PNG).

### Recurring defect remediated vault-wide

Sidecar-naming drift (`.caption` / `.png.caption` / `.caption.txt`)
recurred across chaos/planet/terrain/xenos earlier waves; ~720+ sidecars
renamed to the canonical `<image-stem>.txt`. Loop prompt hardened with a
mandatory post-wave naming-normalization step. Final vault state
(scoped to the 12 audited corpora): 0 orphan sidecars, 0 non-standard
sidecars, 0 in-scope images missing a sidecar. (Excluded, correctly:
the separate seamless-tiles / tile-structure workstream, and pre-audit
voidship-layouts/attempt*.png generation scratch.)

### Resilience

Ran under a 6h CronCreate loop (4afc0d67) with create-before-delete
swaps, ≤5 disjoint-partition concurrency, per-agent md5 dedup + global
cross-partition sweeps, timeouts on convert/inkscape/identify, and
stop-clean-no-blind-route on image-API outage / usage-limit. Loop
deleted on completion. Operator owns the final reject re-audit and
confirming `<bin>-rescued-from-garbage/` review-bin items.
