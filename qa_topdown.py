#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pillow"]
# ///
"""Top-down battlemap QA smoke harness.

Re-renders every interior archetype at one canonical seed (and aspect
ratio appropriate to the archetype) and stages outputs to
``battlemaps/qa/<runtag>/`` for one-glance review.

Usage:
    uv run qa_topdown.py                       # full sweep, default tag
    uv run qa_topdown.py --tag round2          # tagged QA bucket
    uv run qa_topdown.py --only hab chapel     # subset
    uv run qa_topdown.py --seed 7              # different canonical seed

Per CLAUDE.md the 3090 is one queue: this script serializes renders.
Architecture-only is enforced by the prompts in generate_battlemap.py;
the harness does no prompt mutation of its own.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter

from generate_battlemap import (  # type: ignore[import-not-found]
    INTERIOR_FLOOR_PROMPT_TEMPLATE,
    INTERIOR_STYLE_FLOOR_TEXTURES,
    INTERIOR_STYLES,
    _clip_l_for_style,
    run_interior,
)

ROOT = Path(__file__).resolve().parent
QA_ROOT = ROOT / "battlemaps" / "qa"

# Canonical aspect per archetype. Tunnel is a corridor; everything else
# is a square room. District/region/planet/system are wide-scale; we
# render them square as the strategic-map norm.
ARCHETYPE_DIMS: dict[str, tuple[int, int]] = {
    "hab": (1024, 1024),
    "tunnel": (1024, 512),
    "industrial": (1024, 1024),
    "chapel": (1024, 1024),
    "bar": (1024, 1024),
    "garrison": (1024, 1024),
    "lair": (1024, 1024),
    "medicae": (1024, 1024),
    "archive": (1024, 1024),
    "mechanicus": (1024, 1024),
    "district": (1024, 1024),
    "region": (1024, 1024),
    "planet": (1024, 1024),
    "system": (1024, 1024),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://198.51.100.11:8188", help="ComfyUI server URL")
    ap.add_argument("--seed", type=int, default=42, help="canonical seed for the QA sweep")
    ap.add_argument("--tag", default="round1", help="subdirectory under battlemaps/qa/")
    ap.add_argument(
        "--only",
        nargs="+",
        choices=sorted(INTERIOR_STYLES),
        help="restrict to these archetypes (default: all)",
    )
    ap.add_argument(
        "--exclude",
        nargs="+",
        choices=sorted(INTERIOR_STYLES),
        default=[],
        help="archetypes to skip (default: none)",
    )
    ap.add_argument(
        "--floor-only",
        action="store_true",
        help="render floor-only (canonical stackable base layer; walls separate). "
        "Restricts to archetypes with a floor texture defined.",
    )
    args = ap.parse_args()

    targets = list(args.only) if args.only else sorted(INTERIOR_STYLES)
    targets = [a for a in targets if a not in set(args.exclude)]
    if args.floor_only:
        before = list(targets)
        targets = [a for a in targets if a in INTERIOR_STYLE_FLOOR_TEXTURES]
        skipped = sorted(set(before) - set(targets))
        if skipped:
            print(f"[qa] --floor-only: skipping (no floor texture): {skipped}", file=sys.stderr)

    out_dir = QA_ROOT / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[qa] tag={args.tag} seed={args.seed} archetypes={targets}", file=sys.stderr)

    t0 = perf_counter()
    failures: list[tuple[str, str]] = []
    successes: list[tuple[str, Path]] = []
    for style in targets:
        w, h = ARCHETYPE_DIMS.get(style, (1024, 1024))
        prefix = f"qa_{args.tag}_{style}_seed{args.seed}"
        if args.floor_only:
            t5 = INTERIOR_FLOOR_PROMPT_TEMPLATE.format(
                texture=INTERIOR_STYLE_FLOOR_TEXTURES[style]
            )
        else:
            t5 = INTERIOR_STYLES[style]
        try:
            saved = run_interior(
                args.server,
                t5xxl=t5,
                clip_l=_clip_l_for_style(style),
                width=w,
                height=h,
                seed=args.seed,
                prefix=prefix,
                floor_only=args.floor_only,
            )
            # run_interior writes to ROOT cwd; relocate into the QA bucket.
            target = out_dir / saved.name
            saved.replace(target)
            successes.append((style, target))
            print(f"[qa] OK  {style:12s} -> {target.relative_to(ROOT)}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 — we want one failure to not stop the sweep
            failures.append((style, str(exc)))
            print(f"[qa] ERR {style:12s} {exc}", file=sys.stderr)

    elapsed = perf_counter() - t0
    print(
        f"[qa] done in {elapsed:.1f}s — {len(successes)} ok, {len(failures)} failed -> {out_dir.relative_to(ROOT)}",
        file=sys.stderr,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
