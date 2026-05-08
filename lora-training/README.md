# LoRA training corpora — Solenne campaign

This directory holds the reusable LoRA training material that backs
the wh40k-rpg cartography pipeline. Each subdirectory is one LoRA's
corpus + ai-toolkit config + training/eval support files. Generators
that build these corpora live one level up
(`gen_*_corpus.py`) and read the `manifest.yaml` inside each
subdirectory.

## Plan — 4 LoRAs (or 5, depending on how you count voidships)

| # | LoRA                       | Trigger                | Folder                | Status      | Purpose |
|---|----------------------------|------------------------|-----------------------|-------------|---------|
| 1 | 40K iconography            | `sym_<name>` (11 syms) | `iconography/`        | Trained ✅  | Canonical Imperial heraldry stamped onto scenes (aquila, rosette, mech_cog, etc.). Reusable across all 7 wh40k-rpg game systems. |
| 2 | DH2 character portraits    | `dh_portrait`          | `portraits/`          | Corpus ready | Painterly 40K portrait LoRA, 105 image corpus across 15 archetype categories. Stacks with iconography at inference. |
| 3a | Voidship hull silhouettes | `dh_voidship_hull`     | `voidship-hulls/`     | **In progress (Stage 1)** | Empty Imperial voidship hull silhouettes per ship class. No interior. Output is a blank hull at the right proportions for the class. |
| 3b | Architectural layouts      | `dh_layout`            | `voidship-layouts/`   | Corpus partial (Stage 2) | Top-down architectural layouts (rooms / corridors / doorways) generalized over an arbitrary boundary. Reusable for ship decks, hab apartments, manufactorums, chapels, district maps. |

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

## Generators (one level up)

Each LoRA has a sibling `gen_<name>_corpus.py` driver that reads its
manifest and renders into the corresponding folder. All four use the
same Gemini 2.5 Flash Image API, the same `IMAGE_SAFETY` defensive
parser, and the same append-only manifest pattern — output filenames
embed sequential variant indices, so reordering a manifest re-bills
the corpus on next run. Append at the END.

| Generator | Reads manifest | Writes into |
|-----------|---------------|-------------|
| `../gen_iconography_corpus.py`   | `iconography/manifest.yaml`     | `iconography/iconography-*/` |
| `../gen_portrait_corpus.py`      | `portraits/manifest.yaml`       | `portraits/portrait-*/` |
| `../gen_voidship_hull_corpus.py` | `voidship-hulls/manifest.yaml`  | `voidship-hulls/hull-*/` |
| `../gen_voidship_corpus.py`      | `voidship-layouts/manifest.yaml`| `voidship-layouts/map-*/` |

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
