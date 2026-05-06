#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Run the full cartography pipeline end-to-end.

Idempotent: each stage is a no-op when its outputs are already current.
Honors the "no concurrent GPU jobs" rule by chaining stages serially.

Stages:
  1. extract_stamps    — slice grid PNGs into transparent stamps
  2. make_sidecars     — populate yaml metadata files
  3. classify_stamps   — Florence-2 captions (GPU; can take hours)
  4. assign_groups     — CLIP-ViT-H clustering (GPU)
  5. stage_module      — hardlink stamps into the module dir
  6. build_mass_edit_pack — JSON preset pack
  7. validate_preset_pack — pre-deploy contract check

Usage:
    python pipeline_run.py                     # run all stages
    python pipeline_run.py --skip classify     # skip a heavy stage
    python pipeline_run.py --only stage,build  # only these stages
    python pipeline_run.py --source <stem>     # filter classify+assign

Aborts on the first stage failure unless --keep-going is passed.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

STAGES: list[tuple[str, list[str]]] = [
    ("extract", ["uv", "run", "--quiet", "extract_stamps.py"]),
    ("sidecars", ["uv", "run", "--quiet", "make_sidecars.py"]),
    ("classify", ["uv", "run", "--quiet", "classify_stamps.py"]),
    ("assign", ["uv", "run", "--quiet", "assign_groups.py"]),
    ("stage", ["uv", "run", "--quiet", "stage_module.py"]),
    ("build", ["uv", "run", "--quiet", "build_mass_edit_pack.py"]),
    ("validate", ["uv", "run", "--quiet", "validate_preset_pack.py"]),
]


def main() -> int:
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__)
    ap.add_argument("--skip", default="", help="comma-separated stages to skip")
    ap.add_argument("--only", default="", help="comma-separated stages to run (overrides --skip)")
    ap.add_argument(
        "--source",
        default=None,
        help="filter passed to classify+assign (--source <stem>)",
    )
    ap.add_argument("--keep-going", action="store_true", help="continue after stage failures")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    rc_total = 0
    for name, base in STAGES:
        if only and name not in only:
            continue
        if not only and name in skip:
            print(f"[skip] {name}")
            continue
        cmd = list(base)
        if args.source and name in ("classify", "assign"):
            cmd += ["--source", args.source]
        print(f"[{name}] {shlex.join(cmd)}")
        proc = subprocess.run(cmd, cwd=HERE)
        if proc.returncode != 0:
            rc_total = proc.returncode
            print(f"[{name}] failed (rc={proc.returncode})", file=sys.stderr)
            if not args.keep_going:
                return proc.returncode
    return rc_total


if __name__ == "__main__":
    sys.exit(main())
