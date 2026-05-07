# Cartography TODO

Open work, in priority order. Items removed when done. Last refreshed
2026-05-06.

## Priority deploy gaps — should fix in next sweep

- [ ] **17 stamps remain genuinely caption-resistant** even with the
  tertiary Florence-2-base fallback. They have null name and null
  description, ship under raw filename. Build a manual-annotation
  TUI that walks each one (`pipeline_status.py --json | jq` to
  enumerate), shows the PNG, prompts for name + description + tags
  + state. ~10 minutes of operator time per pass.
- [ ] **Orientation field is populated on only ~3% of stamps.**
  Florence-2 doesn't reliably emit directional words even on the
  base model. Decision required: (a) build the manual-annotation
  TUI to populate orientation per stamp, OR (b) DROP the
  per-stamp orientation field entirely — Foundry tile rotation is
  freeform; orientation only matters when art-time variants
  exist. Path (b) is what most VTT modules do; recommend it.
- [ ] **Phase 2 grouping over-merges at scale.** Current
  `MERGE_THRESHOLD = 0.92` produces large false-positive
  superclusters (one was 121 members) when many stamps share
  art-style background. The `group_audit.py` flag-and-clear loop
  works as a remediation but should not be needed every run.
  Lower the threshold to 0.96 or add a max-cluster-size cap and
  re-run. Verify the trimming doesn't break the known true
  state-variant clusters (cogitator console, dossier, etc.).

## Battlemap workflow gaps

- [ ] **Architecture-only is enforced via prompt neutralization,
  not workflow surgery.** Saved `BattlemapSpacecraft.json` on the
  ComfyUI server still has chair/locker/console region nodes; the
  driver overrides their prompts to "empty deck plating" by
  default. Opt-in via `--render-furniture`. Cleaner long-term:
  clone server-side as `BattlemapSpacecraftV2_Architecture.json`
  with the furniture region nodes removed entirely. Skipping has
  no functional impact today but will confuse a future operator
  who reads the workflow JSON.
- [ ] **Wide-scale archetype quality varies.**
  - `district` — convincing top-down hive city (seed 42) ✓
  - `system` — convincing imperial cartographic chart (seed 42) ✓
  - `region` — passable at seed 7; reads as wastes-with-clusters
    but lacks clear hive identification at most seeds. Iterate
    prompt; the prompt should require explicit "imperial hive
    fortress dot" markers.
  - `planet` — strong at seed 7 (curved-globe with continental
    sprawl); weak at seed 42. Add seed iteration in the docs or
    require the operator to try multiple seeds.
- [ ] **Multi-deck UX.** Operator must hand-paint two layouts that
  share the wall band. Helper that takes one base layout PNG and
  emits N variants with the same hull but different interior
  region masks would be useful (e.g. `make-deck-variants <base>
  --decks 3` emits engineering / quarters / bridge layouts).
- [ ] **Deterministic system maps.** Chroma-Flux randomizes
  orbital geometry per seed; for a consistent Solenne system
  chart (always 4 planets at the right relative positions), a
  programmatic PIL generator with orbital-ring drawing + planet
  circles + Aquila labeled icons would be more reliable than
  diffusion.
- [ ] **Layered/stackable wide-scale maps**: faction control
  overlays, hex grids, jurisdiction zones — all useful at the
  strategic scale, none implemented. Pattern mirrors architectural
  walls-only: render the base, render the overlay, mask, composite.
- [ ] **Foundry V14 stackable scene end-to-end test**: walls-only
  alpha PNG produces correctly. Not yet verified inside Foundry
  with a live scene + token movement above/below the foreground.
  Should be a 5-min spot-check post-deploy.

## Pre-deploy checklist

Before any future `deploy.sh cartography`:

1. `uv run pipeline_status.py` — confirm classified count and
   preset count.
2. `uv run validate_preset_pack.py` — must report 0 errors / 0
   warnings.
3. `uv run group_audit.py` — must report 0 flagged. If flagged,
   clear via the script in `docs/battlemap-workflow.md`.
4. Spot-check at least one stamp on the Foundry server:
   `ssh root@192.168.5.40 ls /opt/foundry-vtt/data/Data/modules/dh-cartography/stamps/ | wc -l`
   should match local count (632 currently).

## Done in current sessions

(See git log + `docs/battlemap-workflow.md` for full record.)

- Stamp pipeline reliability: extract fill-ratio filter, classify
  three-pass strategy (default → 768+white retry → Florence-2-base
  tertiary fallback), name preamble stripping, ASCII-art rejection,
  category-tag enricher, manual fills for unclassifiable stamps.
- 615 / 632 (97.3%) stamps have descriptions; 400 / 632 (63.3%) have
  category tags.
- assign_groups Phase 2 with deterministic uuid5 group ids;
  group_audit.py auto-flags low-overlap clusters with no shared
  subject; current vault has 40 clean multi-member groups, 0 flagged.
- Battlemap driver with 14 archetypes (10 interior + 4 wide-scale),
  layout-as-mask layered output, programmatic make-room +
  make-corridor + quantize-layout helpers, server pull/clone for
  workflow versioning, mask-by-layout for arbitrary stacking,
  compose for layered preview.
- Architecture-only base maps by default; furniture opt-in via flag.
- Multi-deck shared-footprint verification (94.6% IoU exact-color).
- Layered scaffold-over-base verification (pixel-perfect alignment).
- Two production-quality battlemaps verified and committed:
  `SOLENNE_section7_maintenance_tunnels.png` (2048x768),
  `SOLENNE_block9_unit14_edric_residence.png` (1024x1024).
- End-to-end orchestrator (`pipeline_run.py`), validator
  (`validate_preset_pack.py`), status reporter
  (`pipeline_status.py`), group audit (`group_audit.py`).
- Top-level `README.md`, ops notebook
  `docs/battlemap-workflow.md`, location recipe
  `docs/campaign-locations.md`.
- Two successful deploys to the Foundry server.
