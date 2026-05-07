#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "PyYAML", "requests"]
# ///
"""Pipeline 3 — scene picture generator.

Status: SKELETON. Implementation deferred until the symbol library
has canonical art and the operator has approved a stylistic
direction.

Purpose
-------
Establishing shots, lore illustrations, document handouts, and
investigation-photo handouts. Various aspect ratios (16:9 hero
shots, 1:1 handouts, 3:4 portraits of locations). Often heavy with
canonical 40K iconography — a single Imperial chapel scene can
require 5+ symbol composites (Aquila on apse, Inquisition I over
the door, skull-laurel on the lectern, …).

Workflow & symbology
--------------------
- ComfyUI workflow: `ScenePictureV1.json` (to build).
- Flux txt2img with optional ControlNet depth for spatial
  composition (so the operator can sketch a rough block-out and
  let diffusion fill in the look).
- Negative prompts forbid all canonical symbol generation; symbol
  composite walks a list of declared anchors after the render.
- Multi-symbol handling: a scene can declare any number of
  placements; symbol_compose.py applies them in order.

Acceptance criteria for the first cut
-------------------------------------
1. Generate 3 scene pictures:
   - Hab District 4 establishing shot (no symbols required).
   - District 4 Chapel interior (≥2 canonical symbols).
   - Astropathic Relay Station (≥1 canonical symbol).
2. All canonical symbols pass canny-IoU validation post-composite.
3. Operator approves stylistic match.

Output convention
-----------------
Writes to `../../Lore/handouts/<slug>.png` and
`<slug>.json` (sidecar). Aspect ratio is operator-specified.

Usage (planned)
---------------
    uv run generate_scene_picture.py \
        --location "[[Hab District 4]]" --aspect 16:9 \
        --mood "grimdark, smog, midday" \
        --output "../../Lore/handouts/hab_district_4_establishing.png"

    uv run generate_scene_picture.py \
        --location "[[District 4 Chapel]]" --aspect 4:3 \
        --mood "candlelit, somber, post-service" \
        --symbol "aquila:apse_back,large" \
        --symbol "skull_laurel:lectern_front,small" \
        --output "../../Lore/handouts/district_4_chapel.png"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _not_implemented(reason: str) -> int:
    print(
        "generate_scene_picture.py is a SKELETON; the full pipeline is not yet wired up.",
        file=sys.stderr,
    )
    print(f"  reason: {reason}", file=sys.stderr)
    print(
        "  see the docstring at the top of this file and TODO.md "
        "(asset generation pipelines) for the build plan.",
        file=sys.stderr,
    )
    return 64


def cmd_scene(args: argparse.Namespace) -> int:
    return _not_implemented(
        "ComfyUI workflow ScenePictureV1.json not yet built; "
        "Flux txt2img + multi-symbol composite pending. "
        "Symbol compose pass is ready but blocked on canonical PNGs in symbols/."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location", required=True,
                    help="wikilink-style location id (e.g. '[[District 4 Chapel]]')")
    ap.add_argument("--aspect", default="16:9",
                    help="aspect ratio (e.g. 16:9, 4:3, 1:1)")
    ap.add_argument("--mood", required=True,
                    help="prose mood/lighting description fed into the prompt")
    ap.add_argument("--symbol", action="append", default=[],
                    metavar="NAME:anchor[,size]",
                    help="symbol composite spec; repeatable. anchor names depend on the scene template.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--output", type=Path, required=True)
    ap.set_defaults(func=cmd_scene)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
