# Cartography TODO

Open work, in priority order. Items removed when done. Last refreshed
2026-05-06.

## Open

- [ ] **Architecture-only via workflow surgery (cosmetic).** The
  saved `BattlemapSpacecraft.json` on the ComfyUI server still has
  chair/locker/console region nodes. The driver overrides their
  prompts to "empty deck plating" by default, which works
  correctly. Cleaner long-term: clone server-side as
  `BattlemapSpacecraftV2_Architecture.json` with the furniture
  region nodes (and their ImageColorToMask + ConditioningSetMask +
  ConditioningCombine entries) removed. No functional impact;
  cosmetic / future-proofing only.
- [ ] **Multi-deck UX helper** — operator must hand-paint two
  layouts that share the wall band. A helper that takes one base
  hull layout and emits N variants (engineering with rear ramp,
  bridge with windscreen, etc.) would shave ~10 minutes per
  multi-deck ship. Scoped to the spacecraft architectural elements
  only — hand-painting is fine for room-detail layouts.
- [ ] **Layered/stackable wide-scale maps** — faction control
  overlays, hex grids, jurisdiction zones, fleet movement vectors.
  All useful at the strategic scale, none implemented. Pattern
  mirrors architectural `--walls-only`: render the base, render an
  overlay separately, alpha-mask, composite. Worth a separate
  helper script (e.g. `make_overlay.py hex --grid 64x64`).
- [ ] **Foundry V14 stackable scene end-to-end test** — the
  driver's `--walls-only` produces correctly-aligned alpha PNGs.
  Not yet verified inside Foundry with a live scene + token
  movement above/below the foreground. ~5-min spot-check post-
  deploy is sufficient; needs an operator at Foundry's UI.
- [ ] **Operator-driven manual review of orientation + state on
  outliers.** The CLIP zero-shot orientation classifier is ~64%
  accurate on hand-grounded tests; ~36% of populated values may be
  wrong. Foundry tile rotation is freeform so the field is
  metadata only, but a quick manual-correction pass on the most
  unambiguous misses (e.g. desks/lockers labeled top-down where
  they're clearly isometric) would tighten the search filter
  experience.

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
