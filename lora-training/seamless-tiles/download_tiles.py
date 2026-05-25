# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31", "pillow>=10.0"]
# ///
"""Acquire CC0 seamless-tile references for the seamless-tile LoRA corpus.

Pulls top-down surface color maps from two CC0 sources — ambientCG
(zip-of-PBR-maps, we keep only *_Color) and Poly Haven (Diffuse 1k
jpg) — bins them by 40K archetype into raw-references/<archetype>/,
and records full provenance in SOURCES.json (CC0, asset id, url).

This script ONLY acquires + provenances. It does NOT caption or make
the keep/reject verdict — that requires visually Reading each image
per CORPUS_AUDIT.md's cardinal rule and is a separate pass.

Idempotent: skips files already on disk; re-runnable to top up.

    uv run download_tiles.py                 # default ~5/source/archetype
    uv run download_tiles.py --per-source 8  # larger pool
    uv run download_tiles.py --only tile_hex_plating tile_metal_grating
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).parent
REF = ROOT / "raw-references"
SOURCES_JSON = ROOT / "SOURCES.json"
UA = {"User-Agent": "solenne-cartography-corpus/1.0 (CC0 LoRA reference acquisition)"}
MIN_EDGE = 1024

# (archetype, ambientCG categories, Poly Haven category slugs, tag-filter set)
# tag-filter (when non-empty) keeps only assets whose tags/slug
# intersect it — used for the motif-specific archetypes where the
# source category is broad.
PLAN = [
    ("tile_hab_floor",        ["Concrete"],              ["concrete"],            set()),
    ("tile_industrial_floor", ["Metal", "MetalPlates"],  ["metal"],               set()),
    ("tile_ship_deck",        ["MetalPlates"],           ["metal"],               set()),
    ("tile_chapel_floor",     ["Marble", "PavingStones"],["tiles"],               set()),
    ("tile_medicae_floor",    ["Tiles"],                 ["tiles"],               set()),
    ("tile_tunnel_floor",     ["Rock", "Rocks"],         ["rock"],                set()),
    ("tile_sump_floor",       ["Ground"],                ["dirty"],               set()),
    ("tile_garrison_floor",   ["Asphalt", "PavingStones"],["asphalt", "road"],    set()),
    ("tile_hex_plating",      ["MetalPlates", "Metal"],  ["metal"],
     {"hexagon", "hexagonal", "hex", "honeycomb"}),
    ("tile_metal_grating",    ["Metal", "MetalPlates"],  ["metal"],
     {"grate", "grating", "mesh", "perforated", "grid", "diamond", "tread", "checker"}),
]


def load_sources() -> dict:
    if SOURCES_JSON.exists():
        return json.loads(SOURCES_JSON.read_text())
    return {}


def save_sources(s: dict) -> None:
    SOURCES_JSON.write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")


def ok_image(buf: bytes) -> bool:
    try:
        im = Image.open(io.BytesIO(buf))
        im.load()
        return max(im.size) >= MIN_EDGE
    except Exception:
        return False


def acg_assets(category: str, limit: int) -> list[dict]:
    url = ("https://ambientcg.com/api/v2/full_json"
           f"?type=Material&category={category}&sort=Popular&limit={limit}")
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    return r.json().get("foundAssets", [])


def acg_download_color(asset_id: str) -> bytes | None:
    url = f"https://ambientcg.com/get?file={asset_id}_1K-JPG.zip"
    r = requests.get(url, headers=UA, timeout=180)
    if r.status_code != 200 or not r.content:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        return None
    for n in zf.namelist():
        low = n.lower()
        if low.endswith(".jpg") and ("_color" in low or "_col." in low or low.endswith("color.jpg")):
            return zf.read(n)
    return None


def ph_assets(category: str, limit: int) -> list[tuple[str, dict]]:
    r = requests.get(f"https://api.polyhaven.com/assets?type=textures&categories={category}",
                      headers=UA, timeout=60)
    r.raise_for_status()
    items = list(r.json().items())
    items.sort(key=lambda kv: kv[1].get("download_count", 0), reverse=True)
    return items[:limit]


def ph_download_diffuse(asset_id: str) -> bytes | None:
    r = requests.get(f"https://api.polyhaven.com/files/{asset_id}", headers=UA, timeout=60)
    if r.status_code != 200:
        return None
    files = r.json()
    node = files.get("Diffuse") or files.get("diffuse") or files.get("Color") or files.get("col")
    if not node:
        return None
    res = node.get("1k") or node.get("2k")
    if not res:
        return None
    fmt = res.get("jpg") or res.get("png")
    if not fmt or "url" not in fmt:
        return None
    d = requests.get(fmt["url"], headers=UA, timeout=180)
    return d.content if d.status_code == 200 and d.content else None


def tag_match(tags: list[str], slug: str, filt: set[str]) -> bool:
    if not filt:
        return True
    blob = " ".join(tags).lower() + " " + slug.lower()
    return any(t in blob for t in filt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-source", type=int, default=5,
                    help="target kept files per source per archetype")
    ap.add_argument("--only", nargs="*", help="restrict to these archetype triggers")
    args = ap.parse_args()

    sources = load_sources()
    # Several archetypes share a source category (Poly Haven `metal`
    # feeds industrial/ship_deck/hex/grating; `tiles` feeds
    # chapel/medicae). Without a global guard the same asset lands in
    # multiple archetype dirs and gets captioned under two triggers
    # (violates no-duplicate + one-trigger-one-concept). Track every
    # asset_id already bound to an archetype and skip it elsewhere —
    # first archetype in PLAN order wins.
    seen_asset_ids = {v["asset_id"] for v in sources.values()}
    plan = [p for p in PLAN if not args.only or p[0] in args.only]
    grand = 0

    for arche, acg_cats, ph_cats, filt in plan:
        d = REF / arche
        d.mkdir(parents=True, exist_ok=True)
        print(f"\n=== {arche} ===")

        # ---- ambientCG ----
        kept = 0
        pool_limit = max(args.per_source * 4, 24) if filt else args.per_source * 3
        for cat in acg_cats:
            if kept >= args.per_source:
                break
            try:
                assets = acg_assets(cat, pool_limit)
            except Exception as e:
                print(f"  acg {cat}: query failed {e}")
                continue
            for a in assets:
                if kept >= args.per_source:
                    break
                aid = a["assetId"]
                if not tag_match(a.get("tags", []), aid, filt):
                    continue
                if aid in seen_asset_ids:
                    continue
                out = d / f"acg_{aid}.jpg"
                if out.exists():
                    seen_asset_ids.add(aid)
                    kept += 1
                    continue
                buf = acg_download_color(aid)
                time.sleep(1.0)
                if not buf or not ok_image(buf):
                    print(f"  acg {aid}: no usable color map")
                    continue
                out.write_bytes(buf)
                sources[str(out.relative_to(ROOT))] = {
                    "source": "ambientcg", "asset_id": aid,
                    "url": a.get("shortLink", f"https://ambientcg.com/a/{aid}"),
                    "category": cat, "license": "CC0 1.0",
                    "tags": a.get("tags", []),
                }
                seen_asset_ids.add(aid)
                kept += 1
                grand += 1
                print(f"  acg {aid} -> {out.name}")
                save_sources(sources)

        # ---- Poly Haven ----
        kept = 0
        for cat in ph_cats:
            if kept >= args.per_source:
                break
            try:
                items = ph_assets(cat, max(args.per_source * 4, 20) if filt else args.per_source * 2)
            except Exception as e:
                print(f"  ph {cat}: query failed {e}")
                continue
            for aid, meta in items:
                if kept >= args.per_source:
                    break
                if not tag_match(meta.get("tags", []), aid, filt):
                    continue
                if aid in seen_asset_ids:
                    continue
                out = d / f"ph_{aid}.jpg"
                if out.exists():
                    seen_asset_ids.add(aid)
                    kept += 1
                    continue
                buf = ph_download_diffuse(aid)
                time.sleep(1.0)
                if not buf or not ok_image(buf):
                    print(f"  ph {aid}: no usable diffuse")
                    continue
                out.write_bytes(buf)
                sources[str(out.relative_to(ROOT))] = {
                    "source": "polyhaven", "asset_id": aid,
                    "url": f"https://polyhaven.com/a/{aid}",
                    "category": cat, "license": "CC0 1.0",
                    "tags": meta.get("tags", []),
                }
                seen_asset_ids.add(aid)
                kept += 1
                grand += 1
                print(f"  ph {aid} -> {out.name}")
                save_sources(sources)

    save_sources(sources)
    print(f"\nDONE. {grand} new files. Provenance: {SOURCES_JSON}")
    print("NEXT: visually Read each file, then caption+bin per CORPUS_AUDIT.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
