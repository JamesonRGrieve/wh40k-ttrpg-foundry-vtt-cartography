# Presentation v2 — REJECTED 2026-05-08

Built 2026-05-07. Operator-reviewed and rejected on 2026-05-08
across most goals:

- Portraits read as low-fidelity thumbnails vs. deployed
  Edric Family / Pell Osric references; aquilas not true to
  canonical two-headed eagle shape.
- Every battlemap defaulted to a square canvas; layouts must follow
  actual room geometry.
- Ship decks read as MS-Paint compared to deployed interior
  battlemaps — flat walls, weak floor, schematic shapes.
- District overheads read as freestanding building stamps, not as
  hive-city density.
- Chapel apse aquila (the closest win) had wings arched-up like a
  generic angel statue, not the canonical aquila shape.
- Stamp matrix demo wasted storage on pure 90/180/270° rotations
  (Foundry rotates tiles freely at runtime).

Full post-mortem in `docs/battlemap-workflow.md` under "2026-05-08
— Second presentation rejection". The "Project end goal" and "Hard
rules" sections in `cartography/CLAUDE.md` have been updated.

**Operator-instructed tooling decision:** use Gemini Imagen 4
("nano-banana") for iconography-critical surfaces. Local Chroma-
Flux has a hard ceiling on canonical 40K iconography that no
parameter sweep on the existing scripts will lift. See
`cartography/CLAUDE.md` "Tooling decisions" section.

This bundle is preserved as a record of what got rejected and why.
The artifacts below should NOT be promoted to deployed paths
(`Characters/portraits/`, `battlemaps/SOLENNE_*.png`, etc.) — they
fall short of the bar. Future sessions: read the post-mortem and
the updated rules before producing a v3 bundle.

## Folder index

| Folder | Goal | Mechanical summary |
| --- | --- | --- |
| `01_portraits/` | 8 (portraits + 1:1 tokens) | 7 NPC busts via two-pass txt2img → img2img integration (denoise=0.45). Each bust + token pair. |
| `02_battlemaps/` | 1 (interior battlemaps) | 4 new SOLENNE_*.png interiors at 1024² (sump / chapel / medicae / garrison). |
| `03_painterly_ships/` | 3 (ships) | 4 ship-deck candidates after `painterly_pass.py` img2img at denoise=0.75. `_before_*.png` are the spacecraft-mode source renders. |
| `04_districts/` | 4 (city / district maps) | 2 district-scale overhead candidates (seeds 7, 99). |
| `05_iconography_scenes/` | 9 (integrated iconography) | Chapel scene at integration denoise 0.80; Vigil Ledger hull at 0.65 and 0.80. `_reference_deployed_vigil_ledger.png` is the canonical iconography target. |
| `06_stamp_matrix/` | 7 (stamp matrix variations) | Cogitator Console group: 4 orientations × 2 states demo. North-active is the source, others are synthesized variants. |
| `07_reference/` | — | Deployed Solenne maps and portraits used as the comparison baseline. |

## Goal-by-goal status

| # | Goal | New artifacts here | Operator must judge |
| - | ---- | ------------------ | ------------------- |
| 1 | Battlemaps (interior tactical) | 4 new SOLENNE_*.png in `02_battlemaps/` | Style match against `07_reference/SOLENNE_section7_maintenance_tunnels.png` |
| 2 | Battlemap overlays (walls-alpha) | None new this pass — existing `dh-cartography/battlemaps/hab_3room_walls_alpha.png` already shipped, awaits Foundry verification | Whether existing pair is the canonical pattern |
| 3 | Ships (multi-deck, painterly) | 4 painterly variants in `03_painterly_ships/` (compare `_before_*.png` to the painterly `*_d075.png`) | Whether 0.75 hits painterly bar or another sweep needed |
| 4 | City / district maps | 2 in `04_districts/` | Pick canonical district base (or reject all) |
| 5 | Planetary | None new — operator may use deployed `07_reference/SOLENNE_planet_overview.png` | Whether deployed is sufficient |
| 6 | Star system | None new — operator may use deployed `07_reference/SOLENNE_system_chart.png` | Whether deployed is sufficient |
| 7 | Stamps (matrix variations) | 5 new variants in `06_stamp_matrix/` for one group | Whether the gap-fill pattern is correct |
| 8 | Portraits + 1:1 tokens | 7 NPC bust+token pairs in `01_portraits/` | Style match against `07_reference/_deployed_inquisitor.png` and `_deployed_corvin_edric.png` |
| 9 | Scenes with integrated iconography | 3 in `05_iconography_scenes/` | Chapel apse aquila at d=0.80 — does it read as integrated stone/brass? Vigil Ledger comparison vs. `_reference_deployed_vigil_ledger.png` |

## Known gaps and untried levers

1. **Symbology on flat metal surfaces (ship hulls).** Denoise 0.80
   repaints the surrounding scene cleanly but erases the symbol
   silhouette (Vigil Ledger d=0.80, IoU 0.008). Untried levers:
   localized inpainting with a tight mask (TODO approach 2),
   Flux-specific ControlNet (approach 3), reference-image
   conditioning via IPAdapter using the deployed Vigil Ledger
   itself as the reference.
2. **Painterly ship-deck pass.** Denoise 0.75 introduces surface
   detail but may not read as full Solenne-painterly.
   Untested: 0.85, prompt iteration anchored on
   `SOLENNE_section7_maintenance_tunnels.png` via IPAdapter.
3. **Stamp matrix gap-fill at scale.** The supplemental sidecar
   path is manual; `make_sidecars.py` `NAME_RE` only matches
   `_NN.png`. To fill the 502 grouped stamps' missing variants
   automatically, the regex needs to accept `_NN_<suffix>.png`.
4. **Walls-alpha overlay for the 4 new SOLENNE_*.png interiors.**
   They were rendered as single-layer interiors. Stackable
   pairs (floor-only base + walls-only foreground) would need a
   re-render through the spacecraft + `--keep-only` path or via
   the multi-room floor-plan workflow.
5. **Aesthetic judgment loop.** I cannot self-declare any of these
   met. Goals 1, 3, 8, 9 require operator approval before being
   logged as closed in `TODO.md`.

## Provenance

Every PNG with a corresponding sidecar (in the source tree, not
copied here) has the exact prompt / seed / denoise / IoU recorded.
The sidecars live with the source artifacts:
- portraits: `Characters/portraits/<name>_bust.json`
- scenes: `cartography/scenes/<name>.json`
- battlemaps: `cartography/battlemaps/` (preset metadata via
  `dh-cartography/mass-edit-presets.json`)
