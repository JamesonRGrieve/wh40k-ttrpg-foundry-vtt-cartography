#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "Pillow",
#   "numpy",
# ]
# ///
"""Convert a Dungeondraft Universal VTT export into a canonical
region-color layout PNG for the `spacecraft` regional-conditioning
battlemap workflow (goal #10 — external layout ingestion).

Why this exists
---------------
A raw canny / lineart ControlNet has zero semantics: it reproduces
lines but does not know a gap is a door or a glyph is stairs. The
Universal VTT (`.dd2vtt`) export already carries the semantics as
labelled vector geometry — walls (`line_of_sight`), portals
(doors + windows), and lights — so we convert that JSON directly into
the five canonical region colors the saved `BattlemapSpacecraft.json`
workflow conditions on, rather than asking a model to re-derive
structure from a flattened picture.

    .dd2vtt JSON ─► dd2vtt_to_layout.py ─► <stem>.png (region colors)
                                        ─► <stem>.placements.json
                                            (door + light coordinates)

The region PNG feeds `generate_battlemap.py spacecraft --layout <stem>.png`.

Door / light handling
---------------------
Doors are INTERACTIVE (they open and close), so per the
architecture/tile-layer rule they do not get painted as a base-map
region by default — they are carved as floor-colored openings in the
wall, and their pixel coordinates are written to the placements
sidecar so the operator can auto-place door tiles on Foundry's tile
layer. Lights likewise: the base map gets a canonical lighting region
disc, and the sidecar records the source coordinate / range / color
for placing lumen tiles. Override door treatment with `--door-as`.

Hard edges, no anti-aliasing
----------------------------
The spacecraft workflow matches region colors EXACTLY; anti-aliased
edges between regions fall through to the unmasked base prompt
(CLAUDE.md gotcha #11). Everything here is drawn aliased and never
resized, and a final palette-conformance check fails loudly if any
out-of-gamut pixel slipped in.

Coordinate model
----------------
UVTT geometry is in GRID units. Pixels = (coord - map_origin) * ppg.
Image size = map_size * pixels_per_grid. Origin is top-left, y down.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Single source of truth for the canonical region palette. Importing the
# driver is side-effect-free (it is guarded by `if __name__ == "__main__"`).
from generate_battlemap import SPACECRAFT_REGION_RGB  # noqa: E402

WALL = SPACECRAFT_REGION_RGB["wall"]
FLOOR = SPACECRAFT_REGION_RGB["floor"]
RAMP = SPACECRAFT_REGION_RGB["ramp"]
LIGHTING = SPACECRAFT_REGION_RGB["lighting"]

# Optional dedicated door color for --door-as door. NOT one of the five
# conditioned roles — the saved workflow has no door node, so a region in
# this color falls through to the base prompt. Provided for a future
# workflow that adds a door node; documented in goal #10.
DOOR = (0x6B, 0x4A, 0x2B)

# Palette permitted in the output, keyed by --door-as choice.
def _allowed_palette(door_as: str) -> set[tuple[int, int, int]]:
    base = {WALL, FLOOR, RAMP, LIGHTING}
    if door_as == "door":
        base.add(DOOR)
    return base


# --- UVTT parsing ----------------------------------------------------------


def _pt(d: dict[str, Any]) -> tuple[float, float]:
    return float(d["x"]), float(d["y"])


def _polylines(raw: Any) -> list[list[tuple[float, float]]]:
    """Normalize a line_of_sight value to a list of polylines.

    Dungeondraft emits an array of polylines (each a list of {x,y}).
    Some legacy exports emit a single flat list of {x,y}. Handle both.
    """
    if not raw:
        return []
    first = raw[0]
    if isinstance(first, dict):  # flat single polyline
        return [[_pt(p) for p in raw]]
    return [[_pt(p) for p in line] for line in raw if line]


def load_uvtt(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    res = data.get("resolution", {})
    ppg = int(round(float(res.get("pixels_per_grid", 100))))
    map_size = res.get("map_size", {})
    origin = res.get("map_origin", {}) or {}
    ox, oy = float(origin.get("x", 0.0)), float(origin.get("y", 0.0))

    if not map_size:
        raise ValueError(
            f"{path.name}: resolution.map_size missing — not a valid UVTT export"
        )

    walls = _polylines(data.get("line_of_sight"))
    walls += _polylines(data.get("objects_line_of_sight"))

    portals = []
    for p in data.get("portals", []) or []:
        pos = p.get("position", {})
        bounds = [_pt(b) for b in p.get("bounds", []) if isinstance(b, dict)]
        portals.append(
            {
                "pos": _pt(pos) if pos else (None, None),
                "bounds": bounds,
                "rotation": float(p.get("rotation", 0.0)),
                "closed": bool(p.get("closed", True)),
                "freestanding": bool(p.get("freestanding", False)),
            }
        )

    lights = []
    for lt in data.get("lights", []) or []:
        pos = lt.get("position", {})
        lights.append(
            {
                "pos": _pt(pos) if pos else (None, None),
                "range": float(lt.get("range", 0.0)),
                "intensity": float(lt.get("intensity", 1.0)),
                "color": str(lt.get("color", "ffffffff")),
            }
        )

    return {
        "ppg": ppg,
        "grid_w": float(map_size["x"]),
        "grid_h": float(map_size["y"]),
        "origin": (ox, oy),
        "walls": walls,
        "portals": portals,
        "lights": lights,
        "image_b64": data.get("image"),
    }


# --- Rasterization ---------------------------------------------------------


def convert(
    uvtt: dict[str, Any],
    *,
    wall_grid_frac: float,
    light_grid_frac: float,
    door_as: str,
) -> tuple[Image.Image, dict[str, Any]]:
    ppg = uvtt["ppg"]
    ox, oy = uvtt["origin"]
    width = int(round(uvtt["grid_w"] * ppg))
    height = int(round(uvtt["grid_h"] * ppg))
    if width <= 0 or height <= 0:
        raise ValueError(f"degenerate canvas {width}x{height}")

    wall_px = max(2, int(round(ppg * wall_grid_frac)))
    light_px = max(2, int(round(ppg * light_grid_frac)))
    join_r = wall_px // 2

    def to_px(x: float, y: float) -> tuple[float, float]:
        return (x - ox) * ppg, (y - oy) * ppg

    # Whole canvas is walkable floor; everything else is painted on top.
    img = Image.new("RGB", (width, height), FLOOR)
    draw = ImageDraw.Draw(img)  # aliased by default — do not switch to RGBA

    # Walls: thick aliased polylines with filled round joints so corners
    # stay contiguous (no gap pixels that would fall through to base prompt).
    for line in uvtt["walls"]:
        pts = [to_px(x, y) for x, y in line]
        if len(pts) >= 2:
            draw.line(pts, fill=WALL, width=wall_px, joint="curve")
        for cx, cy in pts:
            draw.ellipse(
                [cx - join_r, cy - join_r, cx + join_r, cy + join_r], fill=WALL
            )

    # Lights: canonical lighting-color disc at each source.
    for lt in uvtt["lights"]:
        if lt["pos"][0] is None:
            continue
        cx, cy = to_px(*lt["pos"])
        draw.ellipse(
            [cx - light_px, cy - light_px, cx + light_px, cy + light_px],
            fill=LIGHTING,
        )

    # Portals (doors/windows). Default: carve a floor-colored opening across
    # the door span (slightly wider than the wall so the wall is fully
    # cleared) — the doorway is architecture, the door leaf is a tile.
    carve_px = int(round(wall_px * 1.5))
    door_fill = {"wall-gap": FLOOR, "ramp": RAMP, "door": DOOR}[door_as]
    for p in uvtt["portals"]:
        span = [to_px(x, y) for x, y in p["bounds"]]
        if len(span) >= 2:
            draw.line(span, fill=door_fill, width=carve_px, joint="curve")
        elif p["pos"][0] is not None:
            cx, cy = to_px(*p["pos"])
            r = carve_px // 2
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=door_fill)

    # Palette conformance guard (gotcha #11): no AA / out-of-gamut pixels.
    allowed = _allowed_palette(door_as)
    colors = img.getcolors(maxcolors=1 << 24)
    if colors is None:
        raise RuntimeError(
            "output has >16M distinct colors — anti-aliasing leaked somewhere"
        )
    stray = {rgb for _, rgb in colors} - allowed
    if stray:
        raise RuntimeError(
            f"output contains {len(stray)} out-of-gamut color(s) that will "
            f"fall through to the base prompt: {sorted(stray)[:5]}"
        )

    # Placement sidecar — door + light coordinates in PIXEL space, for
    # auto-placing interactive tiles on the Foundry tile layer.
    placements = {
        "image_size": [width, height],
        "pixels_per_grid": ppg,
        "doors": [
            {
                "x": round(to_px(*p["pos"])[0], 2) if p["pos"][0] is not None else None,
                "y": round(to_px(*p["pos"])[1], 2) if p["pos"][0] is not None else None,
                "rotation_deg": round(p["rotation"], 2),
                "closed": p["closed"],
                "freestanding": p["freestanding"],
                "span_px": [[round(x, 2), round(y, 2)] for x, y in
                            (to_px(a, b) for a, b in p["bounds"])],
            }
            for p in uvtt["portals"]
        ],
        "lights": [
            {
                "x": round(to_px(*lt["pos"])[0], 2),
                "y": round(to_px(*lt["pos"])[1], 2),
                "range_px": round(lt["range"] * ppg, 2),
                "intensity": lt["intensity"],
                "color": lt["color"][-6:],  # drop ARGB alpha if present
            }
            for lt in uvtt["lights"]
            if lt["pos"][0] is not None
        ],
    }
    return img, placements


def _decode_source_image(b64: str | None) -> Image.Image | None:
    if not b64:
        return None
    return Image.open(io.BytesIO(base64.b64decode(b64)))


# --- Self-test -------------------------------------------------------------


def _self_test() -> int:
    """Synthesize a minimal UVTT (one room, one door, one light) and verify
    the conversion end-to-end without needing a real Dungeondraft export."""
    ppg = 100
    doc = {
        "format": 0.3,
        "resolution": {
            "map_origin": {"x": 0, "y": 0},
            "map_size": {"x": 6, "y": 4},
            "pixels_per_grid": ppg,
        },
        # Rectangular wall loop inset 1 grid from each edge.
        "line_of_sight": [
            [
                {"x": 1, "y": 1},
                {"x": 5, "y": 1},
                {"x": 5, "y": 3},
                {"x": 1, "y": 3},
                {"x": 1, "y": 1},
            ]
        ],
        "portals": [
            {
                "position": {"x": 3, "y": 1},
                "bounds": [{"x": 2.5, "y": 1}, {"x": 3.5, "y": 1}],
                "rotation": 0.0,
                "closed": True,
                "freestanding": False,
            }
        ],
        "lights": [
            {"position": {"x": 3, "y": 2}, "range": 4.0, "intensity": 1.0,
             "color": "ffffd9a0"}
        ],
    }
    tmp = HERE / "_selftest.dd2vtt"
    tmp.write_text(json.dumps(doc))
    try:
        uvtt = load_uvtt(tmp)
        img, placements = convert(
            uvtt, wall_grid_frac=0.2, light_grid_frac=0.12, door_as="wall-gap"
        )
    finally:
        tmp.unlink(missing_ok=True)

    checks: list[tuple[str, bool]] = []
    checks.append(("image size 600x400", img.size == (6 * ppg, 4 * ppg)))
    present = {rgb for _, rgb in img.getcolors(maxcolors=1 << 24)}
    checks.append(("wall pixels present", WALL in present))
    checks.append(("floor pixels present", FLOOR in present))
    checks.append(("lighting pixels present", LIGHTING in present))
    checks.append(("no door region painted (wall-gap)", DOOR not in present))
    checks.append(("1 door recorded", len(placements["doors"]) == 1))
    checks.append(("1 light recorded", len(placements["lights"]) == 1))
    checks.append(
        ("light color alpha stripped", placements["lights"][0]["color"] == "ffd9a0")
    )
    # Door span midpoint should be carved back to floor at the top wall.
    mid = img.getpixel((300, 100))
    checks.append(("door carved to floor at opening", mid == FLOOR))

    ok = all(passed for _, passed in checks)
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# --- CLI -------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "input", type=Path, nargs="?",
        help="path to the .dd2vtt / .uvtt / .df2vtt export",
    )
    ap.add_argument(
        "-o", "--output", type=Path,
        help="output region PNG path (default: <input-stem>.png)",
    )
    ap.add_argument(
        "--door-as", choices=["wall-gap", "ramp", "door"], default="wall-gap",
        help="how to render portals: 'wall-gap' (default, carve a floor "
        "opening — door leaf goes on the tile layer), 'ramp' (paint the "
        "threshold as ramp), or 'door' (dedicated door color; needs a "
        "workflow door node or it falls through to the base prompt)",
    )
    ap.add_argument(
        "--wall-grid-frac", type=float, default=0.2,
        help="wall thickness as a fraction of one grid cell (default 0.2)",
    )
    ap.add_argument(
        "--light-grid-frac", type=float, default=0.12,
        help="lighting disc radius as a fraction of one grid cell (default 0.12)",
    )
    ap.add_argument(
        "--emit-source-image", action="store_true",
        help="also write the Dungeondraft render embedded in the export to "
        "<stem>.source.png (e.g. for side-by-side comparison)",
    )
    ap.add_argument(
        "--self-test", action="store_true",
        help="run the built-in conversion self-test and exit",
    )
    args = ap.parse_args()

    if args.self_test:
        return _self_test()
    if args.input is None:
        ap.error("input is required (or pass --self-test)")
    if not args.input.exists():
        ap.error(f"no such file: {args.input}")

    uvtt = load_uvtt(args.input)
    img, placements = convert(
        uvtt,
        wall_grid_frac=args.wall_grid_frac,
        light_grid_frac=args.light_grid_frac,
        door_as=args.door_as,
    )
    placements["source"] = args.input.name

    out = args.output or args.input.with_suffix(".png")
    img.save(out)
    side = out.with_suffix(".placements.json")
    side.write_text(json.dumps(placements, indent=2))

    print(f"[dd2vtt] {args.input.name} -> {out.name}", file=sys.stderr)
    print(
        f"[dd2vtt] {img.size[0]}x{img.size[1]} px @ {uvtt['ppg']}/grid, "
        f"{len(uvtt['walls'])} wall polylines, "
        f"{len(placements['doors'])} doors, {len(placements['lights'])} lights "
        f"-> {side.name}",
        file=sys.stderr,
    )

    if args.emit_source_image:
        src = _decode_source_image(uvtt["image_b64"])
        if src is None:
            print("[dd2vtt] no embedded image in export; skipping --emit-source-image",
                  file=sys.stderr)
        else:
            sp = out.with_suffix(".source.png")
            src.save(sp)
            print(f"[dd2vtt] embedded render -> {sp.name}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
