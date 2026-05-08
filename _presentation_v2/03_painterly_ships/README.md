# 03_painterly_ships — img2img painterly pass over spacecraft renders

Tests the HIGH-PRIORITY TODO approach: "use the spacecraft workflow
ONLY for layout + wall geometry, then run an img2img pass over it
through the interior txt2img path with a painterly Solenne-campaign
style prompt at moderate-to-high denoise."

Tool: `painterly_pass.py` (new this session). Pass 1 = the existing
spacecraft-mode renders (the `_before_*.png` files). Pass 2 = img2img
through BattlemapInteriorV1 with archetype-specific prompts and a
strong painterly negative (rejecting flat color / MS Paint / vector
graphic / blocky pixelation).

| Before | After | Style | Denoise | Seed |
| --- | --- | --- | --- | --- |
| `_before_bridge.png` | `ship_bridge_painterly_d055.png` | ship-bridge | 0.55 | 42 |
| `_before_bridge.png` | `ship_bridge_painterly_d075.png` | ship-bridge | 0.75 | 42 |
| `_before_engineering.png` | `ship_engineering_painterly_d075.png` | ship-engineering | 0.75 | 42 |
| `_before_barracks.png` | `ship_barracks_painterly_d075.png` | ship-barracks | 0.75 | 42 |
| `_before_cargo.png` | `ship_cargo_painterly_d075.png` | ship-cargo | 0.75 | 42 |

## Observation (mechanical, not aesthetic)

At denoise=0.55 the source flatness dominates — the after image
reads almost identically to the before. At 0.75 surface detail
appears (rust patina, console silhouettes, deck plate boundaries)
and the underlying deck geometry is preserved.

## Reference

`../07_reference/SOLENNE_section7_maintenance_tunnels.png` is the
painterly bar these candidates need to match.

## Operator decision needed

Whether 0.75 hits the painterly bar, or whether 0.85 / IPAdapter /
LoRA needs to be tried. Whether the ship-deck pixel-aligned hull
bbox (which is why these were rendered through spacecraft mode in
the first place) survives the painterly pass — visual inspection
side-by-side recommended.
