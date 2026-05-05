# Cartography TODO

Open work, in priority order. Items are removed from this file as they
are completed (not merely struck through).

## 1. Recover dark-gutter source images in extraction

`extract_stamps.py` collapses the following 6 images into a single
component because their stamps are dark and their gutters are also dark
or visually similar to stamp content:

- `Gemini_Generated_Image_5ump9o5ump9o5ump.png` (currently 2 stamps,
  expected ~30+)
- `Gemini_Generated_Image_jgbyfsjgbyfsjgby.png` (1)
- `Gemini_Generated_Image_q5zlsqq5zlsqq5zl.png` (1)
- `Gemini_Generated_Image_qhlcmqhlcmqhlcmq.png` (1)
- `Gemini_Generated_Image_uy5kbuy5kbuy5kbu.png` (1)
- `Gemini_Generated_Image_z8itcwz8itcwz8it.png` (1)

Approaches to try, cheapest first:

1. Sample gutter color from the **mode** (peak of histogram of border
   pixels) rather than the median, so a partially stamp-occluded border
   doesn't drag the sample into stamp territory.
2. Per-image `GUTTER_TOL` auto-tune: pick the smallest tolerance such
   that at least N components above `MIN_COMPONENT_AREA` exist (binary
   search on tolerance).
3. As a fallback, run an edge detector and use detected vertical/horizontal
   line segments to seed gutter inference.

Acceptance: every source image in this directory yields ≥10 stamps OR is
explicitly listed as unprocessable in this file with a reason.

## 2. Per-stamp metadata sidecar schema

Goal: each generated stamp gets a YAML sidecar at
`stamps/<source-stem>_NN.yaml` with this minimum:

```yaml
name: # human-readable, e.g. "Wooden Bed (intact)"
description: # 1–2 sentences
tags: [furniture, sleeping, low-quality] # lowercase-hyphenated, vault tag conventions
orientation: # one of: north, south, east, west, top-down, isometric, null
state: # one of: intact, damaged, destroyed, active, inactive, null
group_id: # stable id grouping variants of the same object across orientations/states
source: # original grid image path, for traceability
extracted_at: # ISO-8601 timestamp
```

Open questions:
- Is `group_id` derived from a hash of canonical name, or assigned
  sequentially as stamps are imported into the metadata DB?
- Should descriptions live in the sidecar or a single combined
  `manifest.yaml`? Lean toward sidecars for diff-friendliness.

## 3. ComfyUI image-classification driver

Server: `198.51.100.11` (HTTP port assumed standard ComfyUI 8188; verify).

Build `classify_stamps.py` that:
- For each stamp PNG, POSTs an inference request to ComfyUI running a
  workflow that returns:
  - `orientation` from a fixed vocab
  - `state` (intact / damaged / destroyed / active / inactive)
  - `category` tags (furniture, weapon, container, document, …)
- Writes results into the sidecar from item 2.
- Is idempotent: re-runs only re-classify stamps with no sidecar OR
  with `--force`.

Open work:
- Author the ComfyUI workflow JSON (the model + nodes that produce the
  three classification heads). Likely candidates: a CLIP zero-shot
  classifier with curated label sets per dimension, or a small fine-tuned
  vision model if accuracy is insufficient.
- Decide grouping for variants: same object across orientations/states
  should share `group_id`. Likely a CLIP image-embedding similarity pass
  with a manual review threshold.

## 4. Variant grouping & state association in Foundry

With the plugin choice resolved (Baileywiki Mass Edit + Monk's Active
Tiles), the design space narrows to:

- **Variant cycling within a single tile**: Monk's Active Tiles `Image
  Cycle` action driven by toggle triggers. One tile entity per in-fiction
  object; state changes by clicking it or via macro.
- **Variant selection at placement time**: Mass Edit's prefab/variant
  grouping lets the GM drop a "wooden bed" prefab and pick the desired
  state from the variants list.

Open: write `ADR-001-variant-state.md` once the metadata sidecar schema
(item 2) is finalized, since that schema dictates how variants resolve to
prefab definitions and Image-Cycle frame lists.

## 5. Connect to VTT server and audit installed cartography modules

Per `../../VTT_WIKI.md`, the VTT is at `https://vtt.jamesonrgrieve.ca`.
Confirm which mapping/cartography-related modules are installed today,
and which of them are V14-verified vs running on compatibility shims.
This bounds the plugin selection in item 4.
