# 05_iconography_scenes — integrated-iconography candidates

Tests the HIGH-PRIORITY TODO approach #1: "Raise pass-2 denoise to
0.75–0.85 with a strong material prompt." Pipeline:
`generate_scene_picture.py --symbol-style integrated
--integration-denoise <X>`. Pass 1 = scene render. Pass 2 = paste
black silhouette of the canonical symbol at the named anchor, then
img2img repaint at denoise X with material-hint prompt augmentation.

| File | Anchor | Material hint | Denoise | IoU vs paste |
| --- | --- | --- | --- | --- |
| district4_chapel_d080.png | apse_back | brass-relief | 0.80 | 0.283 |
| vigil_ledger_aquila_hull_d065.png | ship_hull_marking | stamped-metal | 0.65 | 0.174 |
| vigil_ledger_aquila_hull_d080.png | ship_hull_marking | stamped-metal | 0.80 | 0.008 |

(IoU here is the validator's silhouette-overlap score against the
black paste-on-top reference. At higher denoise the symbol gets
repainted into surrounding scene material; low IoU is the *intended*
behavior, not a failure mode.)

## Observation (mechanical)

- Chapel apse (high-contrast wall surface, large symbol footprint):
  at d=0.80 the silhouette was repainted as a winged stone/brass
  statue with candlelit highlights. Silhouette no longer matches
  the source paste, by design.
- Ship hull (flat dark metal, large symbol footprint): at d=0.65
  the silhouette is faint but partially preserved (IoU 0.174).
  At d=0.80 it disappears entirely (IoU 0.008) — the hull surface
  fully repaints over the symbol.

## Reference

`_reference_deployed_vigil_ledger.png` — the deployed Vigil Ledger
with a clear, deeply-stamped aquila on the hull. This is the
target for the ship-hull integration; my d=0.65 and d=0.80
candidates do not match it. Untried levers: localized inpainting
with a tight mask on the symbol region, IPAdapter conditioning
using this very reference image.

## Operator decision needed

- Chapel d=0.80: does the apse statue read as integrated iconography
  per the goal? If yes, this is a working pattern for chapel-class
  scenes. If no, what's missing?
- Vigil Ledger candidates: both fall short of the deployed reference
  on the hull aquila. Should I try localized inpainting next, or
  switch to IPAdapter reference conditioning, or skip the
  retry pending a different reference image?
