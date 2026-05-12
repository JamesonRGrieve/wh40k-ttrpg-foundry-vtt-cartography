#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
Audit CLIP-ViT-H clusters for caption-divergent merges.

CLIP-ViT-H clusters by visual style. Stamps with very different
captions but similar art-style backgrounds (e.g. all on a beige
parchment) sometimes get merged wrongly into one group_id. This tool
flags those candidates by computing pairwise content-token overlap
across each multi-member group's captions; groups whose minimum
pairwise overlap falls below a threshold are surfaced for manual
visual inspection.

Read-only. Outputs a sorted report; the operator decides what to
do (clear group_id, re-cluster, leave alone for borderline cases).

Usage:
    python group_audit.py                     # warn at <0.4 overlap
    python group_audit.py --threshold 0.5     # stricter
    python group_audit.py --json              # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CAMPAIGN_ROOT = HERE.parent.parent
AI_GEN = CAMPAIGN_ROOT / ".ai-gen"
STAMPS_DIR = AI_GEN / "cartography" / "stamps"

# Words to ignore when comparing captions: function words, formatting
# nouns, generic adjectives that match across many subjects. Keeps the
# similarity metric content-focused.
STOPWORDS = frozenset(
    """
    a an the of and or but in on at to for from with by as is are was were be been
    image illustration picture rendering drawing photograph photo digital simple
    minimalist style top down view shows depicts contains arranged set group
    several different multiple various pair stack collection
    light dark gray grey beige brown background
    """.split()
)


def tokens_of(caption: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z][a-z\-]+", (caption or "").lower())
        if w not in STOPWORDS and len(w) >= 4
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.4,
                    help="flag groups whose min pairwise Jaccard overlap is below this")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for f in sorted(STAMPS_DIR.glob("*.yaml")):
        try:
            d = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError:
            continue
        gid = d.get("group_id")
        desc = (d.get("description") or "").strip()
        name = d.get("name") or ""
        if not gid or not desc:
            continue
        groups[gid].append((f.stem, f"{name} {desc}"))

    flagged = []
    clean = []
    for gid, members in groups.items():
        if len(members) < 2:
            continue
        token_sets = [tokens_of(text) for _, text in members]
        if any(not t for t in token_sets):
            min_overlap = 0.0
        else:
            pairs = []
            for i in range(len(token_sets)):
                for j in range(i + 1, len(token_sets)):
                    union = len(token_sets[i] | token_sets[j])
                    inter = len(token_sets[i] & token_sets[j])
                    pairs.append(0.0 if union == 0 else inter / union)
            min_overlap = min(pairs)
        # Tokens shared across EVERY member's caption: likely the
        # concrete subject. If the cluster has a strong shared-subject
        # nucleus, low pairwise overlap is more likely "true variant
        # with state-specific descriptions" than "false-positive merge."
        shared = set.intersection(*token_sets) if all(token_sets) else set()
        rec = {
            "group_id": gid,
            "members": [stem for stem, _ in members],
            "min_overlap": round(min_overlap, 3),
            "shared_subject_tokens": sorted(shared),
        }
        # Decide flag: low overlap AND (no shared subject OR <2 shared).
        # 2+ shared content tokens suggest a true variant cluster.
        is_suspicious = min_overlap < args.threshold and len(shared) < 2
        if is_suspicious:
            flagged.append(rec)
        else:
            clean.append(rec)

    flagged.sort(key=lambda r: r["min_overlap"])

    if args.json:
        print(json.dumps({"threshold": args.threshold, "flagged": flagged, "clean": clean}, indent=2))
        return 1 if flagged else 0

    print(f"groups with members: {len(flagged) + len(clean)}")
    print(f"flagged (min pairwise caption overlap < {args.threshold}): {len(flagged)}")
    print(f"clean: {len(clean)}")
    if flagged:
        print()
        print("=== suspicious (no shared-subject nucleus) — inspect visually ===")
        for r in flagged:
            print(f"\n  {r['group_id'][:8]}.. min_overlap={r['min_overlap']:.2f}  shared={r['shared_subject_tokens']}  ({len(r['members'])} members)")
            for m in r["members"]:
                print(f"    {m}")
    if clean:
        print()
        print("=== likely-OK (high overlap or strong shared subject) ===")
        for r in clean:
            shared_summary = ",".join(r["shared_subject_tokens"][:3]) or "—"
            print(f"  {r['group_id'][:8]}.. min_overlap={r['min_overlap']:.2f}  shared=[{shared_summary}]  ({len(r['members'])} members)")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
