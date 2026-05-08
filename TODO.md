# Cartography TODO

Open work, in priority order. Items removed when done. Last refreshed
2026-05-07.

## Retrospective — what landed in the 2026-05-07 sessions

The three TOP/HIGH PRIORITY blocks that previously lived here are
done; full retrospective in `docs/battlemap-workflow.md`. Brief
summary:

- **Symbology rebuild**: ControlNet path failed (Flux/Chroma node
  incompatibility). Pivoted to two-pass img2img integration. Chapel
  Aquila now reads as brass relief; inquisitor rosette as armor
  inlay. CLI: `--symbol-style integrated` (default for narrative
  scenes/portraits) | `--symbol-style flat` (legacy paste-on-top
  for diagrammatic / sidebar uses). Material hints declared via
  `MATERIAL_HINTS` (8 canonical phrases).
- **Multi-deck rebuild**: 4 programmatic ship-deck presets
  (`ship-bridge`, `ship-engineering`, `ship-barracks`,
  `ship-cargo`) sharing identical hull. All four rendered through
  the spacecraft workflow; shipped in `_deliverables/08_multi_deck/`
  as `<deck>_layout.png` + `<deck>_render.png` pairs. Pixel-perfect
  alignment proven by `verify_deck_stack.py`.
- **Asset generation pipelines**: stamps (rotation + condition),
  character portraits (8 class profiles + 1:1 token crop), scene
  pictures (anchor + material hints) — all wired end-to-end with
  the integrated symbol path.
- **Wide-scale overlays**: `make_overlay.py` with hex / zones /
  fleet / compass subcommands.

## Open

- [ ] **Chapel `--floor-only` thin perimeter trim** — accepted as
  known minor cosmetic. Three rounds of prompt iteration could not
  fully eliminate the trim because the chapel-iconography prior is
  too strong in Flux/Chroma; "no border, no trim" wording in the
  positive prompt actively makes it worse (Flux latches onto the
  forbidden nouns). The negative addendum already contains
  `border`, `trim`, `frame`, `decorative border`. The current
  round-4 result (centered Aquila medallion + thin trim line) is
  the best stable configuration. A LoRA trained on borderless
  chapel reference art would likely fix it; out of scope for now.
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

- [x] **Symbology rebuild (img2img integration).** ControlNet attempt
  failed (Flux/Chroma compatibility); pivoted to two-pass
  txt2img → composite-silhouette → img2img-repaint. Chapel Aquila
  reads as integrated brass relief; inquisitor rosette as armor inlay.
  See docs/battlemap-workflow.md for the round-by-round log.
- [x] **Programmatic ship deck layout presets.** Four ship-* presets
  (bridge / engineering / barracks / cargo) sharing identical hull
  via `_ship_hull_rect()`. Verified pixel-aligned via the new
  `verify_deck_stack.py`.
- [x] **Render multi-deck via spacecraft workflow.** All four ship
  decks rendered with deck-specific INTERIOR_STYLE_FLOOR_TEXTURES;
  `_deliverables/08_multi_deck/` rebuilt with
  `<deck>_layout.png` + `<deck>_render.png` pairs.
- [x] **Multi-deck IoU sanity check.** New `verify_deck_stack.py`
  proves the four ship-deck layouts share canvas + hull bbox
  pixel-perfect (interior walls intentionally differ).
- [x] **make_deck_variants.py IoU sanity check.** Superseded by the
  new programmatic ship-* presets + `verify_deck_stack.py` (which
  works on arbitrary layout PNGs). `make_deck_variants.py` docstring
  now points to the recommended workflow.
- [x] **Wide-scale overlay helper.** New `make_overlay.py` with four
  subcommands: hex (transparent grid overlay), zones (faction /
  jurisdiction polygons from a YAML spec), fleet (movement arrows
  from a YAML spec), compass (cardinal-rose anchor). Verified
  composite over `SOLENNE_system_chart.png`.
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
