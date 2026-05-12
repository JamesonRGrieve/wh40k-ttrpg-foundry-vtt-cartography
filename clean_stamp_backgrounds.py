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


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """8-connected component labeling on a boolean mask. Returns
    (labels, count) where labels is an int array (0 = background) and
    count is the number of components. Pure-numpy BFS — avoids the
    scipy dependency.
    """
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    next_label = 0
    ys, xs = np.where(mask)
    for y, x in zip(ys, xs):
        if labels[y, x] != 0:
            continue
        next_label += 1
        stack: list[tuple[int, int]] = [(y, x)]
        while stack:
            cy, cx = stack.pop()
            if labels[cy, cx] != 0 or not mask[cy, cx]:
                continue
            labels[cy, cx] = next_label
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if (0 <= ny < h and 0 <= nx < w
                            and labels[ny, nx] == 0 and mask[ny, nx]):
                        stack.append((ny, nx))
    return labels, next_label


def find_background_mask(arr: np.ndarray, white_thresh: int,
                         pure_white_thresh: int,
                         min_interior_blob: int) -> np.ndarray:
    """Combine two passes:

    1. Edge-connected near-white flood (white_thresh). Catches halos
       around the stamp boundary, gutter pixels that bled through,
       and any opaque whitish region that connects via 8-neighbour
       chain to an image edge or to existing transparent pixels.

    2. Interior pure-white blob detection (pure_white_thresh,
       min_interior_blob). Catches isolated holes inside the stamp
       body — gutter color that was bounded by the subject and
       wasn't reachable from the edge. Default threshold is exact
       #FFF (255 on all channels) per the 2026-05-11 operator
       directive — anything less strict risks clearing legitimate
       cream / eggshell / off-white highlights. Minimum size is
       3×3 (9 px).

    Returns a boolean mask of pixels to clear (set alpha = 0).
    """
    h, w = arr.shape[:2]
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    is_whiteish = (r >= white_thresh) & (g >= white_thresh) & (b >= white_thresh)
    is_pure_white = ((r >= pure_white_thresh)
                     & (g >= pure_white_thresh)
                     & (b >= pure_white_thresh))
    is_transparent = a < 16
    is_opaque = ~is_transparent

    # ── Pass 1: edge-connected near-white flood ────────────────────
    visited = np.zeros((h, w), dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    ty, tx = np.where(is_transparent)
    for y, x in zip(ty, tx):
        visited[y, x] = True  # transparent pixels are seeds, not clear targets

    def add_seed(y: int, x: int) -> None:
        if 0 <= y < h and 0 <= x < w and not visited[y, x] and is_whiteish[y, x]:
            visited[y, x] = True
            queue.append((y, x))

    for x in range(w):
        add_seed(0, x)
        add_seed(h - 1, x)
    for y in range(h):
        add_seed(y, 0)
        add_seed(y, w - 1)
    for y, x in zip(ty, tx):
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            add_seed(y + dy, x + dx)

    while queue:
        y, x = queue.popleft()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if (0 <= ny < h and 0 <= nx < w and not visited[ny, nx]
                        and is_whiteish[ny, nx]):
                    visited[ny, nx] = True
                    queue.append((ny, nx))

    edge_mask = visited & is_whiteish & is_opaque

    # ── Pass 2: interior pure-white blobs ≥ min_interior_blob ──────
    # Label all pure-white opaque pixels NOT already in the edge mask
    # (those are handled by Pass 1). Components with area at or above
    # the threshold are flagged as background holes.
    interior_candidates = is_pure_white & is_opaque & ~edge_mask
    interior_mask = np.zeros((h, w), dtype=bool)
    if interior_candidates.any():
        labels, n = _label_components(interior_candidates)
        if n > 0:
            sizes = np.bincount(labels.ravel())  # index 0 = background
            big_labels = np.where(sizes >= min_interior_blob)[0]
            big_labels = big_labels[big_labels != 0]
            if big_labels.size:
                interior_mask = np.isin(labels, big_labels)

    return edge_mask | interior_mask


def process(path: Path, white_thresh: int, pure_white_thresh: int,
            min_interior_blob: int, max_frac: float,
            dry_run: bool) -> tuple[bool, int, str]:
    try:
        im = Image.open(path).convert("RGBA")
    except Exception as e:
        return (False, 0, f"open-fail: {type(e).__name__}")
    arr = np.array(im)
    h, w = arr.shape[:2]
    mask = find_background_mask(arr, white_thresh, pure_white_thresh,
                                min_interior_blob)
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
    ap.add_argument("--white-threshold", type=int, default=235,
                    help="edge-flood near-white threshold (Pass 1)")
    ap.add_argument("--pure-white-threshold", type=int, default=255,
                    help="interior pure-white blob threshold (Pass 2). "
                         "Default 255 = exact #FFF only, per operator "
                         "directive. Raise above 255 to disable Pass 2; "
                         "lower at your own risk (can clear legitimate "
                         "cream/eggshell highlights).")
    ap.add_argument("--min-interior-blob", type=int, default=9,
                    help="minimum interior pure-white blob size to clear "
                         "(default 9 = 3x3 px, per operator heuristic)")
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
            p, args.white_threshold, args.pure_white_threshold,
            args.min_interior_blob, args.max_flood_area, args.dry_run)
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
