#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "PyYAML", "requests"]
# ///
"""Pipeline 2 — character portrait generator.

Status: SKELETON. Implementation deferred until the symbol library
has canonical Aquila/Inquisition/Mechanicus art and the operator
has approved a stylistic direction (FFG-era 40K RPG sourcebook
illustration vs. something more painterly).

Purpose
-------
Produce bust / three-quarter / full-body portraits for NPCs and PCs
matching the campaign's illustrated style. Today characters live as
text-only Markdown in `Characters/`; portraits feed Kanka sidebar
images and Foundry actor avatars.

Style target: painterly, grimdark, illustrative. Operator may want
different stylistic options per character class (Inquisitor vs.
hive-ganger vs. Astropath).

Workflow & symbology
--------------------
- ComfyUI workflow: `CharacterPortraitV1.json` (to build).
- Flux txt2img + ControlNet OpenPose for body composition.
- IPAdapter for face consistency across multiple portraits of the
  same character (so a recurring NPC looks the same in every
  rendering).
- Negative prompts forbid hallucinated symbology
  ("no Imperial Aquila in robes, no Inquisitorial I, no Mechanicus
  cog — composited separately as canonical").
- Symbol-compose pass paints canonicals at the body anchors
  declared per character class:
      Inquisitor  → Inquisition I on chest, Aquila on collar
      Tech-priest → Mechanicus cog on chestplate
      Guardsman   → Skull-laurel on shoulder pad
      Preacher    → Cult Imperialis flame on lectern/robe
      …

Acceptance criteria for the first cut
-------------------------------------
1. Generate portraits for 3 PCs at bust scale.
2. Each portrait: zero hallucinated symbology in the raw render
   (validated by inspecting the negative prompt was honored).
3. One canonical Aquila composited where declared.
4. Symbol validation (canny IoU) passes for every composited symbol.
5. Operator approves stylistic match.

Output convention
-----------------
Writes to `../../Characters/portraits/<name>_<slot>.png` and
`<name>_<slot>.json` (sidecar with seed, prompt, IPAdapter ref,
symbol-compose log). The sidecar enables exact-reproduction renders
later.

Usage (planned)
---------------
    uv run generate_character_portrait.py "Inquisitor Vael" \
            --slot bust --class inquisitor --seed 42

    uv run generate_character_portrait.py "Tech-priest Hark" \
            --slot full-body --class tech-priest \
            --reference-from "../Characters/Hark_face_ref.png"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _not_implemented(reason: str) -> int:
    print(
        "generate_character_portrait.py is a SKELETON; the full pipeline is not yet wired up.",
        file=sys.stderr,
    )
    print(f"  reason: {reason}", file=sys.stderr)
    print(
        "  see the docstring at the top of this file and TODO.md "
        "(asset generation pipelines) for the build plan.",
        file=sys.stderr,
    )
    return 64


def cmd_portrait(args: argparse.Namespace) -> int:
    return _not_implemented(
        "ComfyUI workflow CharacterPortraitV1.json not yet built; "
        "Flux txt2img + ControlNet OpenPose + IPAdapter chain pending. "
        "Symbol compose pass is ready but blocked on canonical PNGs in symbols/."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="character name (matches Characters/<name>.md filename or display name)")
    ap.add_argument("--slot", choices=["bust", "three-quarter", "full-body"], default="bust")
    ap.add_argument("--class", dest="cls", required=True,
                    choices=["inquisitor", "acolyte", "tech-priest", "guardsman",
                             "preacher", "astropath", "hive-ganger", "civilian"])
    ap.add_argument("--reference-from", type=Path, default=None,
                    help="optional face reference image (IPAdapter)")
    ap.add_argument("--seed", type=int, default=0)
    ap.set_defaults(func=cmd_portrait)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
