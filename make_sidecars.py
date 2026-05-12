#!/usr/bin/env python3
"""
Emit a YAML metadata sidecar for each extracted stamp PNG.

For every `stamps/<stem>_NN.png`, write `stamps/<stem>_NN.yaml` (only if
the YAML doesn't exist, unless --force is passed). The sidecar holds
fields the ComfyUI classifier driver will fill in later. Manually-edited
fields (name, description, tags) are preserved across re-runs.

Schema (see CLAUDE.md):
    name:         null or string  — human-readable display name
    description:  null or string  — 1–2 sentence prose
    tags:         list[str]       — lowercase-hyphenated, vault conventions
    orientation:  null or one of (north, south, east, west, top-down, isometric)
    state:        null or one of (intact, damaged, destroyed, active, inactive)
    group_id:     null or string  — UUID linking variants of the same object
    source:       string          — original grid filename
    source_index: int             — index of this stamp within the source grid
    extracted_at: ISO-8601 string — timestamp the sidecar was first created
    classified_at: null or ISO    — timestamp ComfyUI last filled classification fields
    classified_by: null or string — model id / workflow hash that filled them

Usage:
    python make_sidecars.py [--force]
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
STAMPS_DIR = _HERE.parent.parent / ".ai-gen" / "cartography" / "stamps"

# Foundation YAML written for a fresh stamp. We hand-write the YAML rather
# than using PyYAML so the file ordering and comments are stable for diffs.
TEMPLATE = """\
# Cartography stamp sidecar — schema documented in ../CLAUDE.md
# Manually-editable fields (name, description, tags) are preserved across
# make_sidecars.py re-runs unless --force is passed.

name: null
description: null
tags: []
orientation: null   # north | south | east | west | top-down | isometric
state: null         # intact | damaged | destroyed | active | inactive
group_id: null      # UUID linking orientation/state variants of one object

source: {source}
source_index: {source_index}
extracted_at: {extracted_at}
classified_at: null
classified_by: null
"""

NAME_RE = re.compile(r"^(?P<stem>.+)_(?P<idx>\d+)\.png$")


def parse_stamp(path: Path) -> tuple[str, int] | None:
    m = NAME_RE.match(path.name)
    if not m:
        return None
    return m.group("stem"), int(m.group("idx"))


def find_source(stem: str) -> str:
    """Map a stamp stem back to its original grid PNG name.

    Stems are `<source-stem>` from the extractor, so the source grid is
    `../<stem>.png` relative to the stamps dir. Return the source filename
    (not full path) for portability.
    """
    return f"{stem}.png"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="overwrite existing sidecars")
    args = p.parse_args(argv)

    if not STAMPS_DIR.is_dir():
        print(f"stamps directory not found: {STAMPS_DIR}", file=sys.stderr)
        return 1

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    written = 0
    skipped = 0
    for png in sorted(STAMPS_DIR.glob("*.png")):
        parsed = parse_stamp(png)
        if parsed is None:
            continue
        stem, idx = parsed
        sidecar = png.with_suffix(".yaml")
        if sidecar.exists() and not args.force:
            skipped += 1
            continue
        sidecar.write_text(
            TEMPLATE.format(
                source=find_source(stem),
                source_index=idx,
                extracted_at=now,
            )
        )
        written += 1
    print(f"sidecars: wrote {written}, skipped {skipped} (existing)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
