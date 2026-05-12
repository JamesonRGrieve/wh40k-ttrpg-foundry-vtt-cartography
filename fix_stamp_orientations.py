#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""Collapse cardinal-direction stamp orientations to top-down.

Background: the orientation classifier in classify_stamps.py used
to map "facing left", "front view", "from behind", etc. to cardinal
directions (north/south/east/west). For orthographic top-down
stamps that's a meaningless distinction — Foundry rotates tiles
freely at runtime so the "which way is the chair pointing" axis is
a placement concern, not a training axis.

This script walks stamps/*.yaml and rewrites cardinal orientations
to `top-down`. Isometric stays isometric. Unknown / null stays as-is.

Run once after the classifier vocabulary fix (2026-05-11). After
this pass, the orientation field on every stamp is one of:
top-down | isometric | null.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

CARDINAL = {"north", "south", "east", "west"}
HERE = Path(__file__).resolve().parent
STAMPS = HERE / "stamps"


def main() -> int:
    sidecars = sorted(STAMPS.glob("*.yaml"))
    changed = 0
    for p in sidecars:
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        ori = (d.get("orientation") or "").strip().lower()
        if ori not in CARDINAL:
            continue
        # Line-level rewrite to preserve formatting.
        lines = p.read_text().splitlines(keepends=True)
        out = []
        rewritten = False
        for line in lines:
            if not rewritten and re.match(r"^orientation\s*:", line):
                m = re.match(r"^(orientation\s*:).*?(\s*#.*)?$",
                             line.rstrip("\n"))
                if m:
                    trailing = m.group(2) or ""
                    out.append(f"{m.group(1)} top-down{trailing}\n")
                    rewritten = True
                    continue
            out.append(line)
        if rewritten:
            p.write_text("".join(out))
            changed += 1
    print(f"[done] rewrote {changed} sidecar orientations to top-down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
