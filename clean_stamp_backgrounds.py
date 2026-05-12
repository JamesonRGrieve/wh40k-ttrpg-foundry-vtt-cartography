#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Remove missed white-background pixels from extracted stamps.

`extract_stamps.py` uses connected-components on a not-gutter mask
to carve stamps out of their source grid. When the gutter color
detection misses pixels (typical with light-toned subjects on
near-white grids), small white regions inside the alpha-opaque area
remain — these are visible as white halos / blobs around object
edges or speckles on the stamp surface.

This script flood-fills from the image edges + existing transparent
regions inward, marking any white-ish pixel reachable that way as
background (alpha=0). White pixels SURROUNDED by non-white pixels
(legitimate white features on the object) stay opaque.

Tunables:
  --white-threshold  channel value (0-255) at which a pixel is
                     considered "near white". Default 235.
  --max-flood-area   guardrail: refuse to clear a flood region that
                     covers more than this fraction of the image
                     (prevents wiping out a legitimately white
                     subject). Default 0.35.
  --dry-run          report changes per file without writing.

Usage:
  uv run clean_stamp_backgrounds.py stamps
  uv run clean_stamp_backgrounds.py stamps --dry-run
"""
from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


def find_background_mask(arr: np.ndarray, white_thresh: int) -> np.ndarray:
    """BFS flood-fill from edges and from already-transparent pixels.
    Returns a boolean mask of pixels to clear (set alpha = 0).
    """
    h, w = arr.shape[:2]
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    is_whiteish = (r >= white_thresh) & (g >= white_thresh) & (b >= white_thresh)
    is_transparent = a < 16
    # Seeds: image-edge whiteish pixels + all transparent pixels'
    # whiteish neighbours. We use the union as a starting frontier
    # and expand only through whiteish pixels.
    visited = np.zeros((h, w), dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    # Seed all transparent pixels (their whiteish neighbours start the flood)
    ty, tx = np.where(is_transparent)
    for y, x in zip(ty, tx):
        visited[y, x] = True  # transparent pixels themselves don't need clearing

    def add_seed(y: int, x: int) -> None:
        if 0 <= y < h and 0 <= x < w and not visited[y, x] and is_whiteish[y, x]:
            visited[y, x] = True
            queue.append((y, x))

    # Edge seeds
    for x in range(w):
        add_seed(0, x)
        add_seed(h - 1, x)
    for y in range(h):
        add_seed(y, 0)
        add_seed(y, w - 1)
    # Adjacent-to-transparent seeds
    for y, x in zip(ty, tx):
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            add_seed(y + dy, x + dx)

    # 8-connected BFS through whiteish pixels
    while queue:
        y, x = queue.popleft()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                    if is_whiteish[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((ny, nx))

    # Clear mask: whiteish + reached, AND currently opaque
    return visited & is_whiteish & ~is_transparent


def process(path: Path, white_thresh: int, max_frac: float,
            dry_run: bool) -> tuple[bool, int, str]:
    try:
        im = Image.open(path).convert("RGBA")
    except Exception as e:
        return (False, 0, f"open-fail: {type(e).__name__}")
    arr = np.array(im)
    h, w = arr.shape[:2]
    mask = find_background_mask(arr, white_thresh)
    cleared = int(mask.sum())
    if cleared == 0:
        return (False, 0, "clean")
    if cleared / (h * w) > max_frac:
        return (False, cleared, f"refused (flood {cleared/(h*w):.0%} > {max_frac:.0%})")
    if dry_run:
        return (True, cleared, "would-clear")
    arr[..., 3][mask] = 0
    Image.fromarray(arr, "RGBA").save(path, optimize=True)
    return (True, cleared, "cleared")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="folder of PNGs (or a single PNG)")
    ap.add_argument("--white-threshold", type=int, default=235)
    ap.add_argument("--max-flood-area", type=float, default=0.35)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-cleared", type=int, default=5,
                    help="don't report files with fewer than this many cleared pixels")
    args = ap.parse_args()

    if args.target.is_file():
        targets = [args.target]
    else:
        targets = sorted(args.target.rglob("*.png"))

    changed = 0
    total_cleared = 0
    refused = 0
    for p in targets:
        ok, cleared, status = process(
            p, args.white_threshold, args.max_flood_area, args.dry_run)
        if status == "clean":
            continue
        if cleared >= args.min_cleared:
            print(f"  {p.name}: {cleared} px {status}")
        if ok:
            changed += 1
            total_cleared += cleared
        if "refused" in status:
            refused += 1

    mode = "would-clear" if args.dry_run else "cleared"
    print(f"\n[done] {changed}/{len(targets)} files {mode}, "
          f"{total_cleared} total px, {refused} refused (would exceed max-flood-area)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
