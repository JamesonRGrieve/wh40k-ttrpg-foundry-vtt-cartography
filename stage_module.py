#!/usr/bin/env python3
"""
Stage extracted stamps and battlemaps into the dh-cartography module dir.

Hardlinks (or copies, on filesystems that don't support hardlinks) every
PNG from `stamps/` into `dh-cartography/stamps/` so the module is
self-contained and ready to zip-and-install or rsync to the Foundry VTT.

Battlemap assets curated for module deployment go in
`dh-cartography/battlemaps/` directly (no source-of-truth folder; the
operator copies in chosen renders by hand). This script does NOT touch
that subdir — it's manually curated.

Sidecar YAML files are NOT staged — they are pipeline metadata, not
runtime assets. The Mass Edit preset pack JSON is the runtime artifact.

Usage:
    python stage_module.py [--copy]  # default: hardlink, --copy forces copy
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "stamps"
DST = HERE / "dh-cartography" / "stamps"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--copy", action="store_true", help="Force copy instead of hardlink")
    args = p.parse_args(argv)

    if not SRC.is_dir():
        print(f"source not found: {SRC}", file=sys.stderr)
        return 1
    DST.mkdir(parents=True, exist_ok=True)

    linked = 0
    copied = 0
    skipped = 0
    for png in sorted(SRC.glob("*.png")):
        target = DST / png.name
        if target.exists():
            try:
                if target.samefile(png):
                    skipped += 1
                    continue
            except FileNotFoundError:
                pass
            target.unlink()
        if args.copy:
            shutil.copy2(png, target)
            copied += 1
        else:
            try:
                os.link(png, target)
                linked += 1
            except OSError:
                shutil.copy2(png, target)
                copied += 1

    # Prune stamps that exist in DST but no longer have a source. Source is
    # authoritative — extracted stamps can be removed (gutter artifacts,
    # superseded sheets) and the module should reflect that without manual
    # cleanup.
    src_names = {p.name for p in SRC.glob("*.png")}
    pruned = 0
    for staged in sorted(DST.glob("*.png")):
        if staged.name not in src_names:
            staged.unlink()
            pruned += 1

    print(f"staged: linked={linked} copied={copied} skipped={skipped} pruned={pruned} → {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
