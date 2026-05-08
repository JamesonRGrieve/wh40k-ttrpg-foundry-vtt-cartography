# Voidship hull silhouettes — Stage 1 LoRA

Trigger: `dh_voidship_hull`. Stage 1 of the two-LoRA voidship
pipeline. This LoRA learns canonical Imperial voidship hull
silhouettes per ship class. **It learns the exterior shape, not the
interior.** Output is an empty hull at the right proportions for the
class — a clean, drawable boundary that the layout LoRA fills in
with rooms at inference time.

## Why two LoRAs

Single-LoRA fused training (one image = hull + interior) collapses
class differentiation when reference images are involved and forces
the layout vocabulary to be ship-specific. Splitting the problem:

- **Hull LoRA (this one)** — class-conditional silhouette generator.
  Captions describe ONLY exterior (silhouette family, scale,
  ornamentation, sponson loadout, hull state). Smaller learning
  problem; reusable across all ship-needing scenes.
- **Layout LoRA (`../voidship-layouts/`)** — boundary-conditioned
  architectural composition generator, using zone grammar in the
  caption. NOT ship-specific. Reusable for hab apartments,
  manufactorum bays, chapels, district maps. Pays for itself across
  the wider battlemap surface.

See `../../docs/battlemap-workflow.md` for the architecture
rationale and inference pipeline.

## Silhouette taxonomy

Two silhouette families (carried over from `voidship-layouts/`):

- **`gothic_voidship`** — canonical Imperial gothic profile: long
  spinal hull, pointed gothic ram-prow, swept stern with engine
  block, lateral sponsons. ~3:1 to 4:1 length-to-beam aspect. Used
  for frigate, destroyer, transport-bulk, yacht, and freighter-medium.
- **`micro_ship`** — short-range utility profile: stubby boxy
  utilitarian hull, no gothic prow. Arvus Lighter, Errant Vector
  family. Used for freighter-small.

Each ship class assigns a `family` and a `modifier` (scale +
ornamentation + loadout) — see `manifest.yaml`.

## Caption format

```
dh_voidship_hull, <class_name>, <silhouette_family>, <modifier_short>, hull state: <state>, top-down orthographic, empty hull
```

No interior, no rooms, no layout descriptors. The layout LoRA
handles those at inference.

## Hard rules

- **Lateral broadside guns, NOT forward pursuit.** Imperial Navy
  ships fight broadside. Frigate/destroyer/cruiser/battleship
  primary armament runs along port and starboard flanks, firing
  outward. Forward-facing pursuit guns are an outlier (Corvus
  Blackstar etc.), NOT the canon line.
- **The hull is empty.** No interior bleed-through. The renderer
  must commit to the hull as a closed silhouette outline with hull
  treatment (plating, panel seams, rivets, heraldry along the
  spine) and BLACK / OPAQUE interior. Captions explicitly say
  "interior unspecified — solid plating from this view, NO rooms
  visible".
- **No style references.** Text-only generation. A shared style
  reference collapses class differentiation (proven 2026-05-08).

## Status

Manifest in progress. Smoke test of 3 hulls due before full corpus
run.

## Files (planned)

```
voidship-hulls/
├── README.md             ← this file
├── manifest.yaml         ← class taxonomy, hull-state matrix, captions
├── _smoke_test/          ← incremental validation samples
└── hull-<class>/         ← per-class hull PNG + .txt caption pairs
    ├── hull-freighter-small/
    ├── hull-freighter-medium/
    ├── hull-frigate-escort/
    ├── hull-destroyer-light/
    ├── hull-transport-bulk/
    └── hull-yacht-roguetrader/
```
