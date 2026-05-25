# LoRA training corpora — Solenne campaign

This directory holds the reusable LoRA training material that backs
the wh40k-rpg cartography pipeline. Each subdirectory is one LoRA's
corpus + ai-toolkit config + training/eval support files. Generators
that build these corpora live one level up
(`gen_*_corpus.py`) and read the `manifest.yaml` inside each
subdirectory.

## Modular room pipeline — THREE stages

Hand-building a room from tiles is a three-stage pipeline, not one
LoRA. Keep these distinct:

| Stage | What it does | Corpus / trigger |
|---|---|---|
| **1 — tile generator** | new *tileable tiles* for hand-building: floors **and** wall/corner/door/endcap structure | `seamless-tiles/` (floors) **+** `tile-structure/` (structure) — both `dh_tile` |
| **2 — room builder** | place & connect Stage-1 tiles into rooms; link rooms (corridors, doorways) | `voidship-layouts/` — `dh_layout` |
| **3 — stamp placer** | drop furniture/props onto built rooms | `stamps/` — `dh_stamp` |

Stage 1 is split across two dirs (floors vs structure) but is **one
stage, one umbrella trigger** (`dh_tile`). A wall/corner/door is
Stage-1 tile vocabulary — **not** a Stage-3 stamp; pieces mis-binned
into `stamps/train/fixtures/` were relocated to `tile-structure/` on
2026-05-16 (see `../CORPUS_AUDIT.md`).

## Plan — 8 LoRAs

| # | LoRA                       | Trigger                | Folder                | Status                 | Purpose |
|---|----------------------------|------------------------|-----------------------|------------------------|---------|
| 1 | 40K iconography            | `sym_<name>` (11 syms) | `iconography/`        | **Trained v1 ✅; v2 corpus pending ($1.52, 38 supplements)** | Canonical Imperial heraldry. v1 step-3000 eval flagged aquila aspect ratio and four weak diagrammatic triggers (inq_rosette, administratum, arbites, imperial_navy); v2 manifest extension targets those — see `v2_extra_treatments` block in `iconography/manifest.yaml`. |
| 2 | DH2 character portraits    | `dh_portrait`          | `portraits/`          | Corpus ready (82) — training paused | Painterly 40K portrait LoRA across 15 archetype categories. Stacks with iconography at inference. |
| 3a | Voidship hull silhouettes | `dh_voidship_hull`     | `voidship-hulls/`     | Smoke validated (6/36) — 30 remaining ($1.20) | Empty Imperial voidship hull silhouettes per ship class. No interior. Three iterations on surface_rules to eliminate forward-facing turrets. |
| 3b | Architectural layouts      | `dh_layout`            | `voidship-layouts/`   | v1 fused corpus retained as supplemental; v2 zone-grammar pending ($0.80) | Top-down architectural layouts (rooms / corridors / doorways) generalized over an arbitrary boundary. Reusable for ship decks, hab apartments, manufactorums, chapels, district maps. |
| 4 | Narrative scenes           | `dh_scene`             | `scenes/`             | Scaffolded — full corpus pending ($2.44, 61 images) | Project goal #9 — chapel naves, sanctums, war rooms, audience halls, etc. Iconography composites at inference (no symbols in this LoRA's training set). |
| 5 | Stamp generator            | `dh_stamp`             | `stamps/`             | 227 trainable staged 2026-05-12 — ⚠ stale: 66 wall/door pieces relocated to Stage-1 `tile-structure/` on 2026-05-16 (fixtures 160→~94); trainable count needs re-derivation, see `../CORPUS_AUDIT.md` | Stage-3 top-down 40K furniture/equipment generator. Solves the missing-variant fill problem. |
| 6 | Seamless tiles (Stage-1 floors) | `dh_tile` + `tile_<archetype>_floor` | `seamless-tiles/` | Raw corpus acquired 2026-05-16 — 55 CC0 refs across 8 archetypes captioned; hex_plating/metal_grating pending supplemental gen | Stage-1 floor half. Edge-tileable top-down 40K floor/surface tiles. CC0 (ambientCG + Poly Haven), provenance in `SOURCES.json`. |
| 7 | Tile-structure (Stage-1 structure) | `dh_tile` + `tile_wall/corner/door/endcap` | `tile-structure/` | Harvested 2026-05-16 — 87 tiles captioned (40 on-disk DaSIG + 47 relocated from mis-binned `stamps/fixtures`, deduped); no Gemini per operator | Stage-1 structure half. Walls, corners, doors, endcaps for hand-building rooms. On-disk DaSIG + Stage-3 relocation, provenance in `SOURCES.json`. |

Voidships are split into two stacked LoRAs (hull + layout) rather
than one fused LoRA — see `../docs/battlemap-workflow.md` (search for
"two-LoRA architecture") for the rationale and the inference
pipeline. Short version: the layout LoRA generalizes beyond ships
and pays for itself across the wider battlemap surface.

## Directory layout

```
lora-training/
├── README.md                        ← this file
├── iconography/                     ← LoRA 1
│   ├── README.md                    ← manifest, training notes, trigger map
│   ├── manifest.yaml                ← corpus generation spec
│   ├── configs/iconography.yaml     ← ai-toolkit train config
│   ├── eval-samples/                ← step-0 / step-3000 sample images
│   ├── deploy_lora_to_comfyui.sh    ← deploy helper
│   └── iconography-<symbol>/        ← per-trigger PNG + .txt caption pairs
├── portraits/                       ← LoRA 2
│   ├── README.md                    ← manifest, training notes
│   ├── manifest.yaml
│   ├── configs/portraits.yaml       ← ai-toolkit train config (rank 32)
│   ├── strip_watermark.py           ← Gemini sparkle-watermark stripper
│   └── portrait-<archetype>/        ← per-archetype PNG + .txt caption pairs
├── voidship-hulls/                  ← LoRA 3a (Stage 1 of voidship pipeline)
│   ├── README.md                    ← manifest, hull silhouette taxonomy
│   ├── manifest.yaml                ← per-class hull descriptors, hull-state matrix
│   └── hull-<class>/                ← per-class blank-hull PNG + .txt caption pairs
└── voidship-layouts/                ← LoRA 3b (Stage 2 of voidship pipeline)
    ├── README.md                    ← manifest, zone grammar, layout vocabulary
    ├── manifest.yaml                ← zone grammar, archetype zone-maps
    ├── _references/                 ← style references retained for legacy
    ├── _smoke_test/                 ← incremental validation samples
    └── map-<class>/                 ← per-class layout PNG + .txt caption pairs
```

## Generator (one driver, plugin handlers)

A single `../corpus_generator.py` driver handles every LoRA. Each
manifest declares which handler to use via a top-level
`generator: <name>` field; the driver instantiates the matching
handler class and runs the shared throttle / IMAGE_SAFETY / cost-cap
loop.

```bash
uv run corpus_generator.py --lora iconography --dry-run
uv run corpus_generator.py --lora voidship-hulls --limit 6
uv run corpus_generator.py --lora portraits
```

Available handlers (registered in `corpus_generator.py`):

| Handler name      | Manifest field        | Reads                            | Writes into | Mode |
|-------------------|-----------------------|----------------------------------|-------------|------|
| `iconography`     | `generator: iconography`     | `iconography/manifest.yaml`     | `iconography/iconography-*/`  | API |
| `portrait`        | `generator: portrait`        | `portraits/manifest.yaml`       | `portraits/portrait-*/`       | API |
| `voidship_hull`   | `generator: voidship_hull`   | `voidship-hulls/manifest.yaml`  | `voidship-hulls/hull-*/`      | API |
| `voidship_layout` | `generator: voidship_layout` | `voidship-layouts/manifest.yaml`| `voidship-layouts/map-*/`     | API |
| `scene`           | `generator: scene`           | `scenes/manifest.yaml`          | `scenes/scene-*/`             | API |
| `stamp`           | `generator: stamp`           | `stamps/manifest.yaml`          | `stamps/all/`                 | **stage-only** (no API) |

Stage-only handlers source their PNGs from the filesystem (existing
curated stamps) and synthesize captions from sidecar metadata. They
short-circuit the run loop's API path — no Gemini calls, no cost,
no rate-limiting.

Adding a new LoRA: subclass `Handler` in `corpus_generator.py`, decorate
with `@register`, set a unique `name`, implement `build_jobs(only) →
list[Job]`. Then create `lora-training/<new>/manifest.yaml` with
`generator: <new_name>` at the top.

All handlers share the same append-only filename discipline — output
filenames embed sequential variant indices, so reordering a manifest
re-bills the corpus on next run. Append at the END.

## Training environment

ai-toolkit on **CT 140** (gigabyte host, 198.51.100.30, 3× RTX 3090,
DDP via `accelerate launch --multi_gpu --num_processes=3`) on Flex.1-
alpha base.

Mount layout on the CT:
- `/opt/lora-training/` — bind mount of this directory tree
- `/opt/lora-training/outputs/` — checkpoint output dir (per-LoRA)
- `/opt/lora-training/configs/` — staged ai-toolkit configs

Build the CT with `~/source/ai-lab/deploy-gigabyte-flux-lora.sh`
(invokes `install-flux-lora-trainer.sh` inside the CT). Bind mount
configuration is in the ai-lab inventory.

## Inference pipeline (planned)

```
class descriptor ─► hull LoRA      ─► empty hull image (one render per deck stack)
                                        │
zone-grammar layout ─► layout LoRA  ◄───┤
                                        ▼
                                    finished deck battlemap

+ stack iconography LoRA when scene material has named symbols
+ stack portrait LoRA when generating a character portrait
```

Multi-deck stacking falls out for free: same hull image input, called
once per deck description, all decks register on the same Foundry
tile bbox.

## Hard rules (LoRA training discipline)

- **Append-only manifests.** Output filenames embed sequential
  variant indices; reordering a manifest renames every downstream
  file and re-bills the corpus on next run.
- **No style descriptors in captions.** Style is a per-render anchor
  at inference; LoRAs learn shape / structure / silhouette / class —
  not a particular aesthetic. Ports of style into captions cause the
  trigger to bind to the wrong axis.
- **One trigger per concept, one folder per trigger.** Don't fold
  multiple subjects into a shared trigger; the LoRA learns the
  average of its training set.
- **Reference images must isolate the concept.** Scene-context images
  cause the trigger to bind to the scene rather than the concept.
- **Do not commit `.env`** — the Gemini API key lives in `../.env`.

## Status quick-look

For the current state of in-progress training runs, generation
budget, and recent eval results, see
`../docs/battlemap-workflow.md` (search for the most recent
`## YYYY-MM-DD` heading).
