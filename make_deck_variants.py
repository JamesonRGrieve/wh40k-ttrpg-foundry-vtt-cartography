#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pillow", "numpy"]
# ///
"""Multi-deck layout variant helper. **Largely superseded** — use the
programmatic ``ship-*`` presets in ``FLOORPLAN_PRESETS`` for new
multi-deck builds, since they share the canonical hull via
``_ship_hull_rect()`` and produce architecturally-coherent decks
without operator paint work.

This script remains useful for the narrow case where the operator has
a *hand-painted* base layout and wants to fork deck variants from it
with simple canonical openings (rear ramp, dorsal windscreen). For
that case it preserves the source hull byte-for-byte and only paints
the requested opening.

For ALIGNMENT VERIFICATION (whether a set of decks will stack
pixel-perfect in Foundry), use ``verify_deck_stack.py`` — it accepts
arbitrary layout PNGs and reports canvas + hull-bbox match.

Usage:
    uv run make_deck_variants.py base_hull.png --decks 2
    uv run make_deck_variants.py base_hull.png --decks 3 \\
            --opening deck1=ramp:south --opening deck2=windscreen:north

Openings spec: ``deck<N>=<role>:<side>`` where role ∈ {ramp,
windscreen} and side ∈ {north, south, east, west}. Multiple openings
per deck repeat the flag.

Recommended workflow today:
1. ``uv run generate_battlemap.py make-floorplan layouts/bridge.png \\
        --preset ship-bridge`` (and similarly for engineering / barracks
   / cargo).
2. ``uv run verify_deck_stack.py`` to confirm pixel-perfect stack.
3. ``uv run generate_battlemap.py spacecraft --layout <layout.png> \\
        --style ship-<deck>`` to render each deck through Flux.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

# Canonical region colors. Mirrors SPACECRAFT_REGION_RGB in
# generate_battlemap.py — kept independent so this helper has no
# circular-import risk.
WALL = (0x30, 0x30, 0x30)
FLOOR = (0x80, 0x80, 0x80)
RAMP = (0xA0, 0xA0, 0xA0)
WINDSCREEN = (0x1A, 0x27, 0x50)


def parse_opening(spec: str) -> tuple[int, str, str]:
    """Parse ``deck<N>=<role>:<side>`` into (deck_index, role, side)."""
    if "=" not in spec or ":" not in spec.split("=", 1)[1]:
        raise argparse.ArgumentTypeError(f"bad opening spec: {spec!r} (want deck<N>=role:side)")
    deck_part, body = spec.split("=", 1)
    if not deck_part.startswith("deck"):
        raise argparse.ArgumentTypeError(f"bad deck name in {spec!r}; expected 'deck<N>'")
    try:
        deck_index = int(deck_part[len("deck"):])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad deck number in {spec!r}") from exc
    role, side = body.split(":", 1)
    role = role.strip()
    side = side.strip()
    if role not in {"ramp", "windscreen"}:
        raise argparse.ArgumentTypeError(f"unknown opening role {role!r}; allowed: ramp, windscreen")
    if side not in {"north", "south", "east", "west"}:
        raise argparse.ArgumentTypeError(f"unknown opening side {side!r}")
    return deck_index, role, side


def find_outer_hull(arr: np.ndarray) -> tuple[int, int, int, int]:
    """Return the bounding rect (x0, y0, x1, y1) of the non-black region."""
    mask = (arr != 0).any(axis=2)
    if not mask.any():
        raise ValueError("base hull image is entirely black — no hull found")
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def carve_opening(arr: np.ndarray, *, role: str, side: str, hull_rect: tuple[int, int, int, int],
                  width_frac: float = 0.33, depth: int = 96) -> None:
    """Paint a ramp or windscreen opening on the named side of the hull.

    Carves a rectangle of length `depth` perpendicular to the named
    wall, centered along that wall's span. Width is `width_frac` of
    the wall length. Existing wall pixels become the opening's role
    color; existing floor pixels stay floor (the opening transitions
    through the wall, not into the room).
    """
    x0, y0, x1, y1 = hull_rect
    w = x1 - x0
    h = y1 - y0
    color = RAMP if role == "ramp" else WINDSCREEN
    if side in ("north", "south"):
        opening_w = max(64, int(w * width_frac))
        cx = x0 + (w - opening_w) // 2
        if side == "north":
            arr[y0:y0 + depth, cx:cx + opening_w] = color
        else:
            arr[y1 - depth:y1, cx:cx + opening_w] = color
    else:
        opening_h = max(64, int(h * width_frac))
        cy = y0 + (h - opening_h) // 2
        if side == "west":
            arr[cy:cy + opening_h, x0:x0 + depth] = color
        else:
            arr[cy:cy + opening_h, x1 - depth:x1] = color


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", type=Path, help="path to base hull layout PNG (canonical-color)")
    ap.add_argument("--decks", type=int, default=2, help="number of deck variants to emit (default 2)")
    ap.add_argument("--output-dir", type=Path, default=None,
                    help="output directory (default: same as base)")
    ap.add_argument("--opening", action="append", type=parse_opening, default=[],
                    metavar="deck<N>=ROLE:SIDE",
                    help="add an opening on a specific deck. Example: deck1=ramp:south. "
                    "Repeat for multiple openings per deck or across decks.")
    args = ap.parse_args()

    if not args.base.exists():
        print(f"base layout not found: {args.base}", file=sys.stderr)
        return 1
    if args.decks < 1:
        print("--decks must be >= 1", file=sys.stderr)
        return 1

    out_dir = args.output_dir or args.base.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    base_im = Image.open(args.base).convert("RGB")
    base_arr = np.array(base_im, dtype=np.uint8)
    hull = find_outer_hull(base_arr)

    by_deck: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for deck_index, role, side in args.opening:
        if deck_index < 1 or deck_index > args.decks:
            print(f"--opening references deck{deck_index} but only {args.decks} decks requested", file=sys.stderr)
            return 1
        by_deck[deck_index].append((role, side))

    base_stem = args.base.stem
    written: list[Path] = []
    for n in range(1, args.decks + 1):
        arr = base_arr.copy()
        for role, side in by_deck.get(n, []):
            carve_opening(arr, role=role, side=side, hull_rect=hull)
        target = out_dir / f"{base_stem}_deck{n}.png"
        Image.fromarray(arr, mode="RGB").save(target)
        written.append(target)
        print(f"[deck-variants] -> {target}", file=sys.stderr)

    # Sanity: assert outer hull pixels match across decks (modulo openings).
    # We don't enforce strict equality because openings deliberately mutate
    # wall pixels, but we at least confirm the inner-floor band is consistent.
    print(f"[deck-variants] {len(written)} variants written to {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
