#!/usr/bin/env python3
"""
Slice grid images into individual stamps with transparent backgrounds.

Approach: sample the gutter color from the image border, build a mask of
"not gutter" pixels, then find connected components. Each sufficiently
large component is one stamp; its pixels become opaque, gutter pixels
become transparent. Robust to non-uniform cell sizes and broken/incomplete
gutter lines (a stamp that bleeds into a gutter is still a single component).

Output: ./stamps/<source-stem>_NN.png, numbered top-to-bottom, left-to-right.

Usage:
    python extract_stamps.py [image1.png image2.png ...]

If no arguments are given, processes every PNG in the current directory
(except files inside ./stamps/).
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

# Candidate tolerances tried per image; the one that yields the most
# valid-area components wins. A pixel is "gutter" if every channel is within
# tolerance of the sampled gutter color (median of the outer-frame pixels).
GUTTER_TOL_CANDIDATES = (16, 22, 30, 40, 55, 75)
# Minimum component area (pixels) to count as a stamp. Anything smaller is
# noise (stray bright dots inside a stamp, isolated grid junctions, etc.).
MIN_COMPONENT_AREA = 1500
# Minimum fraction of the component's bbox that must be opaque pixels.
# Real stamps fill 0.55-0.82 of their bbox in our reference data; grid-line
# networks that get accidentally captured as a single huge component fill
# ~0.01. A floor of 0.15 rejects gutter artifacts with massive headroom.
MIN_FILL_RATIO = 0.15
# Morphological closing radius applied to the non-gutter mask before labeling.
# Closing bridges hairline gaps in stamp outlines but ALSO merges adjacent
# stamps when gutters are only 1 px wide. Default off; rely on hole-filling
# (below) to reclaim gutter-colored pixels strictly inside a stamp.
CLOSING_RADIUS = 0
# After labeling, gutter regions strictly inside a stamp (not touching the
# image border AND smaller than MAX_HOLE_AREA) are filled in. The area cap
# stops the gutter "+" structure from being mis-classified as a hole when it
# happens not to reach a border pixel.
FILL_INTERIOR_HOLES = True
MAX_HOLE_AREA = 800
# Padding (px) around the component bbox in the output crop.
CROP_PADDING = 2
# Component sort order: ('row', 'col') groups by row bands first; rows are
# detected by clustering component centroid Y values.
ROW_CLUSTER_TOL_FRAC = 0.5  # cluster rows whose centroid-Y are within this
# fraction of the median component height of one another.


def sample_gutter_color(rgb: np.ndarray) -> np.ndarray:
    """Median color of a 4-pixel-wide frame around the image border."""
    h, w = rgb.shape[:2]
    f = 4
    frame = np.concatenate(
        [
            rgb[:f, :].reshape(-1, 3),
            rgb[-f:, :].reshape(-1, 3),
            rgb[:, :f].reshape(-1, 3),
            rgb[:, -f:].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(frame, axis=0).astype(np.int16)


def binary_dilate(mask: np.ndarray, iterations: int) -> np.ndarray:
    """8-connected binary dilation, `iterations` passes, pure numpy."""
    out = mask.copy()
    for _ in range(iterations):
        nxt = out.copy()
        nxt[1:, :] |= out[:-1, :]
        nxt[:-1, :] |= out[1:, :]
        nxt[:, 1:] |= out[:, :-1]
        nxt[:, :-1] |= out[:, 1:]
        nxt[1:, 1:] |= out[:-1, :-1]
        nxt[1:, :-1] |= out[:-1, 1:]
        nxt[:-1, 1:] |= out[1:, :-1]
        nxt[:-1, :-1] |= out[1:, 1:]
        out = nxt
    return out


def binary_erode(mask: np.ndarray, iterations: int) -> np.ndarray:
    return ~binary_dilate(~mask, iterations)


def build_stamp_mask(rgb: np.ndarray, tol: int) -> np.ndarray:
    """Boolean mask: True where the pixel is part of a stamp (not gutter)."""
    gutter = sample_gutter_color(rgb)
    diff = np.abs(rgb.astype(np.int16) - gutter)
    is_gutter = np.all(diff <= tol, axis=-1)
    stamp = ~is_gutter
    if CLOSING_RADIUS > 0:
        stamp = binary_dilate(stamp, CLOSING_RADIUS)
        stamp = binary_erode(stamp, CLOSING_RADIUS)
    return stamp


def score_tolerance(rgb: np.ndarray, tol: int) -> tuple[int, np.ndarray, np.ndarray, int]:
    """Try one tolerance value and return (score, mask, labels, n).

    Score is the count of components whose area is in the "stamp-plausible"
    range [MIN_COMPONENT_AREA, image_area / 4]. A larger oversized component
    (the whole image collapsed) does not count.
    """
    h, w = rgb.shape[:2]
    image_area = h * w
    max_area = image_area // 4
    mask = build_stamp_mask(rgb, tol)
    if FILL_INTERIOR_HOLES:
        mask = fill_interior_holes(mask)
    labels, n = label_components(mask)
    if n == 0:
        return 0, mask, labels, n
    areas = np.bincount(labels.ravel(), minlength=n + 1)
    valid = 0
    for lab in range(1, n + 1):
        a = int(areas[lab])
        if MIN_COMPONENT_AREA <= a <= max_area:
            valid += 1
    return valid, mask, labels, n


def pick_best_segmentation(rgb: np.ndarray) -> tuple[np.ndarray, int, int]:
    """Try every candidate tolerance, return (labels, n, chosen_tol)."""
    best: tuple[int, np.ndarray, int, int] | None = None  # (score, labels, n, tol)
    for tol in GUTTER_TOL_CANDIDATES:
        score, _mask, labels, n = score_tolerance(rgb, tol)
        if best is None or score > best[0]:
            best = (score, labels, n, tol)
    assert best is not None
    return best[1], best[2], best[3]


def label_components(mask: np.ndarray, connectivity: int = 4) -> tuple[np.ndarray, int]:
    """Connected-components labeling with `connectivity` 4 or 8.

    Labels are 1..n; 0 means background.
    4-connectivity is used by default for stamps so that diagonally-touching
    stamps at grid intersections do not merge through shared corners.
    """
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    if connectivity == 4:
        offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    else:
        offsets = (
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1),
        )
    next_label = 0
    ys, xs = np.where(mask)
    seen = labels  # alias: nonzero == visited
    for y, x in zip(ys.tolist(), xs.tolist()):
        if seen[y, x]:
            continue
        next_label += 1
        seen[y, x] = next_label
        q: deque[tuple[int, int]] = deque([(y, x)])
        while q:
            cy, cx = q.popleft()
            for dy, dx in offsets:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = next_label
                    q.append((ny, nx))
    return labels, next_label


def find_objects(labels: np.ndarray, n: int) -> list[tuple[int, int, int, int] | None]:
    """For each label 1..n, return (y0, x0, y1, x1) bounding box (exclusive) or None."""
    out: list[tuple[int, int, int, int] | None] = [None] * (n + 1)
    if n == 0:
        return out[1:]
    flat = labels.ravel()
    h, w = labels.shape
    nz = np.nonzero(flat)[0]
    if nz.size == 0:
        return out[1:]
    lbls = flat[nz]
    ys = nz // w
    xs = nz % w
    # Group by label using argsort.
    order = np.argsort(lbls, kind="stable")
    lbls_s = lbls[order]
    ys_s = ys[order]
    xs_s = xs[order]
    # Find boundaries between groups.
    boundaries = np.concatenate(
        ([0], np.nonzero(np.diff(lbls_s))[0] + 1, [lbls_s.size])
    )
    for i in range(len(boundaries) - 1):
        a, b = boundaries[i], boundaries[i + 1]
        lab = int(lbls_s[a])
        out[lab] = (
            int(ys_s[a:b].min()),
            int(xs_s[a:b].min()),
            int(ys_s[a:b].max()) + 1,
            int(xs_s[a:b].max()) + 1,
        )
    return out[1:]


def order_components(bboxes: list[tuple[int, int, int, int]]) -> list[int]:
    """Return indices sorted top-to-bottom in row bands, then left-to-right.

    Row bands are derived by clustering bbox vertical centers using a tolerance
    proportional to median component height — robust to slightly misaligned rows.
    """
    if not bboxes:
        return []
    centers_y = [(b[0] + b[2]) / 2 for b in bboxes]
    heights = [b[2] - b[0] for b in bboxes]
    median_h = float(np.median(heights)) if heights else 1.0
    tol = max(median_h * ROW_CLUSTER_TOL_FRAC, 1.0)

    order_by_y = sorted(range(len(bboxes)), key=lambda i: centers_y[i])
    rows: list[list[int]] = []
    for idx in order_by_y:
        if not rows or (centers_y[idx] - centers_y[rows[-1][-1]]) > tol:
            rows.append([idx])
        else:
            rows[-1].append(idx)
    out: list[int] = []
    for row in rows:
        row.sort(key=lambda i: bboxes[i][1])  # by left edge
        out.extend(row)
    return out


def fill_interior_holes(stamp_mask: np.ndarray) -> np.ndarray:
    """Return stamp_mask with gutter-region "holes" not touching the border filled.

    Any connected gutter region (cells where stamp_mask is False) that does not
    reach the image border is reassigned to True — those are interior holes
    surrounded by stamp pixels.
    """
    h, w = stamp_mask.shape
    bg = ~stamp_mask
    bg_labels, bn = label_components(bg, connectivity=8)
    if bn == 0:
        return stamp_mask
    # Find which background labels touch the border.
    border_labels = set()
    for v in bg_labels[0, :].tolist():
        border_labels.add(v)
    for v in bg_labels[-1, :].tolist():
        border_labels.add(v)
    for v in bg_labels[:, 0].tolist():
        border_labels.add(v)
    for v in bg_labels[:, -1].tolist():
        border_labels.add(v)
    border_labels.discard(0)
    bg_areas = np.bincount(bg_labels.ravel(), minlength=bn + 1)
    fill_label_set = {
        lab for lab in range(1, bn + 1)
        if lab not in border_labels and bg_areas[lab] <= MAX_HOLE_AREA
    }
    if not fill_label_set:
        return stamp_mask
    interior = np.isin(bg_labels, list(fill_label_set))
    return stamp_mask | interior


def process_image(path: Path, out_dir: Path) -> int:
    img = np.array(Image.open(path).convert("RGB"))
    h, w = img.shape[:2]
    labels, n, chosen_tol = pick_best_segmentation(img)
    if n == 0:
        print(f"[skip] {path.name}: no components found", file=sys.stderr)
        return 0

    # Collect bbox + area for each label, drop tiny ones.
    objects = find_objects(labels, n)
    # Areas via bincount over the full label image is much faster than
    # summing per-component slices.
    areas = np.bincount(labels.ravel(), minlength=n + 1)
    keep: list[tuple[int, tuple[int, int, int, int]]] = []  # (label, bbox)
    for label_idx in range(1, n + 1):
        bbox = objects[label_idx - 1]
        if bbox is None:
            continue
        if int(areas[label_idx]) < MIN_COMPONENT_AREA:
            continue
        y0, x0, y1, x1 = bbox
        bbox_area = (y1 - y0) * (x1 - x0)
        if bbox_area > 0 and (int(areas[label_idx]) / bbox_area) < MIN_FILL_RATIO:
            # Sparse component — almost certainly grid lines or another
            # network of thin features that got captured because their
            # color sat just outside the gutter tolerance.
            print(
                f"[reject] {path.name} label={label_idx}: "
                f"fill={int(areas[label_idx]) / bbox_area:.3f} < {MIN_FILL_RATIO}",
                file=sys.stderr,
            )
            continue
        keep.append((label_idx, bbox))

    if not keep:
        print(f"[skip] {path.name}: no components above min area", file=sys.stderr)
        return 0

    bboxes = [b for _, b in keep]
    order = order_components(bboxes)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    count = 0
    for out_idx, k in enumerate(order):
        label_idx, (y0, x0, y1, x1) = keep[k]
        py0 = max(y0 - CROP_PADDING, 0)
        px0 = max(x0 - CROP_PADDING, 0)
        py1 = min(y1 + CROP_PADDING, h)
        px1 = min(x1 + CROP_PADDING, w)

        crop_rgb = img[py0:py1, px0:px1]
        crop_label = labels[py0:py1, px0:px1]
        alpha = np.where(crop_label == label_idx, 255, 0).astype(np.uint8)
        rgba = np.dstack([crop_rgb, alpha])

        out_path = out_dir / f"{stem}_{out_idx:02d}.png"
        Image.fromarray(rgba, mode="RGBA").save(out_path)
        count += 1

    print(f"[ok] {path.name}: {count} stamps (tol={chosen_tol})")
    return count


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    campaign_root = here.parent.parent
    source_grids = campaign_root / ".ai-gen" / "cartography" / "source-grids"
    out_dir = campaign_root / ".ai-gen" / "cartography" / "stamps"

    if argv:
        targets = [Path(a) for a in argv]
    else:
        targets = sorted(source_grids.glob("*.png"))

    total = 0
    for p in targets:
        if not p.is_file():
            print(f"[skip] {p}: not a file", file=sys.stderr)
            continue
        total += process_image(p, out_dir)
    print(f"Done. Wrote {total} stamps to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
