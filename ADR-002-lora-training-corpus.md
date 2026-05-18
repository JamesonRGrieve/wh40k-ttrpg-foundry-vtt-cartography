# ADR-002: LoRA training targets & corpus construction

Status: Proposed (2026-05-18)

## Context

The pipeline today is one-directional: hand-prompt **Gemini** for a
stamp grid, extract (`extract_stamps.py`), classify (`classify_stamps.py`,
TODO §1), deploy (`build_mass_edit_pack.py`, TODO §3). Growing the library
into a gap — "we need three more variants of a damaged blast door facing
east" — means going back to Gemini and re-prompting by hand, with no
guarantee the new grid matches the house style.

Two facts make local generative expansion attractive:

1. The ComfyUI server (`198.51.100.11`, ComfyUI 0.18.1, RTX 3090,
   ~23 GB free) is **already configured for image *generation***, not
   classification (TODO §1). The hardware that will run Florence-2 can
   also train and serve diffusion LoRAs.
2. Once TODO §1 runs, every `stamps/<stem>_NN.png` has a sidecar with
   `description`, `tags`, `orientation`, `state`, and `group_id`. That is
   a ready-made **(image, caption) training corpus** — ~633 cut,
   transparent, consistently-styled assets — at zero extra labelling
   cost.

The corpus, surveyed across all 22 source grids, is stylistically tight
(hand-painted VTT-token look, grimdark 40k palette, isolated object on a
neutral background, soft drop shadow) but spans distinct content and two
distinct projections (true top-down floor features vs. ¾-isometric /
front-elevation props and structures).

This ADR decides **which LoRAs are worth training** and **how the corpus
for each is assembled**. It does not cover training-node selection on the
ComfyUI host (that becomes a TODO item) beyond feasibility.

## Decision

Train a small, layered set of LoRAs — not one-per-category. Fragmenting
~633 images into a dozen micro-LoRAs starves each of data and overfits.
The split below follows axes the project's own ontology already defines
(ADR-001: orientation, state, category) so the corpus filter for each
LoRA is just a sidecar query.

### Tier 0 — `dhcarto-style` (master style LoRA) — prerequisite

- **Why:** teaches the base model the house look (palette, lighting,
  isolated-object-on-neutral-bg framing, token aesthetic). Every other
  LoRA either stacks on this or is unnecessary if this is strong enough.
  Highest leverage; train and evaluate this first.
- **Corpus:** the *entire* deduped corpus. Trigger token `dhcarto`.
- **Caption template:** `dhcarto, <category-tags>, <orientation>, <state>,
  <free description>` — built directly from the sidecar.

### Tier 1 — projection specialists (2 LoRAs)

- `dhcarto-topdown`, `dhcarto-iso`.
- **Why:** the corpus splits hard between true top-down floor features
  (hatches, grates, drains) and ¾-iso/elevation props. A single style
  LoRA blended across both yields muddy perspective; ADR-001 already
  treats orientation as a first-class axis, so keep projection crisp.
- **Corpus:** sidecar filter on `orientation` — `{top-down}` vs.
  `{isometric, north, south, east, west}`. Stack on Tier 0 at inference.

### Tier 2 — `dhcarto-state` (state-variant LoRA) — unblocks ADR-001

- **Why:** ADR-001's runtime-cycling feature needs
  intact→damaged→destroyed / active→inactive variants of the *same*
  object. Gemini is unreliable at "same object, now wrecked." A LoRA
  trained on state-pair exemplars (img2img / ControlNet-guided from the
  intact stamp) lets us *generate the missing states for objects we only
  have one of* — directly filling the `group_id` gap the deploy step
  depends on.
- **Corpus:** all stamps whose `group_id` cluster (TODO §1d) has ≥2
  distinct `state` values, captioned with explicit state tokens.

### Tier 3 — domain LoRAs, only where the corpus is deep & distinctive

Worth their own weights (deep slice + hard for base models to fake the
40k greeble/gothic look):

- `dhcarto-doors` — bulkheads, blast doors, hatches, vault doors, gates.
- `dhcarto-machinery` — pipe junctions, vents, valves, generators,
  control panels.
- `dhcarto-structures` — manufactorum/cathedral mega-tiles and prebuilt
  map sections; highest-value, hardest-to-source map pieces.
- `dhcarto-props` — the long tail of set-dressing (mugs, bottles, books,
  papers, dataslates, lamps, crates, barrels) under one general
  "grimdark prop" model.

Explicitly **not** their own LoRA — folded in as tags under Tier 0/1
(insufficient stylistic divergence to justify separate weights, and
splitting fragments the corpus): medicae/lab, plain furniture, generic
containers, statuary.

### Explicitly de-scoped

A captioning/classification LoRA. TODO §1 already routes classification
to Florence-2; a bespoke tagger LoRA would duplicate it. Considered and
rejected.

## Corpus construction (shared mechanics)

1. **Source images:** `stamps/*.png` (already cut, RGBA). Flatten onto a
   neutral background matching the corpus, or retain alpha, per the
   chosen trainer's convention. Source grids and stamps remain untouched
   (CLAUDE.md hard rules).
2. **Captions:** generated from the sidecar — depends on **TODO §1
   running first** (hard dependency). One `.txt` per image, fixed trigger
   token prepended, fields templated as above.
3. **Dedup:** reuse the CLIPVision embeddings computed for TODO §1d;
   drop near-identical stamps above the same cosine threshold so a LoRA
   does not overfit duplicate cells.
4. **Per-LoRA slice:** a sidecar query (category / orientation / state /
   group_id) — no new labelling.
5. **Gap analysis = the "build corpus" half.** Any target slice with
   < ~60 unique images is under-resourced; that list becomes new TODO
   items and a Gemini prompt-recipe doc to author grids *specifically*
   for the thin slices, which then re-enter the normal extract→classify
   flow. Corpus growth stays input-driven and reproducible.
6. **Layout:** `lora-corpus/<lora-name>/{images,captions}` plus a
   generated `manifest.json` (stamp → caption → source provenance). New
   build directory; never deployed into Foundry (CLAUDE.md hard rule).

## Consequences

- **Sequencing:** TODO §1 (classification) gates all corpus building.
  Then Tier 0 → Tier 1 → Tier 2 (unblocks ADR-001 variant generation) →
  Tier 3 as depth allows. Gaps feed back into Gemini-grid authoring.
- **Hardware:** RTX 3090 / 24 GB → SDXL LoRA is the safe default
  (fits comfortably, well-tooled). Flux-dev LoRA is possible at 24 GB
  via fp8 / low rank but slower — recommend SDXL first, Flux as a later
  quality bump. The generation-configured server can host a trainer
  custom node and serve inference on the same box.
- **Pipeline shape:** the library stops being Gemini-bound. Gemini
  becomes the *bootstrap* and the gap-filler; routine expansion is local,
  style-locked, and reproducible from the corpus.
- **No silent corpus loss:** dedup and slicing are logged; a stamp
  excluded from a LoRA slice is recorded with the reason, mirroring the
  "never silently drop a stamp" rule.
