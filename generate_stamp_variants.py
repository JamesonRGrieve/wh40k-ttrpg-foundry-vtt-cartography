#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "PyYAML", "requests"]
# ///
"""Pipeline 1 — stamp variant generator (gap-filling + new archetypes).

Status: SKELETON. The full implementation lands once the symbol
library has canonicals and the operator has approved the style
direction. This script's CLI / argument shape is stable and the
runtime body is guarded so accidental invocation fails loud.

Purpose
-------
Today the 615-stamp vault has only what Gemini happened to draw.
There is no workflow that produces NEW stamps — variants of an
existing stamp at other rotations / damage states / activation
states, or wholly new archetypes (vehicles, full-body poses).

This driver fills that gap via a ComfyUI workflow
(`StampVariantsV1.json`, to build) using:
- Flux img2img seeded with the source stamp.
- IPAdapter (CLIP-ViT-H + ip-adapter-plus_sdxl_vit-h, already
  installed on the server) to encode source-stamp style.
- ControlNet depth/normal hints for rotational pose control on
  non-symmetric subjects.
- Strict negative prompts that forbid Imperial Aquila /
  Inquisition I / Mechanicus cog / etc — those are composited
  separately via symbol_compose.py.

Acceptance criteria for the first cut
-------------------------------------
1. Pick 5 source stamps with obvious gaps in their group_id cluster
   (e.g. a desk that only exists at top-down).
2. Generate the missing variants.
3. Run them through:
       extract_stamps.py (skip — already cropped) →
       make_sidecars.py →
       classify_stamps.py →
       assign_groups.py
4. Confirm group_id assigns the new variants to the SAME group
   as the source.

Until that round-trip works, do not scale this script.

Usage (planned)
---------------
    uv run generate_stamp_variants.py rotate <source.png> \
            --variants north south west \
            --strength 0.55

    uv run generate_stamp_variants.py condition <source.png> \
            --variants damaged destroyed \
            --strength 0.65

    uv run generate_stamp_variants.py archetype <prompt.txt> \
            --style-from <reference.png> \
            --count 8

Each invocation writes to `stamps/` so the rest of the pipeline picks
it up automatically. Sidecars are written by `make_sidecars.py` on
the next pipeline run; this script does not touch yamls directly.

LoRA fallback
-------------
If prompt + IPAdapter caps below acceptable style fidelity (~70%
operator-eyeball), train a Solenne-style LoRA from operator training
material. Defer until needed — see TODO.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAMPS_DIR = HERE / "stamps"


def _not_implemented(reason: str) -> int:
    print(
        "generate_stamp_variants.py is a SKELETON; the full pipeline is not yet wired up.",
        file=sys.stderr,
    )
    print(f"  reason: {reason}", file=sys.stderr)
    print(
        "  see the docstring at the top of this file and TODO.md "
        "(asset generation pipelines) for the build plan.",
        file=sys.stderr,
    )
    return 64  # EX_USAGE-ish; clearly not zero


def cmd_rotate(args: argparse.Namespace) -> int:
    return _not_implemented(
        "ComfyUI workflow StampVariantsV1.json not yet built; "
        "img2img + IPAdapter + ControlNet rotation chain pending."
    )


def cmd_condition(args: argparse.Namespace) -> int:
    return _not_implemented(
        "Damage/activation transformation pass not yet built. "
        "Plan: same workflow with prompt-driven condition cue."
    )


def cmd_archetype(args: argparse.Namespace) -> int:
    return _not_implemented(
        "Net-new archetype generation not yet built. "
        "Plan: txt2img with style-locking IPAdapter from operator-supplied reference."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("rotate", help="generate rotational variants of a source stamp")
    pr.add_argument("source", type=Path)
    pr.add_argument("--variants", nargs="+",
                    choices=["north", "south", "east", "west", "top-down", "isometric"],
                    required=True)
    pr.add_argument("--strength", type=float, default=0.55,
                    help="img2img denoise strength (0.0-1.0); higher = more reinterpretation")
    pr.add_argument("--seed", type=int, default=0)
    pr.set_defaults(func=cmd_rotate)

    pc = sub.add_parser("condition", help="generate damage/activation variants of a source stamp")
    pc.add_argument("source", type=Path)
    pc.add_argument("--variants", nargs="+",
                    choices=["intact", "damaged", "destroyed", "active", "inactive"],
                    required=True)
    pc.add_argument("--strength", type=float, default=0.65)
    pc.add_argument("--seed", type=int, default=0)
    pc.set_defaults(func=cmd_condition)

    pa = sub.add_parser("archetype", help="generate net-new archetype stamps from a text prompt")
    pa.add_argument("prompt", type=Path, help="path to a prompt file")
    pa.add_argument("--style-from", type=Path, required=True,
                    help="reference image whose style is encoded via IPAdapter")
    pa.add_argument("--count", type=int, default=4)
    pa.add_argument("--seed", type=int, default=0)
    pa.set_defaults(func=cmd_archetype)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
