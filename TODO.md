# Cartography TODO

Open work, in priority order. Items are removed from this file as they
are completed (not merely struck through). Last refreshed 2026-05-05.

## Priority — block the next deploy

- [ ] **Complete the long classify pass.** Of 632 stamps, only ~50
  have descriptions. Florence-2 dual-task at fp16 runs ~1 stamp/min
  on the 3090, so the remaining ~580 take ~10 hours wall-clock.
  Run as `nohup env PYTHONUNBUFFERED=1 uv run --quiet
  classify_stamps.py > /tmp/full_classify.log 2>&1 &`. No
  concurrent GPU jobs.
- [ ] **Re-run `assign_groups.py` after classify completes.** The
  Phase 2 image-embedding clustering only runs over stamps that
  have descriptions; new groups will form once the captions land.
- [ ] **Re-run the group sanity audit.** This session inspected the
  9 multi-member groups in the current vault: 5 confirmed true
  variants (chair pair, dossier pair, locker pair, paperwork pile,
  cogitator console active/inactive/destroyed), 1 same-family
  cluster (pipe fittings), 3 false-positive merges cleared.
  Findings + actions in `docs/battlemap-workflow.md`. Repeat after
  the long classify, with `tools/group_audit.py` if built.
- [ ] **Render production-quality battlemaps for two reference
  Solenne locations** (e.g. Block 9 Unit 14 + Section 7 Maintenance
  Tunnels). Pick seeds, dimensions, archetype per
  `docs/campaign-locations.md`. Visual approval required before
  declaring deploy-ready.

## Stamp metadata gaps

- [ ] **Orientation populated on only ~16% of classified stamps.**
  Florence-2-PromptGen rarely emits directional words. Two paths:
  (a) build a manual-annotation TUI that displays each stamp PNG
  and prompts for orientation; (b) drop the per-stamp orientation
  field — Foundry tile rotation is freeform, the field only
  matters when N/S/E/W variants are pre-committed at art-creation
  time. Path (b) is what most VTT modules do.
- [ ] **Florence-2 fully fails on certain art styles** — verified
  on 4lrua5 stamps 08/09 (battered office chairs). Manually
  labeled. Expect more hits when the long classify reaches new
  sheets; build a `pipeline_status` flag for "stamps with
  group_id but no description".
- [ ] **Group-merge threshold 0.92 is too generous** for stamps
  sharing common art-style background. Either lower
  `MERGE_THRESHOLD` in `assign_groups.py` or add a sanity check
  that flags groups whose member captions share <50% content
  tokens.

## Battlemap workflow gaps

- [ ] **Architecture-only is enforced via prompt neutralization,
  not workflow surgery.** The saved `BattlemapSpacecraft.json` on
  the ComfyUI server still has `chair`/`locker`/`console` region
  nodes. The driver overrides their prompts to "empty deck
  plating" by default; opt-in via `--render-furniture chair locker
  console`. Cleaner long-term: clone server-side as
  `BattlemapSpacecraftV2_Architecture.json` with the furniture
  region nodes removed.
- [ ] **Wide-scale archetype quality varies.**
  - `district` — convincing top-down hive city ✓
  - `system` — convincing imperial cartographic chart ✓
  - `region` — passable; reads as wastes-with-clusters but lacks
    clear hive identification. Iterate prompt + seed.
  - `planet` — passable; reads as continental landmass without
    clear orbital perspective. Iterate prompt + seed.
- [ ] **Multi-deck UX**: operator must hand-paint two layouts that
  share the wall band. Helper that takes one base layout PNG and
  emits N variants with the same hull but different interior
  region masks would be useful.
- [ ] **Deterministic system maps.** Chroma-Flux randomizes
  orbital geometry per seed; for a consistent Solenne system chart
  (always 4 planets at the right relative positions), a
  programmatic PIL-based generator would be more reliable than
  diffusion.
- [ ] **Layered/stackable wide-scale maps**: faction control
  overlays, hex grids, jurisdiction zones — all useful at the
  strategic scale, none implemented. Pattern would mirror
  architectural walls-only: render the base, render an overlay
  separately, mask, composite.
- [ ] **Foundry V14 stackable scene verification**: walls-only
  alpha PNG drops in as foreground image — verified the layer
  produces correctly. Not yet verified end-to-end inside Foundry
  with a live scene + token movement above/below the foreground.

## Pre-deploy checklist

Before running `deploy.sh cartography`:

1. `uv run pipeline_status.py` — confirm stamp counts, classify
   coverage, preset count, staged count.
2. `uv run validate_preset_pack.py` — must report 0 errors / 0
   warnings.
3. SSH-spot-check one stamp on the Foundry server post-deploy:
   `ls /opt/foundry-vtt/data/Data/modules/dh-cartography/stamps/`
   should match the local count.

## Done in current sessions

(Trimmed; see git log + `docs/battlemap-workflow.md` for full record.)

- Stamp pipeline reliability (extract fill-ratio filter, classify
  two-pass retry, name preamble stripping, ASCII-art rejection,
  category-tag enricher, manual fills for unclassifiable stamps).
- Battlemap driver with 14 archetypes (10 interior + 4 wide-scale),
  layout-as-mask layered output, programmatic make-room /
  make-corridor / quantize-layout helpers, server pull/clone for
  workflow versioning.
- Architecture-only base maps by default; furniture opt-in via flag.
- End-to-end orchestrator (`pipeline_run.py`), validator
  (`validate_preset_pack.py`), status reporter
  (`pipeline_status.py`).
- Multi-deck shared-footprint verification (94.6% IoU exact-color);
  layered scaffold-over-base verification (pixel-perfect alignment).
- Visual group-membership audit; 6 stamps' state values manually
  filled where Florence-2 captions missed them.
- Top-level `README.md`, ops notebook
  `docs/battlemap-workflow.md`, location recipe
  `docs/campaign-locations.md`.
