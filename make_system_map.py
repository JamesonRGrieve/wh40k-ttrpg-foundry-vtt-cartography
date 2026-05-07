#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow", "numpy"]
# ///
"""
Programmatic Imperial-cartography system map generator.

Chroma-Flux's `system` archetype produces beautiful one-off charts but
randomizes orbital geometry per seed. For a consistent campaign system
chart — always the same number of planets at the right relative
distances — a programmatic generator is more reliable.

Renders:
- Parchment-stained background with worn edges (procedural noise)
- Central Imperial Aquila / sun glyph
- Concentric orbital rings (one per planet)
- Planet discs sized + colored to match the campaign's lore
- Orbital text labels ("SOLENNE I", "SOLENNE II", ...)
- Imperial sigil border (corner ornaments)

Default config renders the Solenne system for the current Dark
Heresy campaign. Override the planets list to render any other
system.

Usage:
    python make_system_map.py [--output PATH] [--width N] [--height N]
                              [--config PATH] [--seed N]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


HERE = Path(__file__).resolve().parent


# Default config: the Solenne system as documented in Campaign Home.md.
SOLENNE_SYSTEM: dict = {
    "name": "SOLENNE",
    "subtitle": "SUB-SECTOR · DARK HERESY",
    # All `*_frac` values are fractions of MAX_RADIUS_FRAC * min(w, h) / 2
    # — i.e. the chart's render radius. Outermost planet's orbit_frac
    # caps at 0.95 so its label has room outside the orbit ring.
    "star": {"radius_frac": 0.045, "color_inner": (255, 220, 140), "color_outer": (220, 130, 60)},
    "planets": [
        {
            "name": "SOLENNE I",
            "subtitle": "Uninhabitable · Vulcanic",
            "orbit_frac": 0.20,
            "radius_frac": 0.012,
            "color": (200, 80, 60),
        },
        {
            "name": "SOLENNE II · MAJORIS",
            "subtitle": "Hive World · Capital",
            "orbit_frac": 0.40,
            "radius_frac": 0.020,
            "color": (180, 150, 110),
            "moons": [
                {"name": "MINORIS", "orbit_frac": 0.030, "radius_frac": 0.007, "color": (160, 140, 130)},
            ],
        },
        {
            "name": "SOLENNE III",
            "subtitle": "Uninhabitable · Frozen",
            "orbit_frac": 0.62,
            "radius_frac": 0.018,
            "color": (180, 200, 220),
        },
        {
            "name": "SOLENNE IV",
            "subtitle": "Uninhabitable · Outer",
            "orbit_frac": 0.85,
            "radius_frac": 0.024,
            "color": (90, 110, 140),
        },
    ],
}

# Maximum orbital radius as fraction of min(w,h)/2. Leaves room for
# titles and corner sigils.
MAX_RADIUS_FRAC = 0.42


# Aquila silhouette as a 32x32 boolean mask, drawn by hand. Two heads,
# central body, outstretched wings — the simplified two-headed eagle.
# Used as the central Sun's overlay glyph and the corner sigils.
AQUILA_GRID = [
    "                                ",
    "                                ",
    "      X                  X      ",
    "     XXX                XXX     ",
    "    XXXXX              XXXXX    ",
    "    XXXXXX            XXXXXX    ",
    "    XXXXXXX  XXXXXX  XXXXXXX    ",
    "     XXXXXXXXXXXXXXXXXXXXXXX    ",
    "      XXXXXXXXXXXXXXXXXXXXX     ",
    "       XXXXXXXXXXXXXXXXXXX      ",
    "        XXXXXXXXXXXXXXXX        ",
    "  XXXXXXXXXXXXXXXXXXXXXXXXXXXX  ",
    " XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX ",
    "  XXXXXXXXXXXXXXXXXXXXXXXXXXXX  ",
    "    XXXXXXXXXXXXXXXXXXXXXXXX    ",
    "      XXXXXXXXXXXXXXXXXXXX      ",
    "         XXXXXXXXXXXXXX         ",
    "          XXXXXXXXXX            ",
    "           XXXXXXXX             ",
    "            XXXXXX              ",
    "             XXXX               ",
    "              XX                ",
    "                                ",
    "                                ",
    "                                ",
    "                                ",
    "                                ",
    "                                ",
    "                                ",
    "                                ",
    "                                ",
    "                                ",
]


# Color palette tuned for Imperial parchment cartography.
PARCHMENT_BASE = (218, 196, 160)
PARCHMENT_DARK = (158, 130, 90)
INK_DARK = (54, 38, 26)
INK_FADED = (110, 80, 50)
GOLD_LEAF = (212, 178, 96)
RED_SEAL = (140, 30, 30)


def render_parchment(size: tuple[int, int], rng: random.Random) -> Image.Image:
    """Procedural worn-parchment background.

    Builds a base color, layers gaussian noise for paper grain, applies
    radial darkening at the edges, and stamps a few stains. Output is
    RGB at the requested size.
    """
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:] = np.array(PARCHMENT_BASE, dtype=np.float32)
    # Paper grain
    grain = np.array(rng.choices(range(-12, 13), k=h * w), dtype=np.float32).reshape(h, w, 1)
    arr += grain
    # Radial darkening from corners inward
    yy, xx = np.indices((h, w))
    cx, cy = w / 2.0, h / 2.0
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / np.sqrt(cx ** 2 + cy ** 2)
    edge_mask = np.clip((dist - 0.45) / 0.55, 0, 1) ** 2
    dark = np.array(PARCHMENT_DARK, dtype=np.float32)
    arr = arr * (1 - edge_mask[..., None] * 0.6) + dark * edge_mask[..., None] * 0.6
    # Random stains — small darker blobs
    for _ in range(12):
        sx = rng.randint(int(w * 0.05), int(w * 0.95))
        sy = rng.randint(int(h * 0.05), int(h * 0.95))
        sr = rng.randint(int(min(w, h) * 0.01), int(min(w, h) * 0.04))
        intensity = rng.uniform(0.05, 0.18)
        for dy in range(-sr, sr + 1):
            for dx in range(-sr, sr + 1):
                if dx * dx + dy * dy > sr * sr:
                    continue
                px, py = sx + dx, sy + dy
                if 0 <= px < w and 0 <= py < h:
                    falloff = 1 - (dx * dx + dy * dy) / (sr * sr)
                    arr[py, px] *= 1 - intensity * falloff
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def get_font(size: int) -> ImageFont.ImageFont:
    """Imperial-style lettering. Falls back to PIL default if no system font.

    Tries serif fonts that ship with most Linux distros; the chart
    works at smaller scale with the bitmap default but reads better
    with a real serif.
    """
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def stamp_aquila(img: Image.Image, cx: int, cy: int, size: int, color: tuple[int, int, int],
                 alpha: int = 220) -> None:
    """Stamp the AQUILA_GRID onto img centered at (cx, cy) at `size` x `size`."""
    rows = AQUILA_GRID
    grid_h = len(rows)
    grid_w = len(rows[0])
    cell_w = size / grid_w
    cell_h = size / grid_h
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for ry, row in enumerate(rows):
        for rx, ch in enumerate(row):
            if ch != "X":
                continue
            x0 = int(cx - size / 2 + rx * cell_w)
            y0 = int(cy - size / 2 + ry * cell_h)
            x1 = int(x0 + cell_w + 1)
            y1 = int(y0 + cell_h + 1)
            draw.rectangle([x0, y0, x1, y1], fill=color + (alpha,))
    img.alpha_composite(overlay)


def render_system_chart(config: dict, size: tuple[int, int], seed: int) -> Image.Image:
    rng = random.Random(seed)
    w, h = size
    bg = render_parchment(size, rng).convert("RGBA")
    draw = ImageDraw.Draw(bg)

    cx, cy = w / 2, h / 2
    base_dim = min(w, h)
    # All orbit_frac / radius_frac fields are scaled relative to
    # max_render_r so the outermost planet fits at orbit_frac=1.0.
    max_render_r = base_dim * MAX_RADIUS_FRAC

    # Decorative inner frame
    inset = int(base_dim * 0.04)
    draw.rectangle([inset, inset, w - inset, h - inset], outline=INK_DARK + (255,), width=4)
    inset2 = int(inset + base_dim * 0.012)
    draw.rectangle([inset2, inset2, w - inset2, h - inset2], outline=INK_FADED + (200,), width=1)

    # Star at center
    star = config["star"]
    star_r = int(max_render_r * star["radius_frac"])
    # Glow
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for r, a in [(star_r * 4, 30), (star_r * 3, 50), (star_r * 2, 80)]:
        gdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=star["color_outer"] + (a,))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=8))
    bg.alpha_composite(glow)
    draw.ellipse([cx - star_r, cy - star_r, cx + star_r, cy + star_r],
                 fill=star["color_outer"] + (255,), outline=INK_DARK + (255,), width=2)
    inner_r = int(star_r * 0.7)
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
                 fill=star["color_inner"] + (255,))

    # Orbital rings + planets
    font_planet = get_font(max(12, int(base_dim * 0.020)))
    font_planet_sub = get_font(max(10, int(base_dim * 0.013)))
    font_moon = get_font(max(9, int(base_dim * 0.012)))

    # Deterministic angular distribution: each planet gets a sector
    # offset evenly around 360°, plus a per-seed rotation. Labels
    # never collide because no two planets share the same sector.
    n_planets = len(config["planets"])
    base_rotation = rng.uniform(0, 2 * 3.14159)
    for i, planet in enumerate(config["planets"]):
        orbit_r = int(max_render_r * planet["orbit_frac"])
        # Orbit ring (faded ink)
        draw.ellipse([cx - orbit_r, cy - orbit_r, cx + orbit_r, cy + orbit_r],
                     outline=INK_FADED + (180,), width=2)
        # Even sector + small jitter so the distribution looks
        # natural rather than perfectly polygonal.
        sector_angle = base_rotation + 2 * 3.14159 * i / n_planets
        sector_angle += rng.uniform(-0.15, 0.15)
        angle = sector_angle
        px = cx + orbit_r * np.cos(angle)
        py = cy + orbit_r * np.sin(angle)
        pr = int(max_render_r * planet["radius_frac"] * 4)
        draw.ellipse([px - pr, py - pr, px + pr, py + pr],
                     fill=planet["color"] + (255,), outline=INK_DARK + (255,), width=2)

        # Inner shading: small darker arc on the unlit side
        shade_r = int(pr * 0.85)
        shade = Image.new("RGBA", (pr * 2, pr * 2), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shade)
        sdraw.ellipse([pr - shade_r + int(pr * 0.5), pr - shade_r,
                       pr + shade_r + int(pr * 0.5), pr + shade_r],
                      fill=(0, 0, 0, 80))
        shade = shade.filter(ImageFilter.GaussianBlur(radius=pr / 4))
        bg.paste(shade, (int(px - pr), int(py - pr)), shade)

        # Label: name + subtitle
        label_dx = pr + int(base_dim * 0.012)
        # Place label outside the orbit center on whichever side has room
        if px > cx:
            lx = px + label_dx
            anchor = "lt"
        else:
            lx = px - label_dx
            anchor = "rt"
        ly = py - int(base_dim * 0.005)
        draw.text((lx, ly), planet["name"], fill=INK_DARK + (255,),
                  font=font_planet, anchor=anchor)
        draw.text((lx, ly + int(base_dim * 0.022)), planet["subtitle"],
                  fill=INK_FADED + (255,), font=font_planet_sub, anchor=anchor)

        # Moons
        for moon in planet.get("moons", []):
            mrad = int(max_render_r * moon["orbit_frac"] * 4)
            draw.ellipse([px - mrad, py - mrad, px + mrad, py + mrad],
                         outline=INK_FADED + (140,), width=1)
            mangle = rng.uniform(0, 2 * 3.14159)
            mx = px + mrad * np.cos(mangle)
            my = py + mrad * np.sin(mangle)
            mr = int(max_render_r * moon["radius_frac"] * 4)
            draw.ellipse([mx - mr, my - mr, mx + mr, my + mr],
                         fill=moon["color"] + (255,), outline=INK_DARK + (255,), width=1)
            draw.text((mx + mr + 4, my - 4), moon["name"],
                      fill=INK_FADED + (255,), font=font_moon, anchor="lt")

    # Asteroid belt: randomized small specks between two adjacent planets
    if len(config["planets"]) >= 2:
        # Place between 1st and 2nd planet's orbits
        belt_r0 = max_render_r * (config["planets"][0]["orbit_frac"] + 0.04)
        belt_r1 = max_render_r * (config["planets"][1]["orbit_frac"] - 0.02)
        if belt_r1 > belt_r0:
            for _ in range(120):
                r = rng.uniform(belt_r0, belt_r1)
                a = rng.uniform(0, 2 * 3.14159)
                ax = cx + r * np.cos(a)
                ay = cy + r * np.sin(a)
                sr = rng.randint(1, 2)
                draw.ellipse([ax - sr, ay - sr, ax + sr, ay + sr], fill=INK_DARK + (200,))

    # Title cartouche at top
    font_title = get_font(max(28, int(base_dim * 0.05)))
    font_subtitle = get_font(max(14, int(base_dim * 0.020)))
    title = config["name"]
    subtitle = config.get("subtitle", "")
    draw.text((cx, int(base_dim * 0.075)), title, fill=INK_DARK + (255,),
              font=font_title, anchor="mm")
    if subtitle:
        draw.text((cx, int(base_dim * 0.115)), subtitle, fill=INK_FADED + (255,),
                  font=font_subtitle, anchor="mm")

    # Corner aquila sigils
    sigil_size = int(base_dim * 0.08)
    sigil_inset = int(base_dim * 0.07)
    for sx, sy in [(sigil_inset, sigil_inset),
                   (w - sigil_inset, sigil_inset),
                   (sigil_inset, h - sigil_inset),
                   (w - sigil_inset, h - sigil_inset)]:
        stamp_aquila(bg, sx, sy, sigil_size, GOLD_LEAF)

    # Red wax seal at bottom-center
    seal_r = int(base_dim * 0.05)
    seal_cx, seal_cy = cx, h - int(base_dim * 0.085)
    draw.ellipse([seal_cx - seal_r, seal_cy - seal_r, seal_cx + seal_r, seal_cy + seal_r],
                 fill=RED_SEAL + (240,), outline=INK_DARK + (255,), width=2)
    stamp_aquila(bg, seal_cx, seal_cy, int(seal_r * 1.4), (240, 220, 180))

    return bg.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", type=Path,
                    default=HERE / "battlemaps" / "SOLENNE_system_chart.png")
    ap.add_argument("--width", type=int, default=2048)
    ap.add_argument("--height", type=int, default=2048)
    ap.add_argument("--config", type=Path, default=None,
                    help="JSON file overriding system config (default: SOLENNE_SYSTEM)")
    ap.add_argument("--seed", type=int, default=42,
                    help="seed for paper grain, planet angles, and asteroid placement")
    args = ap.parse_args()

    config = SOLENNE_SYSTEM if args.config is None else json.loads(args.config.read_text())
    img = render_system_chart(config, (args.width, args.height), seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    print(f"[ok] {args.output} ({args.width}x{args.height}, seed={args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
