# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Harvest Stage-1 structure tiles (wall/corner/door/endcap).

Two on-disk sources, no network, no Gemini (operator directive
2026-05-16):

  1. DaSIG modular pieces vendored in the .corpus tree
     (props/ tree only — dasig-props/ is byte-identical). COPIED.
  2. Wall/door pieces mis-binned into stamps/train/fixtures/ under
     the pre-3-stage model. MOVED here (relocation), old stamp
     caption carried along to be overwritten by the tile-spec
     caption in the visual-review pass.

Then byte-dedupes the union (DaSIG-named provenance wins over a
relocated copy of the same bytes) and writes SOURCES.json.

This script only harvests + dedupes + provenances. It does NOT
caption or make the final keep/reject verdict — that needs a visual
Read of every PNG (CORPUS_AUDIT.md cardinal rule) and is a separate
pass.

    uv run harvest_structure.py
    uv run harvest_structure.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
REF = ROOT / "raw-references"
SOURCES_JSON = ROOT / "SOURCES.json"

# Corpus tree is `.corpus/` at the cartography pipeline root
# (ROOT = .../cartography/lora-training/tile-structure).
DASIG = ROOT.parent.parent / ".corpus/uncertain/pending-visual-review/stamps/props"
FIX = (ROOT.parent / "stamps" / "train" / "fixtures")

WALL_NN = re.compile(r"WALL-\d+", re.I)
STRUCT_KW = ("wall", "door", "corner", "hatch", "bulkhead", "gate", "portcullis")
# substrings that mean it's furniture/equipment, not structure, even
# if a structural word also appears (e.g. "two-door beige locker").
FURNITURE_KW = ("locker", "cabinet", "shelf", "rack", "crate", "barrel",
                "console", "terminal", "bench", "cot", "table", "chair",
                "vending", "footlocker", "wardrobe", "desk", "pew")


def piece_for_name(name: str, path: Path) -> str | None:
    u = name.upper()
    if "WALL-CORNER" in u:
        return "tile_corner"
    if "WALL-DOOR" in u:
        return "tile_door"
    if "WALL-STAIRS" in u:
        return "tile_wall"          # captioned with integrated-stairs tag
    if WALL_NN.search(u) or "DASIG WALL" in u:
        return "tile_wall"
    if "/DOORS/" in str(path).upper() or "DASIG DOOR" in u:
        return "tile_door"
    return None


def piece_for_subject(subj: str) -> str | None:
    s = subj.lower()
    if any(f in s for f in FURNITURE_KW):
        return None
    if not any(k in s for k in STRUCT_KW):
        return None
    if any(k in s for k in ("door", "hatch", "bulkhead", "gate", "portcullis")):
        return "tile_door"
    if "corner" in s:
        return "tile_corner"
    if any(k in s for k in ("pillar", "junction", "endcap", "end cap", "terminus")):
        return "tile_endcap"
    return "tile_wall"


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    for p in ("tile_wall", "tile_corner", "tile_door", "tile_endcap"):
        (REF / p).mkdir(parents=True, exist_ok=True)
    sources: dict[str, dict] = {}
    if SOURCES_JSON.exists():
        sources = json.loads(SOURCES_JSON.read_text())

    copied = relocated = 0

    # ---- 1. DaSIG props/ copy ----
    if DASIG.exists():
        for png in sorted(DASIG.rglob("*.png")):
            piece = piece_for_name(png.name, png)
            if not piece:
                continue
            dst = REF / piece / f"dasig_{sanitize(png.name)}"
            if not dst.exists():
                if dry:
                    print(f"[dry] copy {png.name} -> {piece}/{dst.name}")
                else:
                    shutil.copy2(png, dst)
                copied += 1
            sources[str(dst.relative_to(ROOT))] = {
                "source": "dasig-on-disk",
                "origin": str(png),
                "license": "vendored DaSIG map-asset pack (.corpus)",
            }
    else:
        print(f"WARN: DaSIG path not found: {DASIG}")

    # ---- 2. Stage-3 fixtures relocation ----
    if FIX.exists():
        for txt in sorted(FIX.glob("*.txt")):
            png = txt.with_suffix(".png")
            if not png.exists():
                continue
            parts = [x.strip() for x in txt.read_text().strip().split(",")]
            subj = parts[1] if len(parts) > 1 and parts[0].startswith("dh_stamp") else ""
            piece = piece_for_subject(subj)
            if not piece:
                continue
            base = f"relocated_{sanitize(png.stem)}"
            dpng = REF / piece / f"{base}.png"
            dtxt = REF / piece / f"{base}.txt"
            if dry:
                print(f"[dry] MOVE {png.name} (subj='{subj}') -> {piece}/")
            else:
                shutil.move(str(png), dpng)
                shutil.move(str(txt), dtxt)   # old stamp caption; overwritten in review
            relocated += 1
            sources[str(dpng.relative_to(ROOT))] = {
                "source": "stage3-relocation",
                "origin": str(png),
                "old_stamp_caption_subject": subj,
                "license": "vendored DaSIG map-asset pack (.corpus)",
            }
    else:
        print(f"WARN: fixtures path not found: {FIX}")

    # ---- 3. byte-dedupe (dasig_ provenance wins over relocated_) ----
    by_hash: dict[str, list[Path]] = {}
    for png in REF.rglob("*.png"):
        by_hash.setdefault(md5(png), []).append(png)
    removed = 0
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda p: (0 if p.name.startswith("dasig_") else 1, str(p)))
        for dup in group[1:]:
            if dry:
                print(f"[dry] dedupe drop {dup.relative_to(REF)} (== {group[0].name})")
            else:
                sources.pop(str(dup.relative_to(ROOT)), None)
                dup.unlink()
                dup.with_suffix(".txt").unlink(missing_ok=True)
            removed += 1

    if not dry:
        SOURCES_JSON.write_text(json.dumps(sources, indent=2, sort_keys=True) + "\n")

    print(f"\ncopied(dasig)={copied}  relocated(stage3)={relocated}  "
          f"deduped={removed}")
    for p in ("tile_wall", "tile_corner", "tile_door", "tile_endcap"):
        n = len(list((REF / p).glob("*.png")))
        print(f"  {p}: {n}")
    print("NEXT: visually Read every PNG, then caption+verdict per CORPUS_AUDIT.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
