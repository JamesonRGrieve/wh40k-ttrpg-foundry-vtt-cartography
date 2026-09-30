#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: AGPL-3.0-or-later
# /// script
# requires-python = ">=3.11"
# dependencies = ["easyocr", "pillow", "numpy"]
# ///
"""Screen a staged LoRA corpus for any legible text before training.

Runs OCR over every .png in a staged corpus folder (stage_single_stamps.py
output) and prints each image where OCR reads text it is at least MIN_CONF
sure of, with the words. Review the list by eye (OCR also fires on rivets,
grilles and wood grain) and pass the confirmed ones to stage_single_stamps.py
--exclude as pack paths (the folder's manifest.json maps file -> source).

Run on the training host (GPU): uv run ocr_screen_stamps.py <corpus-dir> > flagged.tsv
"""

from __future__ import annotations

import sys
from pathlib import Path

import easyocr

MIN_CONF = 0.5
MIN_CHARS = 2


def main() -> int:
    folder = Path(sys.argv[1])
    reader = easyocr.Reader(["en"], gpu=True, verbose=False)
    files = sorted(folder.glob("*.png"))
    for p in files:
        words = [t for _box, t, conf in reader.readtext(str(p)) if conf >= MIN_CONF and len(t.strip()) >= MIN_CHARS]
        if words:
            print(f"{p.name}\t{' | '.join(words)}", flush=True)
    print(f"# screened {len(files)} images", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
