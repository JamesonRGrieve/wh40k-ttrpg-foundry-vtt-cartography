#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
Report cartography pipeline health.

Surfaces:
- per-sheet classification + grouping + tagging coverage
- aggregate category-tag distribution
- preset-pack status (existence and entry count)
- staged-module status (count vs. source PNG count)

Read-only; never mutates anything.

Usage:
    python pipeline_status.py [--json]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SOURCES_DIR = HERE  # source PNG sheets live alongside the scripts
STAMPS_DIR = HERE / "stamps"
STAGED_DIR = HERE / "dh-cartography" / "stamps"
PRESET_PACK = HERE / "dh-cartography" / "mass-edit-presets.json"


@dataclass
class SheetReport:
    stem: str
    total_pngs: int = 0
    yaml_count: int = 0
    classified: int = 0
    grouped: int = 0
    has_categories: int = 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    sheets: dict[str, SheetReport] = {}
    cat_counter: collections.Counter[str] = collections.Counter()

    # Discover source PNG stems.
    source_stems = {p.stem for p in SOURCES_DIR.glob("*.png")}

    # Walk stamps/ — each PNG belongs to one sheet (its stem starts with the source).
    for png in sorted(STAMPS_DIR.glob("*.png")):
        # Match the longest source stem that prefixes the stamp filename.
        match = max(
            (s for s in source_stems if png.stem.startswith(s + "_")),
            key=len,
            default=None,
        )
        if not match:
            continue
        rep = sheets.setdefault(match, SheetReport(stem=match))
        rep.total_pngs += 1
        yaml_path = png.with_suffix(".yaml")
        if not yaml_path.exists():
            continue
        rep.yaml_count += 1
        try:
            d = yaml.safe_load(yaml_path.read_text()) or {}
        except yaml.YAMLError:
            continue
        if (d.get("description") or "").strip():
            rep.classified += 1
        if d.get("group_id"):
            rep.grouped += 1
        tags = d.get("tags") or []
        # Category tags emitted by classify_stamps.derive_category_tags.
        # Maintained as an explicit allowlist so descriptive caption
        # words like "light-colored" or "grid-like" don't false-match.
        category_tags = {
            "furniture", "furniture-chair", "furniture-couch", "furniture-bed",
            "furniture-table", "furniture-shelf",
            "container", "container-locker", "container-crate", "container-barrel",
            "container-vessel", "container-tableware", "container-bag",
            "light", "light-fixture",
            "door",
            "prop", "prop-document", "prop-writing",
            "tech", "tech-screen", "tech-device", "tech-utility",
            "architecture", "architecture-window", "architecture-step",
            "architecture-wall", "architecture-surface",
            "weapon", "weapon-melee", "weapon-ranged",
            "tool",
            "decor", "decor-banner", "decor-statue", "decor-floor",
        }
        cats = [t for t in tags if t in category_tags]
        if cats:
            rep.has_categories += 1
        for t in cats:
            cat_counter[t] += 1

    total_pngs = sum(r.total_pngs for r in sheets.values())
    total_classified = sum(r.classified for r in sheets.values())
    total_grouped = sum(r.grouped for r in sheets.values())
    total_categorized = sum(r.has_categories for r in sheets.values())
    staged_count = len(list(STAGED_DIR.glob("*.png"))) if STAGED_DIR.is_dir() else 0
    preset_count = 0
    if PRESET_PACK.exists():
        preset_count = len(json.loads(PRESET_PACK.read_text()))

    summary = {
        "sheets": {
            r.stem: {
                "pngs": r.total_pngs,
                "yamls": r.yaml_count,
                "classified": r.classified,
                "grouped": r.grouped,
                "categorized": r.has_categories,
            }
            for r in sorted(sheets.values(), key=lambda x: x.stem)
        },
        "totals": {
            "sheets": len(sheets),
            "stamps_total": total_pngs,
            "classified": total_classified,
            "grouped": total_grouped,
            "categorized": total_categorized,
            "staged": staged_count,
            "preset_count": preset_count,
        },
        "categories": dict(cat_counter.most_common()),
    }

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print("=== sheets ===")
    print(f"{'sheet':<60} {'pngs':>5} {'yaml':>5} {'cls':>4} {'grp':>4} {'cat':>4}")
    for stem, info in summary["sheets"].items():
        short = stem[:58] + ".." if len(stem) > 58 else stem
        print(
            f"{short:<60} {info['pngs']:>5} {info['yamls']:>5} "
            f"{info['classified']:>4} {info['grouped']:>4} {info['categorized']:>4}"
        )
    t = summary["totals"]
    pct = lambda n, d: 0.0 if not d else 100.0 * n / d
    print()
    print("=== totals ===")
    print(f"  sheets        {t['sheets']}")
    print(f"  stamps        {t['stamps_total']}")
    print(f"  classified    {t['classified']:>4}/{t['stamps_total']:<4}  ({pct(t['classified'], t['stamps_total']):.1f}%)")
    print(f"  grouped       {t['grouped']:>4}/{t['stamps_total']:<4}  ({pct(t['grouped'], t['stamps_total']):.1f}%)")
    print(f"  categorized   {t['categorized']:>4}/{t['stamps_total']:<4}  ({pct(t['categorized'], t['stamps_total']):.1f}%)")
    print(f"  staged        {t['staged']:>4}/{t['stamps_total']:<4}  ({pct(t['staged'], t['stamps_total']):.1f}%)")
    print(f"  preset entries {t['preset_count']}")
    if cat_counter:
        print()
        print("=== category tags ===")
        for cat, n in cat_counter.most_common(20):
            print(f"  {n:>4}  {cat}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
