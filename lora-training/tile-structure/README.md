# Tile-structure corpus — Stage 1 (structure pieces)

Walls, corners, doors, endcaps for the **modular room pipeline**.
This is a **Stage-1 sub-corpus** — the structure half of the
tileable-tile vocabulary. The floor half is `../seamless-tiles/`.
Same stage, same `dh_tile` umbrella trigger, two dirs.

## The three-stage pipeline

| Stage | What | Where |
|---|---|---|
| **1 — tile generator** | new *tileable tiles* for hand-building: floors **and** wall/corner/door structure | `seamless-tiles/` (floors) + **`tile-structure/`** (this dir) |
| **2 — room builder** | place & connect Stage-1 tiles into rooms; link rooms (corridors, doorways) | `voidship-layouts/` (`dh_layout`) |
| **3 — stamp placer** | drop furniture/props onto built rooms | `stamps/` (`dh_stamp`) |

A wall/corner/door is **Stage-1 tile vocabulary**, not a Stage-3
stamp. Pieces mis-binned into `stamps/train/fixtures/` before the
3-stage model was explicit were relocated here (2026-05-16).

## Layout

```
tile-structure/
├── manifest.yaml          ← 3-stage model, piece-role triggers, caption spec, provenance
├── README.md              ← this file
├── harvest_structure.py   ← on-disk DaSIG copy + Stage-3 relocation + byte-dedupe + provenance
├── SOURCES.json           ← per-file provenance — do not delete
└── raw-references/<piece>/   ← tile PNGs + per-image .txt caption sidecars
                              (tile_wall, tile_corner, tile_door, tile_endcap)
```

## Sources (operator directive 2026-05-16: no Gemini yet)

1. **On-disk DaSIG** — modular map-asset pieces already vendored in
   the `.corpus` tree (`WALL-NN`, `WALL-CORNER-NN`,
   `WALL-DOOR-NN`, `Doors/`, DaSIG-named). 40K-styled, primary bulk.
   Harvested from the `props/` tree only (`dasig-props/` is
   byte-identical).
2. **Stage-3 relocation** — wall/door pieces previously captioned
   into `stamps/train/fixtures/`, moved here and re-captioned to the
   tile spec, deduped against the DaSIG harvest.
3. **Online CC0** — Kenney / OpenGameArt CC0-1.0 only, supplementary
   structural variety. None retained with unclear license.

## Acquire → caption pipeline

1. `uv run harvest_structure.py` — copies/relocates + byte-dedupes +
   writes provenance. Harvest only.
2. **Visual review (cardinal rule).** Read every PNG; reject
   non-structural (furniture caught by a filename/substring),
   perspective, or watermarked; write a tile-spec `.txt` sidecar
   from the pixels per `manifest.yaml`. Misfits →
   `raw-references/_rejected/<reason>/`.
