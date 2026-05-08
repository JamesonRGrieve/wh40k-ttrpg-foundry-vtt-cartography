#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "PyYAML"]
# ///
"""Wide-scale overlay layers for strategic battlemaps.

Wide-scale renders (district / region / planet / system) often need
operator-controlled overlays — hex grids for travel reckoning,
faction-control color tints, jurisdiction zones, fleet-movement
vectors. This helper produces transparent PNGs at the same dimensions
as the underlying base render, ready to drop into Foundry as a
foreground tile (or composited via `generate_battlemap.py compose`).

Subcommands:

  hex          — hex grid overlay (size, colour, opacity, axial labels)
  zones        — faction/jurisdiction zones from a polygon spec
  fleet        — arrow vectors between named points
  compass      — N/E/S/W rose at a chosen anchor (rendered as a
                 small stamp-shaped element on top of an existing map)

Each subcommand writes a transparent-bg PNG and prints the path.
The overlay matches the base render's dimensions so it composites
pixel-perfect on top.

Usage:

    uv run make_overlay.py hex \\
        --width 1024 --height 1024 --grid 64 \\
        --color 'D4B260' --opacity 0.4 \\
        --output overlays/system_hex.png

    uv run make_overlay.py zones zones.yaml \\
        --width 1024 --height 1024 \\
        --output overlays/region_jurisdiction.png

    uv run make_overlay.py fleet fleet.yaml \\
        --width 1024 --height 1024 \\
        --output overlays/region_fleet.png

The output composites cleanly over a base render via:
    uv run generate_battlemap.py compose base.png overlays/<name>.png \\
        --output composed.png
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent


def parse_hex_color(s: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    """Parse '#RRGGBB' or 'RRGGBB' to (r,g,b,a) with alpha = opacity * 255."""
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError(f"--color must be 6 hex chars, got {s!r}")
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    a = max(0, min(255, int(round(opacity * 255))))
    return (r, g, b, a)


# --- hex grid -----------------------------------------------------------------


def _flat_hex_vertices(cx: float, cy: float, size: float) -> list[tuple[float, float]]:
    """Vertex coords for a flat-top hexagon centered at (cx, cy)."""
    return [
        (cx + size * math.cos(math.radians(60 * i)),
         cy + size * math.sin(math.radians(60 * i)))
        for i in range(6)
    ]


def cmd_hex(args: argparse.Namespace) -> int:
    """Hex grid overlay. `--grid` is the hexagon edge length in px."""
    rgba = parse_hex_color(args.color, args.opacity)
    canvas = Image.new("RGBA", (args.width, args.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    size = float(args.grid)
    # Flat-top hex spacing: dx = 1.5 * size, dy = sqrt(3) * size; rows offset.
    dx = 1.5 * size
    dy = math.sqrt(3) * size

    # Iterate over column/row indices wide enough to cover the canvas.
    cols = int(args.width / dx) + 3
    rows = int(args.height / dy) + 3
    for col in range(-1, cols):
        for row in range(-1, rows):
            cx = col * dx
            cy = row * dy + (dy / 2 if col % 2 else 0)
            vertices = _flat_hex_vertices(cx, cy, size)
            draw.polygon(vertices, outline=rgba, width=max(1, args.line_width))
            if args.labels:
                # Axial coordinate labels at the hex center.
                # Convert (col, row) to axial (q, r) — flat-top offset.
                q = col
                r = row - (col - (col & 1)) // 2
                label = f"{q},{r}"
                draw.text((cx - 12, cy - 6), label, fill=rgba)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output)
    print(f"[hex] {args.width}x{args.height} grid={args.grid} color={args.color} -> {args.output}",
          file=sys.stderr)
    return 0


# --- zones --------------------------------------------------------------------


def cmd_zones(args: argparse.Namespace) -> int:
    """Faction/jurisdiction zones from a polygon YAML spec.

    Spec format:
        zones:
          - name: "Inquisitorial Cordon"
            color: "#7A1212"
            opacity: 0.35
            polygon: [[100, 100], [400, 100], [400, 300], [100, 300]]
            label_pos: [250, 200]
          - name: "PDF Patrol Zone"
            color: "#506830"
            opacity: 0.28
            polygon: [[400, 100], [800, 100], [800, 600], [400, 600]]

    Polygons are filled with the named color at the named opacity; an
    optional darker outline is drawn at the zone's boundary.
    """
    spec = yaml.safe_load(args.spec.read_text())
    zones = spec.get("zones", [])
    canvas = Image.new("RGBA", (args.width, args.height), (0, 0, 0, 0))

    for z in zones:
        color = z.get("color", "#FFFFFF")
        opacity = float(z.get("opacity", 0.3))
        rgba_fill = parse_hex_color(color, opacity)
        rgba_edge = parse_hex_color(color, min(1.0, opacity * 2.5))
        polygon = [(float(x), float(y)) for x, y in z["polygon"]]

        # Draw on a per-zone layer so we can alpha-composite cleanly.
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        ldraw.polygon(polygon, fill=rgba_fill, outline=rgba_edge, width=3)

        # Optional zone label
        label = z.get("name")
        label_pos = z.get("label_pos")
        if label and label_pos:
            ldraw.text((float(label_pos[0]), float(label_pos[1])), str(label), fill=rgba_edge)

        canvas = Image.alpha_composite(canvas, layer)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output)
    print(f"[zones] {args.width}x{args.height} zones={len(zones)} -> {args.output}",
          file=sys.stderr)
    return 0


# --- fleet vectors ------------------------------------------------------------


def _arrowhead(draw: ImageDraw.ImageDraw, p0: tuple[float, float], p1: tuple[float, float],
               *, color: tuple[int, int, int, int], head_size: int = 14) -> None:
    """Draw an arrowhead at p1 pointing along the line from p0->p1."""
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    angle = math.atan2(dy, dx)
    left = (p1[0] - head_size * math.cos(angle - math.radians(28)),
            p1[1] - head_size * math.sin(angle - math.radians(28)))
    right = (p1[0] - head_size * math.cos(angle + math.radians(28)),
             p1[1] - head_size * math.sin(angle + math.radians(28)))
    draw.polygon([p1, left, right], fill=color)


def cmd_fleet(args: argparse.Namespace) -> int:
    """Fleet movement arrow overlay from a YAML spec.

    Spec format:
        arrows:
          - from: [120, 480]
            to:   [820, 220]
            color: "#D4B260"
            opacity: 0.85
            label: "Imperial Navy 2nd Squadron"
          - from: [400, 800]
            to:   [400, 200]
            color: "#7A1212"
            opacity: 0.85
    """
    spec = yaml.safe_load(args.spec.read_text())
    arrows = spec.get("arrows", [])
    canvas = Image.new("RGBA", (args.width, args.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    for a in arrows:
        color = a.get("color", "#FFFFFF")
        opacity = float(a.get("opacity", 0.85))
        rgba = parse_hex_color(color, opacity)
        p0 = tuple(float(v) for v in a["from"])
        p1 = tuple(float(v) for v in a["to"])
        width = int(a.get("line_width", 4))
        draw.line([p0, p1], fill=rgba, width=width)
        _arrowhead(draw, p0, p1, color=rgba, head_size=int(a.get("head_size", 16)))
        label = a.get("label")
        if label:
            mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            draw.text((mid[0] + 6, mid[1] - 14), str(label), fill=rgba)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output)
    print(f"[fleet] {args.width}x{args.height} arrows={len(arrows)} -> {args.output}",
          file=sys.stderr)
    return 0


# --- compass rose -------------------------------------------------------------


def cmd_compass(args: argparse.Namespace) -> int:
    """Tiny compass rose at a named anchor on the canvas."""
    rgba = parse_hex_color(args.color, args.opacity)
    canvas = Image.new("RGBA", (args.width, args.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    cx = args.cx if args.cx is not None else args.width - 80
    cy = args.cy if args.cy is not None else args.height - 80
    r = args.radius

    # Outer circle.
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba, width=2)
    # Cardinal arms.
    for dx, dy, label in [(0, -1, "N"), (1, 0, "E"), (0, 1, "S"), (-1, 0, "W")]:
        px = cx + dx * r
        py = cy + dy * r
        draw.line([(cx, cy), (px, py)], fill=rgba, width=2)
        # Label slightly outside the circle.
        draw.text((cx + dx * (r + 8) - 4, cy + dy * (r + 8) - 6), label, fill=rgba)
    # Centerpoint.
    draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=rgba)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output)
    print(f"[compass] {args.width}x{args.height} center=({cx},{cy}) r={r} -> {args.output}",
          file=sys.stderr)
    return 0


# --- CLI ---------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    common_dim = lambda p: (
        p.add_argument("--width", type=int, required=True),
        p.add_argument("--height", type=int, required=True),
        p.add_argument("--output", type=Path, required=True),
    )

    ph = sub.add_parser("hex", help="hex grid overlay")
    common_dim(ph)
    ph.add_argument("--grid", type=int, default=64, help="hexagon edge length in px")
    ph.add_argument("--color", default="D4B260", help="hex color, e.g. 'D4B260'")
    ph.add_argument("--opacity", type=float, default=0.4)
    ph.add_argument("--line-width", type=int, default=2)
    ph.add_argument("--labels", action="store_true", help="render axial coord labels per hex")
    ph.set_defaults(func=cmd_hex)

    pz = sub.add_parser("zones", help="faction/jurisdiction zones from a YAML polygon spec")
    pz.add_argument("spec", type=Path, help="path to zones YAML")
    common_dim(pz)
    pz.set_defaults(func=cmd_zones)

    pf = sub.add_parser("fleet", help="fleet movement arrows from a YAML spec")
    pf.add_argument("spec", type=Path, help="path to fleet YAML")
    common_dim(pf)
    pf.set_defaults(func=cmd_fleet)

    pc = sub.add_parser("compass", help="cardinal-direction compass rose")
    common_dim(pc)
    pc.add_argument("--cx", type=int, default=None, help="center x (default: width-80)")
    pc.add_argument("--cy", type=int, default=None, help="center y (default: height-80)")
    pc.add_argument("--radius", type=int, default=42)
    pc.add_argument("--color", default="D4B260")
    pc.add_argument("--opacity", type=float, default=0.85)
    pc.set_defaults(func=cmd_compass)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
