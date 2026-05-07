# Cartography TODO

Open work, in priority order. Items removed when done. Last refreshed
2026-05-07.

## Open

- [ ] **HIGH PRIORITY: Stamp variant generator (gap-filling pipeline).**
  Today the vault has only what Gemini happened to paint on the source
  sheets. There is no workflow that takes a stamp ("desk, top-down,
  intact") and generates matching variants — no rotation generator,
  no damage/activation state generator. The existing pipeline is
  purely classify-what-you-got: Florence-2 captions + CLIP-ViT-L-14
  zero-shot for orientation/state. Result: rotational and condition
  coverage is whatever the sheets happened to provide, with no way
  to fill obvious holes.

  What we need:
  - **Rotational variants.** Given a top-down or N-facing stamp,
    produce S/E/W variants. Two paths:
    1. **Geometric** for top-down stamps: rotate the PNG 90/180/270°.
       Fast, deterministic, but the result reads as "rotated", not
       "naturally drawn from the new angle" — shadows and asymmetric
       details look wrong.
    2. **Generative** for non-trivial cases: img2img with controlnet
       depth/normal hints and a prompt-rotated description. ComfyUI
       has the building blocks (Flux, IPAdapter, CLIP-ViT-H embed
       — all installed for the existing classifier). Needs a new
       workflow file (`StampVariantsRotation.json`) and a driver.
  - **Condition state variants.** Given an "intact" stamp, generate
    "damaged" and "destroyed" matched-style copies. Same img2img +
    IPAdapter approach: IPAdapter encodes the source style, prompt
    drives the damage pass. "active" / "inactive" can use a similar
    pattern with light-emission cues.
  - **LoRA training.** Reserve for when prompt+IPAdapter caps out.
    Operator has training material on offer; budget ~6-12 hours
    one-time to capture the Solenne campaign style as a LoRA. A
    style-LoRA would unlock both gap-filling AND new archetypes
    (vehicles, weapons, full character poses) without sourcing
    new Gemini sheets.

  Acceptance for first cut: take 5 hand-picked source stamps with
  obvious gaps in their group (e.g. a desk that only has a top-down
  variant), generate the missing rotation variants, classify them
  through the existing pipeline, and confirm group_id assigns them
  to the same group as the source. If that round-trip works, scale.



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
