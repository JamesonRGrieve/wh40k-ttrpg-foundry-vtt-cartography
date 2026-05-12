#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""Stamp-name audit + cleanup tool.

Walks `stamps/*.yaml`, classifies each name into:
  - keep      — looks like a real subject noun phrase
  - nullify   — Florence-2 garbage (preamble leak, style descriptor,
                background-only, generic single-word)
  - null      — already null

With `--fix`, rewrites bad names to `null` in-place, preserving the
rest of the sidecar (line-level edit, not PyYAML round-trip).
Nullified names are then skipped by the StampHandler at staging
time — the PNG stays in stamps/ for possible re-classification later.

Patterns flagged as bad (case-insensitive unless noted):
  - contains "the image"             — preamble leak ("...The image is a...")
  - contains "background"            — describes BG not subject
  - starts with "with a" / "with "   — partial-phrase fragment
  - starts with "simple," "plain,"
    "minimalist" + comma             — style descriptor, not subject
  - exact match to a generic noun    — "image", "square", "object", "pattern",
                                       "cylindrical object", "rectangular object"
  - alphanumeric mash                — "3DThe", "3The", etc.
  - all-lowercase single word with
    no proper-noun structure         — usually a junk token

Usage:
  uv run audit_stamps.py             # report only
  uv run audit_stamps.py --fix       # rewrite bad names to null
  uv run audit_stamps.py --verbose   # show every bad name
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
STAMPS = HERE / "stamps"

# Bad-name patterns. Each is a (label, predicate) pair. KEEP IN SYNC
# with the matching list in classify_stamps.py (search for
# `_GARBAGE_NAME_PATTERNS`).
BAD_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("preamble_leak",      re.compile(r"\bthe image\b", re.I)),
    # Any word fused to "The" or "A" without a space — Florence-2
    # occasionally emits "SimpleThe", "SetThe", "3DThe", "MinimalA",
    # "DigitalA", etc. when concatenating chunks from PromptGen.
    ("preamble_word_mash", re.compile(r"^[A-Za-z0-9]+(The|A)\b\s")),
    ("preamble_3d_mash",   re.compile(r"^\s*(3D|3)(The|the)\b")),
    ("background_desc",    re.compile(r"\bbackground\b", re.I)),
    ("fragment_with",      re.compile(r"^\s*with\s+a?\s+", re.I)),
    ("style_simple",       re.compile(r"^\s*simple\s*,", re.I)),
    ("style_plain",        re.compile(r"^\s*plain\s*,", re.I)),
    ("style_minimalist",   re.compile(r"^\s*minimalist\b", re.I)),
    ("seamless_pattern",   re.compile(r"^\s*seamless\s+pattern", re.I)),
    # Aggregate / pattern descriptions: Florence-2 captions
    # tiled-arrangement images as "objects arranged in a pattern"
    # which doesn't give the LoRA a learnable single-subject anchor.
    ("aggregate_arrangement",
        re.compile(r"\b(objects?|frames?|items?|shapes?)\s+arranged\b", re.I)),
    ("aggregate_pattern",
        re.compile(r"\b(grid-?like|symmetrical|repeating)\s+pattern\b", re.I)),
    # Style-noun heads: "Menu Design", "Composition", "Aesthetic",
    # "Illustration" — these are presentation descriptors, not
    # subject nouns.
    ("style_noun_design",
        re.compile(r"^\s*\w+\s+design\b", re.I)),
    ("style_noun_aesthetic",
        re.compile(r"\baesthetic\b", re.I)),
    ("style_noun_composition",
        re.compile(r"^\s*\w+\s+composition\b", re.I)),
    ("style_noun_illustration",
        re.compile(r"^\s*\w+\s+illustration\b", re.I)),
    # Trailing fragments where the noun was eaten ("Frames With A Simple",
    # "Composition With A Plain"): name ends mid-modifier.
    ("trailing_with_a_adj",
        re.compile(r"\bwith\s+a\s+(simple|plain|minimalist|gray|grey|"
                   r"beige|brown|light|dark)\s*$", re.I)),
]

# Exact-match generic single/double-word names that carry no subject info.
EXACT_BAD = {
    "image", "pattern", "object", "square", "circle", "rectangle",
    "cylindrical object", "rectangular object", "circular object",
    "square object", "set", "group", "row", "grid",
    "abstract design", "geometric pattern",
}


def classify(name: str | None) -> tuple[str, str | None]:
    """Return (verdict, reason).
    verdict ∈ {keep, null, nullify}; reason is the matching pattern label.
    """
    if name is None or not str(name).strip():
        return ("null", None)
    n = str(name).strip()
    nl = n.lower().strip(' "')
    if nl in EXACT_BAD:
        return ("nullify", "exact_generic")
    for label, pat in BAD_PATTERNS:
        if pat.search(n):
            return ("nullify", label)
    # Very short single-word names like "Square" are often junk.
    if len(n.split()) == 1 and not n[0].isupper():
        return ("nullify", "single_lowercase")
    return ("keep", None)


def read_name(path: Path) -> str | None:
    try:
        d = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return None
    return d.get("name")


def nullify_name(path: Path) -> bool:
    """Line-level rewrite: replace the `name:` line with `name: null`.
    Preserves the rest of the file byte-for-byte.
    """
    lines = path.read_text().splitlines(keepends=True)
    out = []
    rewritten = False
    for line in lines:
        if not rewritten and re.match(r"^name\s*:", line):
            # Preserve any trailing comment if present
            m = re.match(r"^(name\s*:).*?(\s*#.*)?$", line.rstrip("\n"))
            if m:
                trailing = m.group(2) or ""
                out.append(f"{m.group(1)} null{trailing}\n")
                rewritten = True
                continue
        out.append(line)
    if rewritten:
        path.write_text("".join(out))
    return rewritten


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true",
                    help="rewrite bad names to null in-place")
    ap.add_argument("--verbose", action="store_true",
                    help="list every bad name found")
    args = ap.parse_args()

    sidecars = sorted(STAMPS.glob("*.yaml"))
    print(f"[audit] scanning {len(sidecars)} sidecars")

    keep = 0
    already_null = 0
    nullify: list[tuple[Path, str, str]] = []
    reason_counts: Counter[str] = Counter()
    for p in sidecars:
        n = read_name(p)
        verdict, reason = classify(n)
        if verdict == "keep":
            keep += 1
        elif verdict == "null":
            already_null += 1
        else:  # nullify
            nullify.append((p, n or "", reason or "?"))
            reason_counts[reason or "?"] += 1

    print(f"\n[audit] keep      = {keep:4d}")
    print(f"[audit] null      = {already_null:4d} (already null)")
    print(f"[audit] nullify   = {len(nullify):4d} (bad names)")
    print(f"[audit] total     = {keep + already_null + len(nullify)}")
    print(f"\n[audit] nullify reasons:")
    for reason, count in reason_counts.most_common():
        print(f"  {reason:24s} {count:4d}")

    if args.verbose:
        print(f"\n[audit] bad names (verbose):")
        for path, name, reason in nullify[:200]:
            print(f"  [{reason:24s}] {path.stem}: {name!r}")
        if len(nullify) > 200:
            print(f"  ... ({len(nullify) - 200} more)")

    if args.fix:
        rewritten = 0
        for path, _, _ in nullify:
            if nullify_name(path):
                rewritten += 1
        print(f"\n[fix] rewrote {rewritten}/{len(nullify)} sidecars to name: null")
        print(f"[fix] re-run `uv run corpus_generator.py --lora stamps` to "
              f"refresh the staged corpus")
    else:
        print(f"\n[audit] dry-run only. Pass --fix to rewrite bad names to null.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
