# Cartography TODO

Open work, in priority order. Items removed when done. Last refreshed
2026-05-07.

## Open

## TOP PRIORITY — Symbology rebuild (ControlNet structural guidance)

The current symbol_compose pipeline pastes flat black SVG canonicals
on top of the rendered scene. This is wrong for the spec: the
canonical is supposed to GUIDE diffusion to render the symbol AS
brass relief, embroidered banner, painted insignia on armor, etc.
Operator confirmed this in session — the chapel POC has a literal
SVG glued on, and the inquisitor portrait's rosette doesn't read as
a seal.

ComfyUI server has all required nodes installed (verified):
`ControlNetLoader`, `CannyEdgePreprocessor`, `LineArtPreprocessor`,
`ControlNetApplyAdvanced`, `Canny`, `InpaintModelConditioning`,
`VAEEncodeForInpaint`, `DifferentialDiffusion`, `SetLatentNoiseMask`.

Build:
1. New workflow `workflows/ScenePictureControlNetV1.json` with the
   Canny → ControlNetApplyAdvanced chain layered on the proven
   txt2img template.
2. Driver helper that emits a guide image (black canonical outline
   on transparent canvas at the anchor's bbox position) for each
   declared symbol.
3. Replace `compose_symbols()` calls in
   `generate_scene_picture.py` and `generate_character_portrait.py`
   with the controlnet-guided render path. Keep the literal-paste
   path available as `--symbol-style flat` for diagrammatic uses
   (sidebar badges, journal icons); make `--symbol-style integrated`
   the default for scenes/portraits.
4. Per-anchor prompt augmentation: the operator declares a material
   hint per anchor (e.g. `aquila:apse_back,large,brass-relief` or
   `inquisition_rosette:chest_center,large,armor-inlay`); the
   driver inserts that material hint into the prompt for the
   symbol's region.
5. Re-render `_deliverables/05_scene_pictures/district_4_chapel.png`
   and `_deliverables/06_character_portraits/inquisitor_bust.png`
   with the new pipeline so the Aquila and Rosette appear AS
   integrated material, not as glued-on SVG.

## HIGH PRIORITY — Multi-deck rebuild

Current `make_deck_variants.py` design is wrong. It takes a fully-
detailed layout PNG and adds openings; outputs are MS-Paint-quality
because the input was already a single hand-painted deck.
`_deliverables/08_multi_deck/` should be deleted from deliverables
or moved to `_intermediate/`.

Build:
1. Add `ship-bridge`, `ship-engineering`, `ship-barracks`,
   `ship-cargo` presets to `FLOORPLAN_PRESETS`. Shared outer hull
   dimensions across all four; deck-specific interior architecture
   (reactor well + control panels for engineering, console
   horseshoe + windscreen for bridge, bunk rows for barracks,
   container grid for cargo). Use clean rectangular regions in
   canonical region colors; mirror the precision of the existing
   `make-floorplan` presets.
2. Add a deck-specific floor texture entry in
   `INTERIOR_STYLE_FLOOR_TEXTURES` for each
   (`ship-bridge` = polished black metal with brass inlays,
   `ship-engineering` = ferro-grate over reactor coils, etc.).
3. Render each preset through `spacecraft --style ship-<deck>`
   to produce the actual battlemaps.
4. Replace `_deliverables/08_multi_deck/` with the rendered
   battlemaps, not the layout doodles.
5. Optionally: a `strip-to-shell` mode on `make_deck_variants.py`
   that takes ANY layout and outputs just the outer wall + bare
   floor, so an operator's hand-painted layouts can be re-used as
   shells for new deck variants.

## HIGH PRIORITY — Asset generation pipelines

Three pipelines for generating **new** assets (today the vault is purely
classify-what-Gemini-already-drew). All three share a cross-cutting
**symbol-preservation strategy** because diffusion models routinely mangle
canonical 40K iconography (Aquila feathers/heads/swords drift, Inquisition
`I` becomes generic crosses, Mechanicus cog teeth multiply). Symbol
fidelity is non-negotiable.

### Cross-cutting: symbol-preservation strategy

The foundational rule: **canonical symbols are PASTED, never generated**.
Diffusion is allowed to render style/atmosphere; it is NOT allowed to
render the symbology. Every symbol in our library has a canonical PNG
master with a sidecar JSON declaring its anchor / scale / lighting
behavior; downstream pipelines composite the master onto the diffusion
output rather than asking the model to draw it.

Layered approach (ordered by strictness):

1. **Library lookup.** `symbols/<name>/canonical.png` is the source of
   truth. Variants for lighting (dim, lit, candlelit, red-emergency)
   live as siblings (`canonical_dim.png`, `canonical_lit.png`, …).
2. **Anchor-point compositing.** Each generation workflow declares a
   layout/template that designates anchor points where symbols belong
   (e.g. `chapel_apse_back_wall: aquila`). The compositor pastes the
   right canonical at the right scale and angle.
3. **Lighting transfer pass (optional).** When the symbol must look
   integrated with scene lighting, compose against a shadow-map pass
   from the diffusion render so the canonical inherits the scene's
   ambient color/contrast without losing its silhouette.
4. **Validation.** After compositing, run a Canny-edge similarity check
   between the composited region and the canonical. If similarity drops
   below a threshold the asset is flagged for operator review.
5. **Hard prohibition.** Diffusion prompts must explicitly negate
   symbol generation: "no Imperial Aquila in the render, no eagle
   sigils, no Inquisition I, no Mechanicus cog — these will be
   composited separately as canonical art". Without this, Flux will
   try to render the symbol AND we'll paste over it, leaving artifacts.

Required infrastructure (build before any pipeline):
- `symbols/` directory with one folder per canonical symbol. Each
  folder contains `canonical.png` (transparent PNG, master), optional
  lighting variants, and `metadata.json` (anchor scale, allowed
  rotations, allowed mirroring).
- `symbol_compose.py` — utility module: `compose_symbols(image,
  anchor_specs)` pastes canonicals at named anchors; `validate_symbol(
  image, anchor_spec)` runs the Canny similarity check.
- Operator-provided canonical sources for at minimum: Imperial Aquila,
  Inquisitorial `I`, Mechanicus cog, Cult Imperialis flame, Skull-and-
  laurel sigil. These are GW IP; operator must supply or approve
  generated-then-locked references.

### Pipeline 1 — Stamp variant generator (gap-filling + new archetypes)

**Purpose.** Fill rotational and condition holes in the existing
615-stamp vault, AND produce wholly new archetypes (vehicles, full-body
poses, weapons) without sourcing new Gemini sheets.

**Workflow file:** `workflows/StampVariantsV1.json` (to build) —
img2img + IPAdapter encoding source-stamp style + ControlNet
depth/normal for rotational pose control.

**Driver:** `generate_stamp_variants.py` (to build) — takes a source
stamp + a list of desired variants {north, south, east, west, intact,
damaged, destroyed, active, inactive}, runs N renders, applies
symbol-compose pass if the source has any registered symbols.

**Acceptance for first cut:**
- Pick 5 source stamps with obvious gaps in their group (e.g. a desk
  that only exists top-down).
- Generate the missing variants.
- Run them through extract → make_sidecars → classify → assign_groups.
- Confirm group_id assigns the new variants to the SAME group as the
  source. If round-trip works, scale.

**LoRA fallback:** if prompt + IPAdapter caps out at ~70% style
fidelity, train a Solenne-style LoRA from operator training material
(~6-12 GPU-hours one-time). Defer until needed.

### Pipeline 2 — Character portrait generator

**Purpose.** Produce bust / full-body portraits for NPCs and PCs
matching the campaign's illustrated style. Today characters live as
text-only Markdown in `Characters/`; portraits would populate Kanka
sidebar images and Foundry actor portraits.

**Style target.** Painterly, grimdark, illustrative — closer to FFG-
era 40K RPG sourcebook art than the stamp-grid aesthetic. Operator may
want different stylistic options per character class (Inquisitor vs.
hive-ganger vs. Astropath).

**Workflow file:** `workflows/CharacterPortraitV1.json` (to build) —
Flux txt2img + ControlNet OpenPose for body composition + IPAdapter
for face consistency across multiple portraits of the same character.

**Driver:** `generate_character_portrait.py` (to build) — takes a
character name + body slot (bust|three-quarter|full-body) + style hint
+ optional reference IPAdapter image; outputs to
`Characters/portraits/<name>_<slot>.png` and writes a sidecar JSON
recording the seed/prompt for reproducibility.

**Symbol concerns:** robes/uniforms often carry Aquila or Inquisition
sigils. Compose canonical at anchor points (chest-front, collar,
shoulder-pad) declared in the portrait template per character class.

**Acceptance for first cut:**
- Generate portraits for 3 PCs at bust scale.
- Each portrait: zero hallucinated symbology in raw render (validated
  via the negative-prompt rule); one canonical Aquila composited where
  declared; symbol-validation passes.
- Operator approves stylistic match.

### Pipeline 3 — Scene picture generator

**Purpose.** Establishing shots, lore illustrations, document handouts,
investigation photos. Various aspect ratios; often heavy with multiple
canonical symbols (Imperial banners, Mechanicus signage, Aquila reliefs
on architecture).

**Workflow file:** `workflows/ScenePictureV1.json` (to build) — Flux
txt2img with optional ControlNet depth for spatial composition.

**Driver:** `generate_scene_picture.py` (to build) — takes a scene
spec (location wikilink, aspect ratio, mood, declared symbol anchors)
and produces an asset at `Lore/handouts/<slug>.png` or similar.

**Multi-symbol handling.** A single scene can require 5+ canonical
symbol composites (e.g. an Imperial chapel with Aquila on apse,
Inquisition `I` over door, skull-laurel on lectern). Symbol-compose
pass walks all anchors in declaration order.

**Acceptance for first cut:**
- Generate 3 scene pictures: Hab District 4 establishing shot, the
  District 4 Chapel interior (with at least 2 canonical symbols),
  and the Astropathic Relay Station (with 1 canonical symbol).
- All canonical symbols pixel-match their library masters after
  composite.
- Operator approves.

### Build order

1. Symbol library scaffolding + `symbol_compose.py` + canonical
   sources (operator action required to provide / approve).
2. Pipeline 1 (stamps) — closest to existing classify pipeline,
   shortest validation loop via group round-trip.
3. Pipeline 3 (scenes) — leverages stamp lessons; scenes are
   bigger but architecturally similar (txt2img + post-composite).
4. Pipeline 2 (portraits) — most distinct style; benefits from
   lessons learned in 1 and 3 about IPAdapter style consistency.



- [ ] **Chapel `--floor-only` thin perimeter trim (minor).** Round 4
  polish reduced the artifact: gilded mosaic now renders as a
  centered Aquila medallion (acceptable feature) plus a thin trim
  line along the perimeter. The chapel iconography prior is a strong
  Flux signal that resists prompt suppression. Operators can crop or
  accept; not blocking.
- [ ] **Foundry V14 stackable scene end-to-end test.** Real
  multi-room battlemap pair now staged at
  `dh-cartography/battlemaps/hab_3room_base.png` +
  `hab_3room_walls_alpha.png` (1792×1024, hab archetype, seed 42).
  Layout source at `hab_3room_layout.png`. Pending: deploy via
  `../../deploy.sh cartography`, then in Foundry create a scene
  using the base as Background and the walls-alpha as Foreground
  tile, drop a token, verify wall occlusion. ~5-min operator check.
- [ ] **Floor texture weight in spacecraft mode (round 2).** First
  iteration applied to hab fragment (front-loaded distinctive nouns,
  added "high contrast", "distinct"). Re-render scheduled. If still
  subtle, options: (a) repeat for other archetypes; (b) modify the
  spacecraft workflow JSON to boost floor-region guidance; (c) accept
  the limitation as an inherent trade-off of regional conditioning.
- [ ] **Multi-deck UX helper polish.** Initial helper writes deck
  variants but doesn't validate that the outer hull pixels remain
  identical across decks (modulo opening cuts). Add a sanity check
  that prints the wall-IoU between deck1 and deck<N> after writing.
- [ ] **Multi-deck UX helper** — operator must hand-paint two
  layouts that share the wall band. A helper that takes one base
  hull layout and emits N variants (engineering with rear ramp,
  bridge with windscreen, etc.) would shave ~10 minutes per
  multi-deck ship. Scoped to spacecraft architectural elements only.
- [ ] **Layered/stackable wide-scale maps** — faction control
  overlays, hex grids, jurisdiction zones, fleet movement vectors.
  All useful at the strategic scale, none implemented. Pattern
  mirrors architectural `--walls-only`: render the base, render an
  overlay separately, alpha-mask, composite. Worth a separate helper
  script (e.g. `make_overlay.py hex --grid 64x64`).
- [ ] **Operator-driven manual review of orientation + state on
  outliers.** The CLIP zero-shot orientation classifier is ~64%
  accurate on hand-grounded tests; ~36% of populated values may be
  wrong. State classifier (new this session) lifted state coverage
  25% → 78.5% but its accuracy is unverified — likely ~70-80% on
  damaged/intact/destroyed (bimodal stamps), lower on active/inactive.
  Foundry tile rotation is freeform so these fields are metadata only,
  but a quick manual-correction pass on the most unambiguous misses
  would tighten the search filter experience.

## RECENTLY CLOSED

- [x] **Architecture-only via workflow surgery (cosmetic).** Replaced
  by the stronger result: floor-only base + walls-only foreground is
  the canonical stackable design. The saved BattlemapSpacecraft.json
  furniture region nodes still neutralize correctly at runtime;
  cosmetic V2 clone deferred to future cleanup pass.
- [x] **Top-down bare battlemap quality pass (round 3).** Floor-only
  mode added to `generate_battlemap.py interior` and to
  `qa_topdown.py`. 10/10 archetypes render clean tileable floors at
  seed 42. See docs/battlemap-workflow.md for the round-by-round log.
- [x] **Multi-room floor-plan support.** Operator critique
  ("all single rooms / all square") addressed: new `make-floorplan`
  CLI + `FLOORPLAN_PRESETS` + `spacecraft --style <archetype>` flag.
  POC `hab-3room-corridor × hab` rendered at 1792×1024 with three
  rooms, central corridor, three doorways, walls + base + walls-only
  alpha all pixel-aligned.
- [x] **Floor-plan preset library expanded.** Added `tunnel-junction`,
  `chapel-nave-with-apse`, `industrial-bay`, `archive-stacks-grid`.
  Total 6 presets. All render correctly; minor cosmetic glitches
  noted in the workflow doc.
- [x] **State classifier (CLIP zero-shot).** New `classify_state.py`.
  Two-stage damage + activation with strict gating to avoid
  "everything dim is inactive" bias. Lifted state coverage from 25%
  → 78.5% across the 615-stamp vault.
- [x] **Multi-deck UX helper.** New `make_deck_variants.py`. Takes
  a base hull layout, emits N deck variants preserving outer hull
  pixel-perfect, with optional canonical openings
  (`--opening deck1=ramp:south`).

## Pre-deploy checklist

Before any future `deploy.sh cartography`:

1. `uv run pipeline_status.py` — confirm classified count and preset count.
2. `uv run validate_preset_pack.py` — must report 0 errors / 0 warnings.
3. `uv run group_audit.py` — must report 0 flagged. If flagged, clear via
   the script in `docs/battlemap-workflow.md`.
4. Spot-check on the Foundry server:
   `ssh root@192.168.5.40 ls /opt/foundry-vtt/data/Data/modules/dh-cartography/stamps/ | wc -l`
   should match local count.

## Done in this run of sessions

(Full record in git log + `docs/battlemap-workflow.md`.)

- Stamp pipeline reliability:
  - extract_stamps fill-ratio filter (rejects gutter artifacts at extraction)
  - classify_stamps three-pass strategy (default → 768+white retry →
    Florence-2-base tertiary fallback)
  - Caption preamble stripping (PromptGen's "The image is a digital
    illustration of …" → real subject name)
  - ASCII-art rejection on garbage captions
  - Category-tag enricher (furniture-chair, container-locker, etc.)
  - Manual fills for unclassifiable stamps
- 615/615 stamps classified after retroactive gutter cleanup.
- Group pipeline:
  - assign_groups Phase 2 with deterministic uuid5 group ids
  - Phase 2 merge switched from BEST cross-pair similarity (chained
    superclusters of 100+ members) to MEDIAN cross-pair similarity
    (max cluster 121 → 17 in this vault)
  - group_audit.py auto-flags low-overlap clusters lacking a shared
    concrete subject token; clear-loop snippet in
    docs/battlemap-workflow.md. Current vault: 65 clean multi-member
    groups, 0 flagged.
- Orientation classification:
  - Florence-2 docvqa empty for natural images (only good for forms)
  - SigLIP-so400m sigmoid scoring biased to verbose labels
  - **CLIP-ViT-L-14 zero-shot two-stage** (camera angle → facing
    direction) classifier in classify_orientation.py
  - 552/615 stamps populated (~89.7%) up from ~3% caption-derived
- Battlemap pipeline:
  - 14 archetypes (10 interior + 4 wide-scale)
  - Architecture-only base maps default; furniture opt-in via
    `--render-furniture chair locker console`
  - `--walls-only` and generic `--keep-only <role>` layered output
  - `mask-by-layout` for arbitrary stacking (txt2img scaffold ⊕ base)
  - `compose` for layered preview
  - `make-room`, `make-corridor` for canonical-color layout templates
  - `quantize-layout` v2 (modal-bg detection + force-snap to canonical)
  - Multi-deck shared-footprint verification (94.6% IoU exact-color)
  - Independent-render scaffold-over-base verification (pixel-perfect)
- Wide-scale archetype prompt iteration (V3 prompts):
  - district + system rendered convincingly at default seeds
  - region + planet now strong at seed 7 (V3 prompts force
    cartographic framing + curved horizon)
- Deterministic system map: make_system_map.py renders the Solenne
  system as Imperial cartography (parchment, orbital rings, planet
  discs sized to lore, MINORIS moon, asteroid belt, Aquila sigils,
  red wax seal). Repeatable per-seed.
- 5 production-quality reference battlemaps for actual Solenne
  campaign locations:
  - SOLENNE_section7_maintenance_tunnels.png (2048x768)
  - SOLENNE_block9_unit14_edric_residence.png (1024²)
  - SOLENNE_region_overview.png (1024²)
  - SOLENNE_planet_overview.png (1024²)
  - SOLENNE_system_chart.png (2048², deterministic)
- End-to-end orchestrator (`pipeline_run.py`), validator
  (`validate_preset_pack.py`), status reporter
  (`pipeline_status.py`), group audit (`group_audit.py`).
- Top-level README, ops notebook docs/battlemap-workflow.md,
  campaign-locations.md.
- 4 successful deploys to the Foundry server, latest with 615
  stamps and 5 reference battlemaps.
