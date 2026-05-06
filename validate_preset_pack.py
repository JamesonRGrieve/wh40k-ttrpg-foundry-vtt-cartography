#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Validate a Mass Edit preset pack against the importer's required-field
contract. Checks every preset entry for the fields enforced by
`browser/browserApp.js:902-917` in the upstream multi-token-edit
module:

  - id (string, non-empty after generation)
  - name (string, non-empty)
  - documentName (string)
  - img (string, path)
  - tags (flat list of strings; group: prefix permitted)
  - gridSize (int)
  - data (non-empty list)
  - data[N].texture.src (string)
  - data[N].x, .y, .width, .height, .rotation (numbers)

Also surfaces best-practice warnings:
  - presets with empty img path (would render as broken tile)
  - presets whose data[N].texture.src disagrees with their img
  - presets with width/height of 0
  - duplicate ids (Mass Edit dedupes silently; loses presets)

Read-only. Exits 0 if every entry passes the required-field contract,
1 otherwise.

Usage:
    python validate_preset_pack.py [path/to/mass-edit-presets.json]
    python validate_preset_pack.py --warn-as-error  # also fail on warnings
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "dh-cartography" / "mass-edit-presets.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--warn-as-error", action="store_true")
    args = ap.parse_args()

    if not args.path.exists():
        print(f"not found: {args.path}", file=sys.stderr)
        return 2

    try:
        pack = json.loads(args.path.read_text())
    except json.JSONDecodeError as e:
        print(f"invalid JSON: {e}", file=sys.stderr)
        return 2

    if not isinstance(pack, list):
        print(f"top-level must be a list (Mass Edit's expected format), got {type(pack).__name__}", file=sys.stderr)
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    id_counter: Counter[str] = Counter()

    for i, entry in enumerate(pack):
        ctx = f"preset[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{ctx}: entry is not a dict")
            continue
        # Required scalar fields
        for key, expected_type, allow_empty in [
            ("id", str, False),
            ("name", str, False),
            ("documentName", str, False),
            ("img", str, True),  # warn separately
            ("gridSize", int, False),
        ]:
            v = entry.get(key)
            if v is None:
                errors.append(f"{ctx}: missing required field {key!r}")
            elif not isinstance(v, expected_type):
                # Foundry tolerates float gridSize — only flag if not numeric.
                if key == "gridSize" and isinstance(v, (int, float)):
                    pass
                else:
                    errors.append(
                        f"{ctx}: {key!r} expected {expected_type.__name__}, got {type(v).__name__}"
                    )
            elif not allow_empty and isinstance(v, str) and not v.strip():
                errors.append(f"{ctx}: {key!r} is empty")

        # tags: flat list of strings
        tags = entry.get("tags", [])
        if not isinstance(tags, list):
            errors.append(f"{ctx}: 'tags' must be a list, got {type(tags).__name__}")
        else:
            for j, t in enumerate(tags):
                if not isinstance(t, str):
                    errors.append(f"{ctx}: tags[{j}] must be string, got {type(t).__name__}")

        # data: non-empty list of placeable dicts
        data = entry.get("data")
        if not isinstance(data, list):
            errors.append(f"{ctx}: 'data' must be a list")
        elif not data:
            errors.append(f"{ctx}: 'data' must not be empty")
        else:
            for j, place in enumerate(data):
                pctx = f"{ctx}.data[{j}]"
                if not isinstance(place, dict):
                    errors.append(f"{pctx}: not a dict")
                    continue
                tex = place.get("texture")
                if not isinstance(tex, dict):
                    errors.append(f"{pctx}: 'texture' must be a dict")
                else:
                    src = tex.get("src")
                    if not isinstance(src, str) or not src.strip():
                        errors.append(f"{pctx}.texture.src missing or empty")
                    elif entry.get("img") and src != entry["img"]:
                        warnings.append(f"{pctx}.texture.src ({src}) disagrees with preset.img ({entry['img']})")
                for nkey in ("x", "y", "width", "height", "rotation"):
                    nv = place.get(nkey)
                    if not isinstance(nv, (int, float)):
                        errors.append(f"{pctx}.{nkey} missing or non-numeric")
                    elif nkey in ("width", "height") and nv == 0:
                        warnings.append(f"{pctx}.{nkey} is 0 (Mass Edit recomputes, but may indicate missing PIL)")

        # Best-practice check: img path
        if not entry.get("img"):
            warnings.append(f"{ctx}: 'img' is empty (preview will be blank)")

        # Track id duplicates
        if isinstance(entry.get("id"), str) and entry["id"]:
            id_counter[entry["id"]] += 1

    for pid, count in id_counter.items():
        if count > 1:
            errors.append(f"duplicate id: {pid!r} appears {count} times — Mass Edit dedupes silently")

    print(f"presets checked: {len(pack)}")
    print(f"errors: {len(errors)}")
    print(f"warnings: {len(warnings)}")
    for e in errors[:30]:
        print(f"  ERROR: {e}")
    if len(errors) > 30:
        print(f"  ... +{len(errors) - 30} more errors")
    for w in warnings[:30]:
        print(f"  WARN:  {w}")
    if len(warnings) > 30:
        print(f"  ... +{len(warnings) - 30} more warnings")

    if errors:
        return 1
    if warnings and args.warn_as_error:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
