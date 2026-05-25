# Seamless tile corpus — Stage 1 (floors)

> **Stage 1 of the 3-stage modular room pipeline** (see
> `../README.md` → "Modular room pipeline"). This dir is the
> **floor half** of the Stage-1 tile vocabulary; the **structure
> half** (walls/corners/doors/endcaps) is `../tile-structure/`.
> Same stage, same `dh_tile` umbrella. Stage 2 (place/connect tiles
> into rooms) = `../voidship-layouts/` `dh_layout`; Stage 3 (stamp
> the rooms) = `../stamps/` `dh_stamp`.

Backs TODO.md **"Seamless 1×1 tile LoRA for 40K room building"** and
the operator's *square-and-hex tileable cartography tiles* objective.
Trains a LoRA whose outputs are top-down, mutually edge-tileable 40K
floor/surface tiles dropped onto Foundry's tile layer to compose
rooms of any archetype at any size.

## Why "square AND hex"

Foundry V14 grids (square / hex-row / hex-col, pointy or flat top)
are a **scene overlay**. A tile image is grid-agnostic — any
edge-seamless texture composes correctly under either grid. So the
corpus captures two things:

1. **square-tileable** — generic 4-edge-seamless surfaces (the bulk:
   rockcrete, deck plate, rock, marble). Tile on a square lattice,
   read fine under a hex grid too.
2. **hex-pattern** — textures whose *motif* is hexagonal/honeycomb
   (`tile_hex_plating`, hex grating). 40K-iconic (Mechanicus /
   Necromunda industrial) and reinforces a hex aesthetic on hex
   scenes.

Both carry a mandatory tiling-type caption tag (`square-tileable`
or `hex-pattern`).

## Layout

```
seamless-tiles/
├── manifest.yaml          ← archetype→trigger map, caption spec, acceptance, provenance
├── README.md              ← this file
├── download_tiles.py      ← CC0 acquisition (ambientCG + Poly Haven)
├── SOURCES.json           ← per-file provenance (source, asset id, url, CC0) — do not delete
└── raw-references/<archetype>/   ← color maps + per-image .txt caption sidecars
```

Trigger namespace: umbrella `dh_tile` + per-archetype
(`tile_hab_floor`, `tile_industrial_floor`, `tile_ship_deck`,
`tile_chapel_floor`, `tile_medicae_floor`, `tile_tunnel_floor`,
`tile_sump_floor`, `tile_garrison_floor`, `tile_hex_plating`,
`tile_metal_grating`). Full rationale in `manifest.yaml`.

## Sources & license

Both sources are **CC0 1.0 (public domain)** — no attribution
legally required; provenance kept in `SOURCES.json` for auditability
and so supplemental generation knows its seeds.

- ambientCG — `https://ambientcg.com` — PBR materials, we keep only
  the `_Color` map from each 1K zip.
- Poly Haven — `https://polyhaven.com` — we keep the `Diffuse` 1k jpg.

## Acquire → caption pipeline

1. `uv run download_tiles.py` — pulls + bins + provenances. Acquisition only.
2. **Visual review (cardinal rule).** Read every file; reject
   non-orthographic / non-seamless / collage / watermarked; write a
   `.txt` caption sidecar at move-time describing the pixels, per the
   spec in `manifest.yaml`. Misfits → `raw-references/_rejected/<reason>/`.
3. Under-filled archetypes (esp. `tile_hex_plating`) are the
   supplemental-generation targets — Gemini-conditioned from the
   kept CC0 seeds.

Status of training runs / budget: see
`../../docs/battlemap-workflow.md` (latest dated heading).
