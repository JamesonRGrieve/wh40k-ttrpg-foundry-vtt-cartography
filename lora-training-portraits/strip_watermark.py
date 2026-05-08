#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Strip the Gemini Flash Image watermark (small four-pointed sparkle
in the bottom-right) from every PNG in a corpus folder.

Two stripping strategies, configurable per call:

  1. mode='inpaint' (default) — replaces the watermark region with a
     median-filtered patch from the surrounding pixels. Looks natural
     in most cases; may smear on busy textures right next to the
     watermark.

  2. mode='crop' — crops the bottom and right edges by N pixels and
     resamples back to the original dimensions. Lossless of structure
     but slightly zooms in (~3% on a 1024² image with N=32).

The watermark itself is consistent across Flash Image outputs:
  - small four-pointed star/sparkle
  - usually ~24-32px wide
  - sits inset from bottom-right by a small margin (~12-16px)
  - white-ish in luminance

Default region targeted: bottom-right 80×80 pixels, with a soft
fade so the patch blends. Adjust via --margin if your samples have
the watermark elsewhere.

Usage:
    uv run strip_watermark.py lora-training-portraits/ --mode inpaint
    uv run strip_watermark.py lora-training-portraits/portrait-aquilla --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def inpaint_corner(im: Image.Image, region_w: int, region_h: int) -> Image.Image:
    """Replace the bottom-right region with a blurred neighborhood
    sample. Soft-fades the patch into surrounding pixels so the
    transition is invisible."""
    W, H = im.size
    rgb = im.convert("RGB").copy()

    # Source region: a strip just to the LEFT of the watermark zone,
    # the same height. We tile/median-blend that strip across the
    # corner. Falls back to the row above if the left strip has the
    # same content as the corner (rare).
    sx0 = max(0, W - region_w * 2)
    sy0 = max(0, H - region_h)
    src_strip = rgb.crop((sx0, sy0, sx0 + region_w, H))

    # Heavy box blur on the source strip to smear out any feature
    # boundaries near the watermark
    blurred = src_strip.filter(ImageFilter.GaussianBlur(radius=12))

    # Paste the blurred strip into the corner, with a soft alpha
    # gradient on the left edge so the transition fades.
    mask = Image.new("L", (region_w, region_h), 255)
    fade_w = max(8, region_w // 4)
    fade_arr = np.array(mask, dtype=np.uint8)
    for x in range(fade_w):
        fade_arr[:, x] = int(255 * (x / fade_w))
    mask = Image.fromarray(fade_arr, mode="L")

    rgb.paste(blurred, (W - region_w, H - region_h), mask)
    return rgb


def crop_and_resample(im: Image.Image, margin: int) -> Image.Image:
    W, H = im.size
    cropped = im.crop((0, 0, W - margin, H - margin))
    return cropped.resize((W, H), Image.LANCZOS)


def process(path: Path, mode: str, region: int, margin: int, dry_run: bool) -> bool:
    if not path.is_file():
        return False
    try:
        im = Image.open(path)
    except Exception as e:
        print(f"  [skip] {path.name}: {type(e).__name__}: {e}", file=sys.stderr)
        return False
    if dry_run:
        print(f"  [dry] {path.name} ({im.size[0]}x{im.size[1]})")
        return True
    if mode == "inpaint":
        out = inpaint_corner(im, region, region)
    elif mode == "crop":
        out = crop_and_resample(im, margin)
    else:
        raise ValueError(f"unknown mode {mode!r}")
    out.save(path, optimize=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path,
                    help="folder to recurse into, OR a single .png path")
    ap.add_argument("--mode", choices=["inpaint", "crop"], default="inpaint")
    ap.add_argument("--region", type=int, default=80,
                    help="bottom-right region size to overwrite (px) when mode=inpaint")
    ap.add_argument("--margin", type=int, default=32,
                    help="bottom+right margin to crop when mode=crop")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if args.target.is_file():
        targets = [args.target]
    else:
        targets = sorted(p for p in args.target.rglob("*.png")
                         # skip our own caches / smoke tests / outputs
                         if "/_smoke_test/" not in str(p)
                         and "/outputs/" not in str(p))
    if args.limit:
        targets = targets[: args.limit]

    print(f"[plan] mode={args.mode} region={args.region} margin={args.margin} files={len(targets)}")
    if args.dry_run:
        for p in targets[:30]:
            print(f"  {p}")
        if len(targets) > 30:
            print(f"  ... ({len(targets)-30} more)")
        return 0

    ok = 0
    for p in targets:
        if process(p, args.mode, args.region, args.margin, args.dry_run):
            ok += 1
    print(f"[done] {ok}/{len(targets)} processed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
