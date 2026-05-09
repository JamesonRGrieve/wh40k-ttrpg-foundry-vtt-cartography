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

## Files

```
stamps/
├── README.md              ← this file
├── manifest.yaml          ← generator config (no axes — 1:1 with sidecars)
└── all/                   ← staged corpus (populated by --lora stamps)
    ├── <stem>.png         ← hardlink to ../../stamps/<stem>.png
    └── <stem>.txt         ← synthesized caption
```
