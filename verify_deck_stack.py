# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Verify a set of ship-deck layouts will stack pixel-perfect in Foundry.

Foundry stacks two scene images at the same coordinates without
re-anchoring. For multi-deck use, every deck's CANVAS SIZE and OUTER
HULL BOUNDING BOX must be identical so a token at coord (X, Y) on
deck1 corresponds to the same physical location on deck2. Per-deck
openings (windscreen, ramp) intentionally modify rim pixels — they
extend the bbox in their direction, but the hull itself is shared.

Default checks the four `ship-*` preset layouts produced by
`make-floorplan`, but accepts arbitrary layout PNGs as positional args.

Usage:
    uv run verify_deck_stack.py                      # default 4 decks
    uv run verify_deck_stack.py L1.png L2.png L3.png # custom set
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent

WALL_RGB = (0x30, 0x30, 0x30)
DECKS = ["bridge", "engineering", "barracks", "cargo"]


def wall_mask(path: Path) -> np.ndarray:
    arr = np.array(Image.open(path).convert("RGB"))
    r, g, b = WALL_RGB
    return (arr[:, :, 0] == r) & (arr[:, :, 1] == g) & (arr[:, :, 2] == b)


def hull_rim_mask(shape: tuple[int, int], inset: int = 96, wall: int = 36) -> np.ndarray:
    """Mask covering the outer hull rim only (the perimeter wall ring),
    not interior walls. Matches _ship_hull_rect() with default constants.
    """
    h, w = shape
    m = np.zeros((h, w), dtype=bool)
    # Outer rim band: between inset and inset+wall on each side.
    m[inset : inset + wall, inset : w - inset] = True             # top
    m[h - inset - wall : h - inset, inset : w - inset] = True     # bottom
    m[inset : h - inset, inset : inset + wall] = True             # left
    m[inset : h - inset, w - inset - wall : w - inset] = True     # right
    return m


def iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / float(union) if union else 0.0


def hull_bbox(path: Path) -> tuple[int, int, int, int, tuple[int, int]]:
    """Return (x0, y0, x1, y1, canvas_size) where (x0..x1, y0..y1) is the
    bounding box of all non-black pixels — the outer hull bbox.

    Pixels outside the hull are black (#000000); inside are wall / floor /
    windscreen / ramp / lighting. The bbox is what Foundry needs to align —
    if every deck has the same bbox, a token at coord (X, Y) maps to the
    same physical location on every deck.
    """
    arr = np.array(Image.open(path).convert("RGB"))
    non_black = (arr.sum(axis=2) > 0)
    ys, xs = np.where(non_black)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1, arr.shape[:2]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layouts", nargs="*", type=Path,
                    help="layout PNGs to verify (default: layouts/poc_ship-{bridge,engineering,barracks,cargo}.png)")
    ap.add_argument("--hull-inset", type=int, default=96,
                    help="hull inset for the hull-only bbox check (default: 96, matches SHIP_HULL_INSET)")
    args = ap.parse_args()

    if args.layouts:
        paths = [(p.stem, p) for p in args.layouts]
    else:
        paths = [(deck, HERE / "layouts" / f"poc_ship-{deck}.png") for deck in DECKS]

    bboxes: dict[str, tuple[int, int, int, int, tuple[int, int]]] = {}
    masks: dict[str, np.ndarray] = {}
    for label, p in paths:
        if not p.exists():
            print(f"missing: {p}", file=sys.stderr)
            return 1
        bboxes[label] = hull_bbox(p)
        masks[label] = wall_mask(p)
    deck_labels = [label for label, _ in paths]

    canvas_sizes = {deck: bb[4] for deck, bb in bboxes.items()}
    print("Canvas sizes (all must match for stack):")
    for label, sz in canvas_sizes.items():
        print(f"  {label:14} : {sz[1]}x{sz[0]}")
    canvases_match = len(set(canvas_sizes.values())) == 1
    print(f"  → {'OK' if canvases_match else 'FAIL'}: canvases {'identical' if canvases_match else 'differ'}")
    print()

    # Outer-hull bbox must be identical (same hull rect across decks).
    # ramp protrusions extend the bbox south on engineering/cargo so they
    # legitimately differ on that one edge. Test by reporting the bbox
    # ignoring south-edge differences.
    print("Outer-hull bounding box (XY range of non-black pixels):")
    for label, (x0, y0, x1, y1, _) in bboxes.items():
        print(f"  {label:14} : x={x0}..{x1}  y={y0}..{y1}  (w={x1-x0}, h={y1-y0})")
    # Hull body: take the min top and max-extent excluding the ramp protrusion.
    # The ramps extend the bbox south; the bridge's windscreen doesn't extend
    # past the hull edge. Compute hull bbox by masking ONLY the canonical
    # hull area (within HULL_INSET on all sides).
    print()
    print("Hull-only bbox (excluding ramp protrusions; should be identical):")
    HULL_INSET = args.hull_inset
    canvas_h, canvas_w = next(iter(bboxes.values()))[4]
    expected_bbox = (HULL_INSET, HULL_INSET, canvas_w - HULL_INSET, canvas_h - HULL_INSET)
    print(f"  expected (canvas {canvas_w}x{canvas_h}, inset={HULL_INSET}): x={expected_bbox[0]}..{expected_bbox[2]}  y={expected_bbox[1]}..{expected_bbox[3]}")
    all_hull_match = True
    for label, p in paths:
        arr = np.array(Image.open(p).convert("RGB"))
        h, w = arr.shape[:2]
        hull_only = arr.copy()
        hull_only[: HULL_INSET, :] = 0
        hull_only[h - HULL_INSET :, :] = 0
        hull_only[:, : HULL_INSET] = 0
        hull_only[:, w - HULL_INSET :] = 0
        non_black = (hull_only.sum(axis=2) > 0)
        if not non_black.any():
            bbox = (0, 0, 0, 0)
        else:
            ys, xs = np.where(non_black)
            bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        match = bbox == expected_bbox
        all_hull_match &= match
        marker = "OK  " if match else "FAIL"
        print(f"  {marker}  {label:14} : x={bbox[0]}..{bbox[2]}  y={bbox[1]}..{bbox[3]}")
    print()

    print("Interior-wall IoU diagnostic (informational; expected to differ per deck):")
    for a, b in combinations(deck_labels, 2):
        s = iou(masks[a], masks[b])
        print(f"  {a:14} ↔ {b:14} : {s:.4f}")
    print()

    if canvases_match and all_hull_match:
        print("✓ Decks stack pixel-perfect: identical canvas, identical hull bbox.")
        print("  Per-deck openings (windscreen / ramp) modify rim pixels intentionally.")
        return 0
    print("✗ Stack will misalign.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
