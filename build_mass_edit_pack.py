#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow"]
# ///
"""
Build a Baileywiki Mass Edit preset pack JSON from the stamps + sidecars.

The output is a flat JSON array of Tile presets — one per stamp PNG —
with tags drawn from the sidecar's category, orientation, state, and
group_id fields. Import the generated file via the Mass Edit Preset
Browser → Import button.

Asset paths in the pack are written relative to a `--asset-prefix`,
which should match where the stamp PNGs are actually served from inside
Foundry's user-data directory. The default prefix assumes the stamps
deploy as a Foundry module at `modules/dh-cartography/stamps/`.

Usage:
    python build_mass_edit_pack.py [--asset-prefix PREFIX] [--out PATH]

Output (default): mass-edit-presets.json next to this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Optional dependency: PIL gives us real image dimensions. If not
# importable, we fall back to gridSize-square (Mass Edit recomputes
# missing width/height on import via loadImageVideoDimensions).
try:
    from PIL import Image  # type: ignore
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

HERE = Path(__file__).resolve().parent
DEFAULT_STAMPS_DIR = HERE / "stamps"

DEFAULT_ASSET_PREFIX = "modules/dh-cartography/stamps"
DEFAULT_GRID_SIZE = 100

YAML_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


@dataclass
class Sidecar:
    name: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    orientation: str | None = None
    state: str | None = None
    group_id: str | None = None
    source: str | None = None
    source_index: int | None = None


def parse_sidecar(path: Path) -> Sidecar:
    """Cheap line-oriented YAML parser for our known sidecar schema.

    Avoids the PyYAML dependency. Handles the limited subset we emit:
    scalar strings, nulls, ints, and one-line bracketed string lists.
    """
    s = Sidecar()
    if not path.exists():
        return s
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line or line.startswith(" "):
            continue
        m = YAML_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "" or val.lower() == "null":
            value: object = None
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            value = (
                [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()]
                if inner
                else []
            )
        elif val.isdigit():
            value = int(val)
        else:
            value = val.strip().strip('"').strip("'")
        if hasattr(s, key):
            setattr(s, key, value)
    return s


def stamp_dimensions(png: Path) -> tuple[int, int]:
    if HAVE_PIL:
        with Image.open(png) as im:
            return im.size  # (width, height)
    return (DEFAULT_GRID_SIZE, DEFAULT_GRID_SIZE)


def derive_name(stamp_path: Path, sc: Sidecar) -> str:
    if sc.name:
        bits = [sc.name]
        if sc.state and sc.state not in sc.name.lower():
            bits.append(sc.state)
        if sc.orientation and sc.orientation not in sc.name.lower():
            bits.append(sc.orientation)
        if len(bits) > 1:
            return f"{bits[0]} — {', '.join(bits[1:])}"
        return bits[0]
    # Fallback to filename when classification hasn't run yet.
    return stamp_path.stem


def derive_tags(sc: Sidecar) -> list[str]:
    out: list[str] = list(sc.tags or [])
    if sc.orientation:
        out.append(f"facing-{sc.orientation}" if sc.orientation in {"north", "south", "east", "west"} else sc.orientation)
    if sc.state:
        out.append(f"state-{sc.state}")
    if sc.group_id:
        out.append(f"group:{sc.group_id}")
    # De-dupe while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def preset_id_for(stamp_path: Path) -> str:
    # Foundry V13+ requires _id to be exactly 16 alphanumeric chars. Take the
    # first 16 chars of the stem's md5 (deterministic + collision-resistant).
    digest = hashlib.md5(stamp_path.stem.encode("utf-8")).hexdigest()
    return digest[:16]


def build_preset(stamp_path: Path, sc: Sidecar, asset_prefix: str) -> dict:
    width, height = stamp_dimensions(stamp_path)
    img_path = f"{asset_prefix}/{stamp_path.name}"
    return {
        "id": preset_id_for(stamp_path),
        "name": derive_name(stamp_path, sc),
        "documentName": "Tile",
        "img": img_path,
        "tags": derive_tags(sc),
        "gridSize": DEFAULT_GRID_SIZE,
        "data": [
            {
                "texture": {"src": img_path, "scaleX": 1, "scaleY": 1},
                "x": 0,
                "y": 0,
                "width": width,
                "height": height,
                "rotation": 0,
            }
        ],
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--stamps-dir",
        type=Path,
        default=DEFAULT_STAMPS_DIR,
        help="Directory containing PNG + YAML pairs to package (default: %(default)s)",
    )
    p.add_argument(
        "--asset-prefix",
        default=DEFAULT_ASSET_PREFIX,
        help="Path inside Foundry user-data where stamps will live (default: %(default)s)",
    )
    p.add_argument(
        "--out",
        type=Path,
        # Write directly into the staged module by default so dev runs
        # produce the same artifact deploy.sh deploys. Override with
        # `--out mass-edit-presets.json` to write to the repo root for
        # inspection without affecting the staged module.
        default=HERE / "dh-cartography" / "mass-edit-presets.json",
        help="Output JSON path (default: %(default)s)",
    )
    p.add_argument(
        "--source",
        default=None,
        help="Filter: include only PNG stems starting with this string",
    )
    p.add_argument(
        "--pack-src",
        type=Path,
        default=HERE / "dh-cartography" / "packs-src" / "dh-presets-journals",
        help="Directory to emit per-document JSON for the Mass Edit pack (default: %(default)s)",
    )
    args = p.parse_args(argv)

    stamps_dir: Path = args.stamps_dir
    if not stamps_dir.is_dir():
        print(f"stamps directory not found: {stamps_dir}", file=sys.stderr)
        return 1

    presets: list[dict] = []
    missing_sidecars = 0
    pngs = sorted(stamps_dir.glob("*.png"))
    if args.source:
        pngs = [p for p in pngs if p.stem.startswith(args.source)]
    for png in pngs:
        sidecar_path = png.with_suffix(".yaml")
        if not sidecar_path.exists():
            missing_sidecars += 1
        sc = parse_sidecar(sidecar_path)
        presets.append(build_preset(png, sc, args.asset_prefix.rstrip("/")))

    args.out.write_text(json.dumps(presets, indent=2) + "\n")
    print(f"Wrote {len(presets)} presets → {args.out}")
    if missing_sidecars:
        print(f"  (missing sidecars: {missing_sidecars})")

    # Also emit a JournalEntry document tree under packs-src/dh-presets-journals/
    # so a Foundry compendium pack can be compiled. Mass Edit's Preset Browser
    # auto-indexes any JournalEntry pack containing a metadata document with
    # _id="MassEditMetaData" — same convention used by Baileywiki's prefab
    # packs, no manual import step required.
    pack_src = args.pack_src
    if pack_src.exists():
        for f in pack_src.iterdir():
            if f.is_file():
                f.unlink()
    pack_src.mkdir(parents=True, exist_ok=True)

    META_INDEX_ID = "MassEditMetaData"
    MODULE_ID = "multi-token-edit"

    index_entries: dict[str, dict] = {}
    for preset in presets:
        pid = preset["id"]
        # Per-preset JournalEntry doc. The actual preset payload lives in
        # flags.multi-token-edit.preset; the document name/img/sort are
        # what shows in the Preset Browser tree.
        doc = {
            "_id": pid,
            "name": preset["name"],
            "sort": 0,
            "folder": None,
            "ownership": {"default": 0},
            "flags": {
                MODULE_ID: {
                    "preset": {
                        "id": pid,
                        "name": preset["name"],
                        "documentName": preset["documentName"],
                        "img": preset["img"],
                        "tags": preset["tags"],
                        "gridSize": preset["gridSize"],
                        "data": preset["data"],
                    },
                },
            },
        }
        (pack_src / f"{pid}.json").write_text(json.dumps(doc, indent=2) + "\n")
        index_entries[pid] = {
            "img": preset["img"],
            "documentName": preset["documentName"],
            "tags": preset["tags"],
        }

    metadata_doc = {
        "_id": META_INDEX_ID,
        "name": "!!! METADATA: DO NOT DELETE !!!",
        "sort": 0,
        "folder": None,
        "ownership": {"default": 0},
        "flags": {MODULE_ID: {"index": index_entries}},
    }
    (pack_src / f"{META_INDEX_ID}.json").write_text(
        json.dumps(metadata_doc, indent=2) + "\n",
    )
    print(f"Wrote {len(presets) + 1} pack source docs → {pack_src}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
