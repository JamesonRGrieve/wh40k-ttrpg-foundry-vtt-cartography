# DH2 character portraits LoRA

Trigger: `dh_portrait`. Painterly Warhammer 40K character portrait
LoRA across the 15 archetype categories present in a Dark Heresy 2e
campaign. Stacks with the iconography LoRA at inference for full
canonical 40K rendering.

## Categories (15)

`portrait-administratum`, `portrait-arbites`, `portrait-astropath`,
`portrait-civilian-trader`, `portrait-civilian-worker`,
`portrait-ecclesiarchy`, `portrait-flagellant`,
`portrait-hive-underclass`, `portrait-imperial-guard`,
`portrait-imperial-navy`, `portrait-inquisition`,
`portrait-mechanicum`, `portrait-medicae`, `portrait-nobility`,
`portrait-voidship-crew`.

## Caption format

```
dh_portrait, <gender> <age>, <build>, <archetype>, <expression>, <lighting>, oil painting dark palette grimdark portrait
```

No subject-name leakage. Each caption is the trigger + the variable
matrix axes (gender × age × build × expression × lighting) + a
generic style trailer.

## Generation

Driver: `../../gen_portrait_corpus.py`. Reads
`portraits/manifest.yaml`. Reference-conditioned generation per
category — when a category has a deployed portrait reference (e.g.,
the Edric Family images, Pell Osric, the test_inquisitor renders),
that reference anchors style only and the prompt explicitly
forbids reproducing its subject / clothing / scene / pose.

## Watermark stripping

Gemini outputs carry a small four-pointed sparkle watermark in the
bottom-right corner. `strip_watermark.py` overwrites the bottom-right
80×80 region with a Gaussian-blurred sample of the surrounding
pixels (default `--mode inpaint`).

The iconography LoRA training (rank 16, 3000 steps) showed the
watermark did NOT bind to any trigger — at training resolution
(768–1024) the ~24px sparkle is too small relative to subject mass.
The portrait LoRA's higher rank (32) and tighter subject framing
may differ; eval after training to decide whether the strip pass is
necessary.

## Training config

`configs/portraits.yaml` — ai-toolkit on Flex.1-alpha base, rank 32 /
alpha 32, lr 1e-4, 3000 steps, save_every 250, EMA 0.99, multi-GPU
DDP via accelerate. Resolution buckets [512, 768, 1024].

## Status

- Corpus complete: 105 images across 15 archetype folders.
- Watermark-stripped pass complete.
- Training: NOT yet started. Operator-paused after iconography
  training to evaluate before queuing more training time.

## Files

```
portraits/
├── README.md                        ← this file
├── manifest.yaml                    ← matrix axes, per-category archetypes
├── strip_watermark.py               ← Gemini sparkle stripper
├── configs/portraits.yaml           ← ai-toolkit train config
└── portrait-<archetype>/            ← 15 archetype folders, ~7 images each
```
