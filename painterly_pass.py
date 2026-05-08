#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "requests", "numpy", "opencv-python-headless", "PyYAML"]
# ///
"""Painterly img2img pass over an existing battlemap render.

Takes a base render (typically the spacecraft-mode workflow's output —
geometrically correct but visually flat) and runs it through the proven
interior-mode txt2img path at moderate-to-high denoise, with a strong
Solenne-painterly style prompt. The intent is to keep the underlying
layout (walls, floor regions, openings) while repainting surfaces with
oil-paint texture matched to the deployed
``SOLENNE_section7_maintenance_tunnels.png`` and
``SOLENNE_block9_unit14_edric_residence.png`` references.

Usage::

    uv run painterly_pass.py path/to/base.png \\
        --style ship-bridge \\
        --denoise 0.55 \\
        --seed 42 \\
        --output path/to/painterly.png

`--style` selects a per-archetype prompt (ship-bridge, ship-engineering,
ship-barracks, ship-cargo, hab, manufactorum, chapel, sump, ...).
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_battlemap import (  # type: ignore[import-not-found]
    poll_history,
    submit_prompt,
    _saved_images_from_history,
    _download_first,
)
from generate_stamp_variants import (  # type: ignore[import-not-found]
    build_img2img_workflow,
    upload_input_image,
)

PAINTERLY_NEG_T5 = (
    "flat solid color, untextured surface, vector graphic, MS Paint, blocky pixelation, "
    "perfectly clean geometry, computer-generated rendering, white background, "
    "anime, cartoon, cel shading, photorealistic, photograph, low resolution, "
    "watermark, text, signature, isometric perspective"
)
PAINTERLY_NEG_CLIP_L = (
    "flat color, untextured, vector, ms paint, blocky, anime, cartoon, photo"
)

# Per-archetype style prompts. All share the same Solenne painterly anchor
# clauses; the lead noun differentiates the surfaces.
_STYLE_BASE = (
    "warhammer 40000 grimdark aesthetic, painterly oil-painting illustration, "
    "thick visible brushwork, weathered metal plating, scratched paint, "
    "rust patina, oil stains on the deck, dramatic chiaroscuro from overhead "
    "lumen-strips, deep shadows in the corners, top-down overhead orthographic "
    "view, professional concept art quality, "
)
STYLE_PROMPTS: dict[str, str] = {
    "ship-bridge": (
        "top-down overhead orthographic view of a starship bridge interior, "
        "command consoles flanking a central command throne, cogitator banks, "
        "viewscreen runners along the front bulkhead, brass and pitted steel deck plates, "
    ) + _STYLE_BASE,
    "ship-engineering": (
        "top-down overhead orthographic view of a starship engineering deck interior, "
        "plasma reactor housing in the center, fuel manifolds, coolant pipework, "
        "grated catwalks, oil-stained gantry plates, sodium-yellow service lighting, "
    ) + _STYLE_BASE,
    "ship-barracks": (
        "top-down overhead orthographic view of a starship crew barracks interior, "
        "rows of stacked bunks, footlockers, narrow central aisle, "
        "tarnished steel deck plates, dim sconce lighting, "
    ) + _STYLE_BASE,
    "ship-cargo": (
        "top-down overhead orthographic view of a starship cargo bay interior, "
        "loading bay doors, crate stacking grids, tie-down rails, "
        "scuffed deck plating with hauler tracks, sodium service lighting, "
    ) + _STYLE_BASE,
    "hab": (
        "top-down overhead orthographic view of a hive-world hab apartment interior, "
        "stained ferrocrete floor, water-marked walls, sagging ceiling panels, "
        "warm tungsten kitchen light spilling onto the floor, "
    ) + _STYLE_BASE,
    "chapel": (
        "top-down overhead orthographic view of an Imperial chapel interior, "
        "ornate flagstone floor, votive candles in sconces along the side walls, "
        "central nave, stained-glass colored light pooling on the stone, "
    ) + _STYLE_BASE,
    "sump": (
        "top-down overhead orthographic view of a grimy underground bar interior, "
        "stained metal-grate floor, scattered crates and stools, dim red bulbs, "
        "puddles of spilled liquor reflecting the light, "
    ) + _STYLE_BASE,
}

_STYLE_CLIP_L: dict[str, str] = {
    k: f"warhammer 40k, grimdark, painterly oil painting, top-down battlemap, {k}"
    for k in STYLE_PROMPTS
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", type=Path, help="Path to the base render PNG (input to img2img).")
    ap.add_argument("--style", required=True, choices=sorted(STYLE_PROMPTS),
                    help="Archetype prompt selector.")
    ap.add_argument("--denoise", type=float, default=0.55,
                    help="img2img denoise. 0.45 preserves geometry; 0.65 repaints surfaces; "
                         "0.80+ may invent new geometry. 0.50-0.65 is the sweet spot for "
                         "'preserve layout, paint surfaces' on flat spacecraft renders.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--server", default="http://198.51.100.11:8188")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    if not args.base.is_file():
        print(f"base render not found: {args.base}", file=sys.stderr)
        return 2

    server_name = upload_input_image(args.server, args.base)
    prefix = args.output.stem
    t5 = STYLE_PROMPTS[args.style]
    clip_l = _STYLE_CLIP_L[args.style]
    wf = build_img2img_workflow(
        server_image=server_name,
        t5xxl=t5,
        clip_l=clip_l,
        neg_t5xxl=PAINTERLY_NEG_T5,
        neg_clip_l=PAINTERLY_NEG_CLIP_L,
        denoise=args.denoise,
        seed=args.seed,
        save_prefix=prefix,
    )
    client_id = uuid.uuid4().hex
    print(f"[painterly] {args.base.name} → style={args.style} denoise={args.denoise} seed={args.seed}",
          file=sys.stderr)
    pid = submit_prompt(args.server, wf, client_id)
    print(f"[painterly] prompt_id={pid}", file=sys.stderr)
    record = poll_history(args.server, pid)
    saved = _saved_images_from_history(record)
    if not saved:
        print("no SaveImage outputs", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = _download_first(args.server, saved, prefix)
    if rendered != args.output:
        # _download_first writes into battlemaps/; copy to requested location.
        from shutil import copy2
        copy2(rendered, args.output)
        print(f"[painterly] wrote {args.output} (raw at {rendered})", file=sys.stderr)
    else:
        print(f"[painterly] wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
