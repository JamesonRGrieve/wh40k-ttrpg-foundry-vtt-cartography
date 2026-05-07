#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "opencv-python-headless"]
# ///
"""Canonical symbol compositor + validator.

The cartography pipeline does NOT trust diffusion to render Imperial
iconography. This module pastes canonical PNG masters from `symbols/`
onto generated images at named anchor points and validates that the
composited region matches the canonical via Canny-edge IoU.

Two interfaces:

1. **Library API** (used by stamp/portrait/scene generators):

       from symbol_compose import (
           load_symbol, compose_symbols, validate_symbol,
           SymbolPlacement, SymbolNotFoundError,
       )

       placements = [
           SymbolPlacement(name="aquila", x=512, y=128, size=256, lighting="lit"),
           SymbolPlacement(name="inquisition_i", x=480, y=420, size=128),
       ]
       composed = compose_symbols(base_image, placements)
       for p in placements:
           ok, score = validate_symbol(composed, p)
           if not ok:
               print(f"FLAG: {p.name} validation failed (IoU {score:.2f})")

2. **CLI** for ad-hoc operations:

       uv run symbol_compose.py validate aquila
       uv run symbol_compose.py validate-all
       uv run symbol_compose.py paste base.png --symbol aquila:512,128,256

Hard rules (per symbols/README.md):
- No silent fallback. Missing canonical = SymbolNotFoundError.
- No automated overwrite of the symbol library. This module is read-only.
- Honor metadata.json policies (rotation, mirror, aspect).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SYMBOLS_DIR = HERE / "symbols"


class SymbolNotFoundError(FileNotFoundError):
    pass


class SymbolPolicyError(ValueError):
    pass


@dataclass
class SymbolMetadata:
    name: str
    display_name: str
    default_size_px: int
    allowed_rotations: list[int]
    allowed_mirror: bool
    preserve_aspect: bool
    anchor_hints: list[str]
    validation_method: str
    validation_threshold: float
    notes: str = ""

    @classmethod
    def from_path(cls, json_path: Path) -> "SymbolMetadata":
        d = json.loads(json_path.read_text())
        v = d.get("validation", {})
        return cls(
            name=d["name"],
            display_name=d.get("display_name", d["name"]),
            default_size_px=int(d.get("default_size_px", 256)),
            allowed_rotations=list(d.get("allowed_rotations", [0])),
            allowed_mirror=bool(d.get("allowed_mirror", False)),
            preserve_aspect=bool(d.get("preserve_aspect", True)),
            anchor_hints=list(d.get("anchor_hints", [])),
            validation_method=str(v.get("method", "canny_iou")),
            validation_threshold=float(v.get("threshold", 0.85)),
            notes=str(d.get("notes", "")),
        )


@dataclass
class SymbolPlacement:
    """Where and how to paste a canonical onto a base image.

    `name`: matches a folder under `symbols/`.
    `x`, `y`: top-left corner in base-image pixel coords.
    `size`: edge length in px (canonical scaled to fit, preserving
        aspect when metadata says so).
    `rotation`: degrees; must be in metadata.allowed_rotations.
    `mirror`: horizontal flip; only allowed if metadata permits.
    `lighting`: optional variant suffix (e.g. "dim", "lit", "red").
        Resolves to `canonical_<lighting>.png`; falls back to
        `canonical.png` if the variant doesn't exist.
    """
    name: str
    x: int
    y: int
    size: int | None = None
    rotation: int = 0
    mirror: bool = False
    lighting: str | None = None


def load_symbol(name: str) -> tuple[SymbolMetadata, Image.Image]:
    """Load metadata + canonical.png. Raises SymbolNotFoundError if missing."""
    folder = SYMBOLS_DIR / name
    if not folder.is_dir():
        raise SymbolNotFoundError(f"symbol folder missing: {folder}")
    meta_path = folder / "metadata.json"
    if not meta_path.exists():
        raise SymbolNotFoundError(f"symbol metadata missing: {meta_path}")
    canon_path = folder / "canonical.png"
    if not canon_path.exists():
        raise SymbolNotFoundError(
            f"symbol master missing: {canon_path}\n"
            f"Operator must drop in canonical.png — see symbols/README.md."
        )
    meta = SymbolMetadata.from_path(meta_path)
    return meta, Image.open(canon_path).convert("RGBA")


def _resolve_canonical(name: str, lighting: str | None) -> Path:
    folder = SYMBOLS_DIR / name
    if lighting:
        candidate = folder / f"canonical_{lighting}.png"
        if candidate.exists():
            return candidate
    return folder / "canonical.png"


def _prepare_canonical(meta: SymbolMetadata, placement: SymbolPlacement) -> Image.Image:
    """Apply rotation, mirror, and resize per placement and policy."""
    if placement.rotation not in meta.allowed_rotations:
        raise SymbolPolicyError(
            f"rotation {placement.rotation}° not allowed for {meta.name!r}; "
            f"allowed: {meta.allowed_rotations}"
        )
    if placement.mirror and not meta.allowed_mirror:
        raise SymbolPolicyError(f"mirror not allowed for {meta.name!r}")

    canon_path = _resolve_canonical(meta.name, placement.lighting)
    if not canon_path.exists():
        raise SymbolNotFoundError(f"canonical missing: {canon_path}")
    im = Image.open(canon_path).convert("RGBA")

    if placement.mirror:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if placement.rotation:
        im = im.rotate(-placement.rotation, expand=True, resample=Image.BICUBIC)

    target = placement.size or meta.default_size_px
    if meta.preserve_aspect:
        w, h = im.size
        scale = target / max(w, h)
        new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    else:
        new_size = (target, target)
    im = im.resize(new_size, Image.LANCZOS)
    return im


def compose_symbols(base: Image.Image, placements: list[SymbolPlacement]) -> Image.Image:
    """Alpha-composite a list of canonical placements onto a base image.

    The base may be RGB or RGBA; output is always RGBA. Placements are
    applied in declaration order; a later placement overlays an earlier
    one if they overlap.
    """
    if not placements:
        return base.convert("RGBA")
    out = base.convert("RGBA").copy()
    for p in placements:
        meta, _ = load_symbol(p.name)
        canon = _prepare_canonical(meta, p)
        out.alpha_composite(canon, dest=(int(p.x), int(p.y)))
    return out


def _canny_edges(image: Image.Image, low: int = 80, high: int = 160) -> np.ndarray:
    import cv2
    arr = np.array(image.convert("L"))
    return cv2.Canny(arr, low, high)


def _canny_iou(a: Image.Image, b: Image.Image) -> float:
    """Intersection-over-union of binary Canny edge maps after dilation.

    Both images are first resized to the same dimensions; transparent
    backgrounds are flattened to white before edge detection so the
    silhouette of the symbol drives the comparison rather than the
    canvas color.
    """
    import cv2
    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)

    def flatten(im: Image.Image) -> Image.Image:
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im.convert("RGBA"))
        return bg.convert("RGB")

    ea = _canny_edges(flatten(a))
    eb = _canny_edges(flatten(b))
    # Light dilation absorbs single-pixel jitter from rotation/scaling.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    ea = cv2.dilate(ea, kernel, iterations=1) > 0
    eb = cv2.dilate(eb, kernel, iterations=1) > 0
    inter = np.logical_and(ea, eb).sum()
    union = np.logical_or(ea, eb).sum()
    if union == 0:
        return 0.0
    return float(inter) / float(union)


def validate_symbol(composed: Image.Image, placement: SymbolPlacement) -> tuple[bool, float]:
    """Crop the placement region and compare to the canonical.

    Returns (ok, score). `ok` is True iff score >= the symbol's
    metadata threshold.
    """
    meta, _ = load_symbol(placement.name)
    canon = _prepare_canonical(meta, placement)
    w, h = canon.size
    cropped = composed.crop((placement.x, placement.y, placement.x + w, placement.y + h))
    if meta.validation_method != "canny_iou":
        raise NotImplementedError(f"validation method {meta.validation_method!r}")
    score = _canny_iou(canon, cropped)
    return (score >= meta.validation_threshold), score


# --- CLI -------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    name = args.name
    try:
        meta, im = load_symbol(name)
    except SymbolNotFoundError as exc:
        print(f"[validate] {name}: MISSING — {exc}", file=sys.stderr)
        return 1
    issues: list[str] = []
    if im.mode != "RGBA":
        issues.append(f"canonical not RGBA (got {im.mode})")
    if "A" in im.mode:
        a = np.array(im.split()[-1])
        if a.max() == 255 and a.min() == 255:
            issues.append("canonical has no transparent pixels — flatten before commit?")
    if meta.allowed_rotations and 0 not in meta.allowed_rotations:
        issues.append("0° not in allowed_rotations — at least the identity must be allowed")
    print(f"[validate] {name}: {meta.display_name}")
    print(f"           size={im.size} default_target={meta.default_size_px} "
          f"rot={meta.allowed_rotations} mirror={meta.allowed_mirror} "
          f"thresh={meta.validation_threshold}")
    if issues:
        for issue in issues:
            print(f"           ISSUE: {issue}")
        return 1
    print("           OK")
    return 0


def cmd_validate_all(args: argparse.Namespace) -> int:
    # Skip leading-underscore folders (e.g. _source/ holds upstream
    # SVG masters and license docs, not symbol data).
    names = sorted(
        p.name for p in SYMBOLS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )
    if not names:
        print("no symbols found", file=sys.stderr)
        return 1
    rc = 0
    for name in names:
        sub = argparse.Namespace(name=name)
        if cmd_validate(sub) != 0:
            rc = 1
    return rc


def _parse_paste_spec(spec: str) -> SymbolPlacement:
    if ":" not in spec:
        raise argparse.ArgumentTypeError(f"--symbol expects NAME:x,y[,size], got {spec!r}")
    name, body = spec.split(":", 1)
    parts = [p.strip() for p in body.split(",") if p.strip()]
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(f"--symbol body needs at least x,y; got {spec!r}")
    x = int(parts[0])
    y = int(parts[1])
    size = int(parts[2]) if len(parts) >= 3 else None
    return SymbolPlacement(name=name, x=x, y=y, size=size)


def cmd_paste(args: argparse.Namespace) -> int:
    base = Image.open(args.base)
    placements = list(args.symbol)
    out = compose_symbols(base, placements)
    out.save(args.output)
    print(f"[paste] wrote {args.output} ({len(placements)} symbols)")
    if args.validate:
        for p in placements:
            ok, score = validate_symbol(out, p)
            tag = "OK" if ok else "FLAG"
            print(f"[validate] {p.name}@({p.x},{p.y}): {tag} (IoU {score:.3f})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("validate", help="sanity-check one symbol's canonical + metadata")
    pv.add_argument("name")
    pv.set_defaults(func=cmd_validate)

    pva = sub.add_parser("validate-all", help="sanity-check every symbol in the library")
    pva.set_defaults(func=cmd_validate_all)

    pp = sub.add_parser("paste", help="paste one or more canonicals onto a base image (test driver)")
    pp.add_argument("base", type=Path)
    pp.add_argument("--output", type=Path, required=True)
    pp.add_argument("--symbol", action="append", required=True, type=_parse_paste_spec,
                    metavar="NAME:x,y[,size]",
                    help="symbol placement; repeat for multiple symbols")
    pp.add_argument("--validate", action="store_true", help="run canny-IoU validation after paste")
    pp.set_defaults(func=cmd_paste)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
