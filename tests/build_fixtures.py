#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow"]
# ///
"""
Generate a small fixtures set: 6 dummy stamp PNGs + sidecars, organized
into 2 groups so the preset-pack builder is exercised against populated
metadata. These do not touch the live `stamps/` directory so a parallel
classify run can keep going.

Layout:
  tests/fixtures/
    fx_bed_intact_north.png/.yaml      group A, state intact, north
    fx_bed_damaged_north.png/.yaml     group A, state damaged, north
    fx_bed_intact_south.png/.yaml      group A, state intact, south
    fx_table_intact_topdown.png/.yaml  group B, state intact, top-down
    fx_table_damaged_topdown.png/.yaml group B, state damaged, top-down
    fx_solo_lamp.png/.yaml             group C (singleton)
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
DST = HERE / "fixtures"


def make_png(path: Path, size: tuple[int, int], fill: tuple[int, int, int], label: str) -> None:
    img = Image.new("RGBA", size, fill + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, size[0] - 1, size[1] - 1], outline=(0, 0, 0, 255), width=2)
    d.text((6, 6), label, fill=(0, 0, 0, 255))
    img.save(path)


SIDECAR = """\
# Cartography stamp sidecar — fixture for end-to-end Foundry validation
name: {name}
description: {description}
tags: {tags}
orientation: {orientation}
state: {state}
group_id: {group_id}

source: {source}
source_index: {source_index}
extracted_at: {extracted_at}
classified_at: {classified_at}
classified_by: fixture
"""


def write_sidecar(png_path: Path, **fields: object) -> None:
    yaml = png_path.with_suffix(".yaml")
    yaml.write_text(SIDECAR.format(**fields))


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    bed_group = "11111111-1111-5111-9111-111111111111"
    table_group = "22222222-2222-5222-9222-222222222222"
    lamp_group = "33333333-3333-5333-9333-333333333333"

    fixtures = [
        # name, png_size, fill_color, label, sidecar fields
        ("fx_bed_intact_north", (160, 96), (180, 140, 80), "BED N intact",
         {"name": '"Wooden Bed"', "description": '"a wooden bed with a thick mattress"',
          "tags": "[furniture, bed, wooden]", "orientation": "north", "state": "intact",
          "group_id": f'"{bed_group}"', "source": "fixture", "source_index": 0,
          "extracted_at": now, "classified_at": now}),
        ("fx_bed_damaged_north", (160, 96), (160, 110, 70), "BED N damaged",
         {"name": '"Wooden Bed"', "description": '"a damaged wooden bed, broken slats"',
          "tags": "[furniture, bed, wooden, broken]", "orientation": "north", "state": "damaged",
          "group_id": f'"{bed_group}"', "source": "fixture", "source_index": 1,
          "extracted_at": now, "classified_at": now}),
        ("fx_bed_intact_south", (160, 96), (190, 150, 90), "BED S intact",
         {"name": '"Wooden Bed"', "description": '"a wooden bed seen from the foot"',
          "tags": "[furniture, bed, wooden]", "orientation": "south", "state": "intact",
          "group_id": f'"{bed_group}"', "source": "fixture", "source_index": 2,
          "extracted_at": now, "classified_at": now}),
        ("fx_table_intact_topdown", (128, 128), (140, 100, 60), "TABLE TD",
         {"name": '"Stone Table"', "description": '"an intact stone table viewed from above"',
          "tags": "[furniture, table, stone]", "orientation": "top-down", "state": "intact",
          "group_id": f'"{table_group}"', "source": "fixture", "source_index": 3,
          "extracted_at": now, "classified_at": now}),
        ("fx_table_damaged_topdown", (128, 128), (130, 100, 70), "TABLE TD dmg",
         {"name": '"Stone Table"', "description": '"a cracked stone table viewed from above"',
          "tags": "[furniture, table, stone, cracked]", "orientation": "top-down", "state": "damaged",
          "group_id": f'"{table_group}"', "source": "fixture", "source_index": 4,
          "extracted_at": now, "classified_at": now}),
        ("fx_solo_lamp", (64, 96), (220, 200, 90), "LAMP",
         {"name": '"Brass Lamp"', "description": '"a small brass lamp, lit"',
          "tags": "[lighting, lamp, brass]", "orientation": "isometric", "state": "active",
          "group_id": f'"{lamp_group}"', "source": "fixture", "source_index": 5,
          "extracted_at": now, "classified_at": now}),
    ]
    for stem, size, fill, label, fields in fixtures:
        png = DST / f"{stem}.png"
        make_png(png, size, fill, label)
        write_sidecar(png, **fields)

    print(f"wrote {len(fixtures)} fixture stamps to {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
