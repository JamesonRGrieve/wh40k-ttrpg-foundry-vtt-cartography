#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: AGPL-3.0-or-later
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Stage the dh_stamp LoRA corpus from single, clean stamps.

One image per stamp variant, never a sheet: each comes from the public stamp
pack (.foundry-cartography-assets), already cut out and background-removed.
Every interior/exterior view is used, each captioned with its own perspective so
the view stays a promptable axis. The private pack (Games Workshop iconography)
is never used.

Leakage guards:
- the pack already drops cells with captions, headings or painted words
  (new-stamp-prompts/tools/subjects.py DROP_CELLS) and neighbour fragments
  (quality_scan.py strays);
- variants listed in EXCLUDE (a text screen, see ocr_screen_stamps.py, and
  review by eye) are left out;
- images under MIN_LONG_SIDE long or MIN_SHORT_SIDE short are left out;
- captions are built only from the pack's own data (caption()), never from
  machine captioning.

Each stamp is flattened onto pure white, centred in a square with a margin,
and written as <out>/<stamp-id>_<nn>.png with a paired .txt caption and a
provenance manifest.json.

Run: uv run stage_single_stamps.py [--out lora-training/stamps/single] [--exclude FILE]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
PACK = HERE.parent / ".foundry-cartography-assets"
# Sheet cells are small, so every stamp is upscaled to the 512 training bucket. A
# long, thin piece (a bench, a counter segment, a runner rug) carries its detail
# along its length, so size is judged on the long side; the short-side floor keeps
# out specks and slivers, which would upscale 8x+ and teach the trigger blur.
MIN_LONG_SIDE = 96     # px
MIN_SHORT_SIDE = 48    # px
MARGIN = 0.08          # fraction of the square left white around the stamp
SCALES = ("interior", "exterior")
TRIGGER = "dh_stamp"
# The pack's resolution tier of each variant's source art. Tiers below 256 are 32-128 px cuts from early sheets;
# upscaled 4-16x to the 512 bucket they teach the trigger blur (LoRA audit, 2026-11-24: 6,978 such variants).
LOW_TIERS = {"32", "64", "128"}
# Line-icon glyphs (black and blue diagram symbols), not painted stamps: kept in the pack for map builders, never
# trained on (LoRA audit, 2026-11-24).
ICON_STAMPS = {"Door", "Glass Door", "Iris Valve Door", "Wall Window", "Window"}
# A stamp split by view carries it in its name ("Market Stall (Side View)"); the caption states the view itself.
VIEW_SUFFIX = re.compile(r"\s*\((?:Side|Three-Quarter|Central) View\)$")
# State words that select a picture rather than describe it: a take number ("plain 2", "square front 003") and the
# ground-free twin's suffix (every training image is isolated on white anyway).
STATE_NOISE = re.compile(r"(?:,\s*no ground)?(?:\s+\d+)?(?:,\s*no ground)?$")


# Each image's view as the pack records it (a variant's own `perspective`, else its
# stamp's), stated plainly so the view is a promptable axis rather than something the
# trigger silently averages.
VIEWS = {
    "orthographic": "top-down orthographic view seen from directly above, no perspective",
    "isometric": "isometric three-quarter view from above at an angle",
    "front": "front elevation view seen straight from the side",
    "central": "high-angle one-point perspective view looking down",
}


def caption(stamp: dict, variant: dict, view: str) -> str:
    """Built only from the pack's own data: trigger, view (the image's perspective),
    subject, the variant's state (condition, damage, material), category, tags the name
    does not already say, setting, and lit/unlit for light sources. Constant style and
    background phrases close it; no machine captioning, no reviewer guesses."""
    name = VIEW_SUFFIX.sub("", stamp["name"]).lower()
    state = STATE_NOISE.sub("", variant["state"]).strip()
    name_words = set(re.findall(r"[a-z0-9]+", name)) | {stamp["category"].lower()}
    settings = [t.removeprefix("setting-") for t in stamp["tags"] if t.startswith("setting-")]
    extra = [t.replace("-", " ") for t in stamp["tags"]
             if not t.startswith("setting-") and t not in name_words]
    parts = [TRIGGER, VIEWS[view], f"a single {name}"]
    if state and state.lower() not in ("variant", name):
        parts.append(f"{state} variant")
    parts.append(f"{stamp['category'].lower()}")
    parts += extra
    parts += [f"{s} setting" for s in settings if s != "generic"]
    if "light" in stamp:
        parts.append("unlit" if variant.get("light", stamp["light"]) is None else "lit, glowing")
    parts += ["hand-painted battle map stamp", "isolated on a plain white background"]
    return ", ".join(parts)


def flatten(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    side = int(max(img.size) / (1 - 2 * MARGIN))
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    canvas.alpha_composite(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "lora-training/stamps/single")
    ap.add_argument("--exclude", type=Path, help="file of pack-relative image paths to leave out")
    args = ap.parse_args()
    exclude = set(args.exclude.read_text().split()) if args.exclude else set()
    pack = json.loads((PACK / "zephyr-pack.json").read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    manifest, skipped = [], {"small": 0, "excluded": 0, "low-res": 0}
    for stamp in pack["stamps"]:
        if stamp["scale"] not in SCALES or stamp["name"] in ICON_STAMPS:
            continue
        for n, v in enumerate(stamp["variants"], 1):
            if v["image"] in exclude:
                skipped["excluded"] += 1
                continue
            # Legacy CC0 symbol sets (cc0/stamps/*-symbols/) are flat line glyphs, not painted art.
            if v["image"].startswith("cc0/") and "symbols/" in v["image"]:
                skipped["icon"] = skipped.get("icon", 0) + 1
                continue
            if v.get("resolution") in LOW_TIERS:
                skipped["low-res"] += 1
                continue
            img = Image.open(PACK / v["image"])
            if max(img.size) < MIN_LONG_SIDE or min(img.size) < MIN_SHORT_SIDE:
                skipped["small"] += 1
                continue
            stem = f"{stamp['id']}_{n:02d}"
            flatten(img).save(args.out / f"{stem}.png")
            view = v.get("perspective", stamp["perspective"])
            text = caption(stamp, v, view)
            (args.out / f"{stem}.txt").write_text(text + "\n")
            manifest.append({"file": f"{stem}.png", "source": v["image"], "stamp": stamp["name"],
                             "view": view, "caption": text})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"staged {len(manifest)} images from {len({m['stamp'] for m in manifest})} stamps -> {args.out}; skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
