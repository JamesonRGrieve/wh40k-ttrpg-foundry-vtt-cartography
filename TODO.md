# Cartography TODO

Open work, in priority order. Items removed when done. Last refreshed
2026-05-08.

## 2026-05-08 review — rejected by operator (second presentation)

The operator reviewed `_presentation_v2/` and rejected on specific
axes: portraits low-fidelity + aquilas not true-to-shape, all maps
defaulted to a square canvas, ship decks read as MS-Paint vs.
deployed battlemaps, district overheads do not read as a hive city,
chapel apse aquila has arched-up wings instead of canonical shape,
stamp matrix wasted storage on pure rotations. Full post-mortem in
`docs/battlemap-workflow.md` under "2026-05-08 — Second presentation
rejection".

The rules in `cartography/CLAUDE.md` "Project end goal" and "Hard
rules" have been updated. Pre-existing 2026-05-07 rules remain in
force; this is additional, not replacement.

Operator-instructed tooling decision: **use Gemini Imagen 4
("nano-banana") for iconography-critical surfaces.** Local Chroma-
Flux has a hard ceiling on canonical 40K iconography because the
model doesn't have aquila/rosette/cog as concept tokens. See
`cartography/CLAUDE.md` "Tooling decisions" section.

## Open (HIGH PRIORITY — 2026-05-08 review-rejected)

- [ ] **Stand up a Gemini Imagen 4 generation path** for iconography-
  critical portraits and scenes. Decision: replace the local
  silhouette-paste-then-img2img pattern with native Imagen renders
  for those surfaces. Keep local Chroma-Flux for surfaces where it
  works (battlemap interiors, wide-scale archetypes, multi-deck
  geometry). Open question for the operator: API endpoint, auth,
  budget envelope.
- [ ] **Train a 40K iconography LoRA** (medium-term, portable
  artifact). Curated training set of isolated canonical-shape
  references on neutral backgrounds: Imperial Aquila, Inquisitorial
  Rosette, Mechanicus opus cog, Astra Militarum winged skull,
  Adepta Sororitas fleur-de-lys, Adeptus Custodes lightning bolt,
  Adeptus Ministorum sigil, Chapter heraldry, Eldar runes, Ork
  glyphs, Tyranid hive markings, Necron dynastic glyphs, Tau caste
  sigils, Chaos star variants. Captions describe SHAPE not style.
  ~50-150 image-caption pairs, one-day fine-tune on the 3090.
  Output: `wh40k_iconography.safetensors` reusable across this
  campaign, all 7 wh40k-rpg game systems, and any future 40K
  project. Do NOT fold campaign-specific style into this LoRA —
  iconography is a 40K constant; style is per-campaign and stacks
  separately at inference time.
- [ ] **Re-architect ships as battlemaps with hull-shaped layouts.**
  Per operator direction: the spacecraft workflow's region-color
  prompt-budget split is the structural cause of the MS-Paint deck
  output. Replace with `interior --style ship-{bridge,engineering,
  barracks,cargo,...}` rendered at the hull's bounding box, then
  alpha-masked to the hull silhouette via the existing mask-by-
  layout / `--keep-only` infrastructure. One hull silhouette per
  ship class shared across all decks → pixel-aligned multi-deck
  stacking preserved. Deprecate the spacecraft mode and
  `painterly_pass.py` as wrappers over an inferior path.
- [ ] **Non-square canvas defaults across battlemap renders.** The
  4 new SOLENNE_*.png interiors and the 2 district overheads in
  `_presentation_v2/` were all 1024×1024 by default. Real campaign
  locations are not square. Add a layout-aware canvas-shape pass
  upstream of the render call: per-archetype default aspect ratios
  (hab apartment 3:2, chapel 4:3, sump 3:2, medicae 4:3, garrison
  16:9, district 1:1 OK if it really is a top-down quadrant), or
  drive the canvas shape from a `--width` × `--height` operator
  argument.
- [ ] **Hive-city density for the district archetype.** The district
  prompt produces freestanding building stamps on an open canvas.
  Hive cities are stacked vertical mega-blocks, kilometres deep,
  sharing walls and rooftops. Either rewrite the district prompt
  to anchor on Necromunda / Forge World hive cross-sections, or
  switch to Gemini for district renders, or move on entirely until
  reference images are operator-supplied.
- [ ] **Painterly fidelity gap on ship decks.** `painterly_pass.py`
  at d=0.75 introduces some surface detail but the source's
  flatness dominates. Untested levers (in priority order): IPAdapter
  conditioning using `SOLENNE_section7_maintenance_tunnels.png` as
  reference; switch to Gemini for the surface pass; LoRA on
  deployed Solenne battlemap references; d=0.85 + prompt anchor
  on a specific deployed map.
- [ ] **Portrait fidelity gap.** New 7 NPC bust portraits in
  `_presentation_v2/01_portraits/` read as low-resolution
  thumbnails next to the deployed Edric Family / Pell Osric refs.
  Untested levers: drop the anti-symbol negative on the txt2img
  pass; bump the latent-resolution to 1024×1280 minimum; IPAdapter
  conditioning using a deployed reference; switch to Gemini for
  iconography-bearing portraits.
- [ ] **Aquila canonical-shape requirement.** Even when the local
  pipeline integrates the symbol painterly-ly (chapel apse d=0.80),
  the wings come back arched-up like a generic angel statue, not
  the canonical two-headed eagle. Per the new hard rule in
  `cartography/CLAUDE.md`, this is a regression regardless of
  surface fidelity. Tied to the Gemini-tooling decision above.

## Open (carried from 2026-05-07 review — still in force)

The 2026-05-07 review rejected `_presentation/` for symbology,
deck aesthetic, hab floor texture, and hex-on-system-chart demo.
Full post-mortem in `docs/battlemap-workflow.md` under "2026-05-07
— Review post-mortem". The reinforcement rules in
`cartography/CLAUDE.md` "Quality acceptance rules" are mandatory
reading.

## Open (carried — review-rejected, must redo)

- [ ] **Symbology integration — pass-2 denoise was wrong.** Chapel
  Aquila and inquisitor rosette are still flat black SVG with noise
  around them. denoise=0.45 preserves silhouettes; it does not
  repaint them. Tried approaches, ranked by confidence:
  1. Raise pass-2 denoise to 0.75–0.85 with a strong material
     prompt. Fastest A/B; tests whether it's just a parameter.
  2. Localized inpainting with a tight mask around the symbol so
     only that region gets aggressive denoise; rest of the scene
     preserved.
  3. Proper Flux-specific ControlNet (`LoadFluxControlNet` +
     `ApplyAdvancedFluxControlNet`). Chroma is a Flux derivative;
     the node may work despite the model list. I dismissed this
     too early last session.
  4. LoRA trained on integrated-iconography references (last
     resort; needs operator-supplied reference set).
  Before retrying: operator must specify what success looks like
  (reference image, deployed-map example, or written description).
- [ ] **Deck and hab aesthetic — switch off spacecraft regional
  conditioning for the look pass.** The spacecraft workflow splits
  guidance budget across 5 regions, structurally capping texture
  punch. Plan:
  1. Use spacecraft workflow ONLY for layout + wall-mask geometry.
  2. Run an img2img pass over the spacecraft render through the
     interior txt2img path with the painterly Solenne-campaign
     style prompt at moderate-to-high denoise.
  3. Compare side-by-side against
     `SOLENNE_section7_maintenance_tunnels.png` and
     `SOLENNE_block9_unit14_edric_residence.png` before shipping.
  Do not iterate on the spacecraft workflow's prompt strings any
  further; that lever is exhausted.
- [ ] **Hex overlay — drop the system-chart demo.** The hex helper
  is fine as a tool; remove the
  `_presentation/05_wide_scale_overlays/solenne_system_with_hex_composed.png`
  demo and ask the operator what scale of overlay (district,
  region, sector) is actually needed for play.
- [ ] **Re-survey `_presentation/` against the new acceptance
  rules.** Before assembling a presentation bundle next session,
  open at least one deployed `SOLENNE_*.png` map per category
  (interior, ship, portrait) and discard any candidate that is
  visibly weaker. Document the comparison in the commit message.

## Open (lower priority)

- [ ] **Floor texture punch on hab archetype** — bland on review.
  Same root cause as deck aesthetic; fix is the workflow switch
  above, not more prompt iteration on the spacecraft path.
- [ ] **Chapel `--floor-only` perimeter trim** — RE-OPENED. Was
  self-closed as "accepted artifact"; operator rejected that
  framing. Untried approaches: localized inpainting on the trim
  region; LoRA on borderless chapel references; switch base model
  for chapel renders. Operator decides whether to escalate.
- [ ] **Foundry V14 stackable scene end-to-end test.** Real
  multi-room battlemap pair now staged at
  `dh-cartography/battlemaps/hab_3room_base.png` +
  `hab_3room_walls_alpha.png` (1792×1024, hab archetype, seed 42).
  Layout source at `hab_3room_layout.png`. Pending: deploy via
  `../../deploy.sh cartography`, then in Foundry create a scene
  using the base as Background and the walls-alpha as Foreground
  tile, drop a token, verify wall occlusion. ~5-min operator check.
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

- [~] **Symbology rebuild (img2img integration).** REOPENED on
  operator review — denoise=0.45 in pass 2 preserves the SVG
  silhouette; the "integrated brass relief" claim was wrong. See
  the HIGH PRIORITY entry above for the next-step plan. Pipeline
  plumbing (CLI flags, MATERIAL_HINTS, two-pass workflow) is
  retained; only the integration parameters need replacing.
- [x] **Programmatic ship deck layout presets.** Four ship-* presets
  (bridge / engineering / barracks / cargo) sharing identical hull
  via `_ship_hull_rect()`. Verified pixel-aligned via the new
  `verify_deck_stack.py`.
- [~] **Render multi-deck via spacecraft workflow.** REOPENED on
  operator review — renders read as MS-Paint, not Solenne-campaign
  oil-paint aesthetic. Layouts (`<deck>_layout.png`) and pixel
  alignment are correct; the rendered look is the failure. See
  HIGH PRIORITY workflow-switch plan above.
- [x] **Multi-deck IoU sanity check.** New `verify_deck_stack.py`
  proves the four ship-deck layouts share canvas + hull bbox
  pixel-perfect (interior walls intentionally differ).
- [x] **make_deck_variants.py IoU sanity check.** Superseded by the
  new programmatic ship-* presets + `verify_deck_stack.py` (which
  works on arbitrary layout PNGs). `make_deck_variants.py` docstring
  now points to the recommended workflow.
- [~] **Chapel `--floor-only` thin perimeter trim.** REOPENED — see
  HIGH/MEDIUM open items. Self-closed as "accepted artifact";
  operator rejected that framing.
- [~] **Floor texture weight in spacecraft mode.** REOPENED —
  workflow switch (img2img painterly pass over spacecraft layout
  output) is the untried lever. See HIGH PRIORITY plan above.
- [x] **Wide-scale overlay helper (tool only).** `make_overlay.py`
  hex/zones/fleet/compass subcommands work mechanically. The
  system-chart hex demo is being removed; tool retained pending
  operator direction on real use cases.
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
