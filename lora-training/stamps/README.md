# Stamp generator LoRA

Trigger: `dh_stamp`. Top-down 40K furniture / equipment / fixture
generator. Trained on the existing curated stamps library
(`../../stamps/`, ~600 PNGs).

## What this LoRA solves

The stamps library is built by Gemini-grid extraction → Florence-2
classification → CLIP-grouping. That pipeline is upstream-batchy:
to get a single new stamp you must generate a whole grid of ~16,
extract, classify, and audit. A stamp LoRA flips this to on-demand
single-stamp generation:

- **Missing-variant fill.** Group has intact + damaged but no
  destroyed → render `dh_stamp, <name>, destroyed, <orientation>`.
- **Targeted additions.** Need a specific subject Florence-2 didn't
  caption well → render directly with the LoRA.
- **Style-locked supplements.** Generated stamps stay consistent
  with the extracted library aesthetic for free, instead of having
  to re-audit a Gemini render against the existing palette.

## Corpus

No API spend — captions are synthesized from existing stamp
sidecars at staging time.

```
uv run corpus_generator.py --lora stamps
```

The `stamp` handler walks `../../stamps/*.yaml`, reads each sidecar
(name / description / tags / orientation / state), and:

1. Hardlinks the PNG into `stamps/all/<stem>.png`.
2. Writes a paired `stamps/all/<stem>.txt` with the synthesized
   caption.

Hardlinks share inodes with the original `stamps/*.png` files —
re-classifying a stamp updates both copies; deleting from either
location leaves the other intact (it's a true link, not a symlink).

## Caption format

```
dh_stamp, <name>, <orientation> view, <state>, <top 8 tags>, <description if short>
```

Stamps with no `name` (Florence-2 silent fails — ~2.7% of the
corpus per CLAUDE.md gotcha #19, which retroactive cleanup should
have removed) are skipped at staging time. Long descriptions
(>240 chars) are dropped from the caption to keep the trigger
strong; the rest of the caption still carries enough information
for the LoRA to bind on subject + state + orientation.

## Training config

To be written. The training run for this LoRA is not yet queued —
operator-paused at the same point as portraits.

## Filtering and sorting (2026-05-11)

The StampHandler routes every staged stamp by orientation +
category:

- **Top-down** stamps go into `train/<category>/`. Categories are
  derived from tags + name via a deterministic first-match map in
  `corpus_generator.py:STAMP_CATEGORIES`:
  furniture, containers, machinery, ordnance, documents, fixtures,
  ornaments, vessels, misc. Stamps that match none land in `misc`.
- **Non-top-down** stamps (isometric, unknown) are quarantined in
  `_excluded/<orientation>/<category>/` and excluded from training
  by default. They remain available for future re-orientation or
  inclusion when the LoRA's view convention expands.
- **Null-name** stamps (audited Florence-2 garbage or silent fails)
  are skipped entirely — their PNGs stay in `../../stamps/` for
  possible re-classification later.

Cardinal orientations (north/south/east/west) are NOT a meaningful
axis for orthographic stamps — Foundry rotates tiles freely at
runtime, so "which way is the chair facing" is a placement
concern, not a training property. The classifier (post-2026-05-11)
collapses cardinal-direction captures to `top-down` at write time.

## Future regen — 20° forward-tilted view

Operator's preferred view convention is **top-down with a slight
20° tilt toward the front** (similar to the Errant Vector and
deployed Solenne battlemap aesthetic). The current corpus is pure
orthographic top-down. A future Gemini regeneration targeting that
specific view will produce stamps in the operator's preferred
convention; until then, training on pure-orthographic is the
honest baseline and a stylistic tilt can be applied at inference.

## Files

```
stamps/
├── README.md                       ← this file
├── manifest.yaml                   ← staging config
├── configs/stamps.yaml             ← ai-toolkit training config
├── train/                          ← top-down stamps, per-category
│   ├── containers/                 ← crates, boxes, barrels, bottles
│   ├── documents/                  ← books, scrolls, parchments
│   ├── fixtures/                   ← doors, hatches, stairs, pipes
│   ├── furniture/                  ← chairs, tables, beds, lockers
│   ├── machinery/                  ← consoles, cogitators, engines
│   ├── misc/                       ← uncategorized top-down
│   ├── ordnance/                   ← weapons, ammo, torpedoes
│   ├── ornaments/                  ← banners, candle stands, censers
│   └── vessels/                    ← (none yet)
└── _excluded/                      ← non-top-down quarantine
    ├── isometric/                  ← isometric / three-quarter
    └── unknown/                    ← no orientation keyword in caption
```
