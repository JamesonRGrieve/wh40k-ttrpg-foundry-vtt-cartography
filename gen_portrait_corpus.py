#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "python-dotenv", "pillow", "PyYAML"]
# ///
"""DH2 character portrait LoRA corpus generator.

Sibling to ``gen_iconography_corpus.py``. Two architectural differences:

1. **No reference-image conditioning is required**, but each category
   *can* declare a `style_reference` (path or filename pattern) that
   the generator passes alongside the prompt. This lets Gemini lock
   onto the existing deployed campaign style (Edric Family / Pell
   Osric / test_inquisitor refs) when filling out new archetypes.

2. **Subject is varied along career × gender × age × build × expression
   × lighting axes** instead of treatment/material/etc. Each archetype
   in a category is composed with a unique (gender, age, build,
   expression, lighting) tuple sampled round-robin from global pools.

Outputs land at ``lora-training-portraits/<folder>/<stem>.png`` with
sibling ``.txt`` captions. The generator is resumable — files that
already exist are skipped.

Usage:
    uv run gen_portrait_corpus.py                    # all categories
    uv run gen_portrait_corpus.py --only ecclesiarchy
    uv run gen_portrait_corpus.py --dry-run
    uv run gen_portrait_corpus.py --limit 10
    uv run gen_portrait_corpus.py --supplements-per-archetype 1
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
from PIL import Image
from google import genai

HERE = Path(__file__).resolve().parent
LORA_DIR = HERE / "lora-training" / "portraits"
MANIFEST_PATH = LORA_DIR / "manifest.yaml"
DEFAULT_MODEL = "gemini-2.5-flash-image"
ESTIMATED_COST_PER_IMAGE = 0.04
MIN_INTERVAL_S = 4.0


def slugify(text: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:maxlen]


def find_style_reference(category_dir: Path, hint: str | None = None) -> Path | None:
    """Pick a style reference for the category.

    If a hint is provided (filename or substring), prefer that. Otherwise
    take the first .png in the folder. Returns None if the folder is
    empty (caller falls back to text-only generation).
    """
    if hint:
        # Exact filename match first
        candidate = category_dir / hint
        if candidate.is_file():
            return candidate
        # Substring match
        matches = sorted(p for p in category_dir.glob("*.png") if hint in p.name)
        if matches:
            return matches[0]
        # Cross-folder lookup (e.g. style ref from another category)
        cross = sorted(LORA_DIR.glob(f"*/{hint}"))
        if cross:
            return cross[0]
        cross = sorted(p for p in LORA_DIR.rglob("*.png") if hint in p.name)
        if cross:
            return cross[0]
    # Default: first .png in this category folder
    pngs = sorted(category_dir.glob("*.png"))
    return pngs[0] if pngs else None


@dataclass
class Job:
    category_dir: Path
    archetype: str
    gender: str
    age: str
    build: str
    expression: str
    lighting: str
    style: str
    composition: str
    caption_trailer: str
    style_reference: Path | None
    out_png: Path
    out_txt: Path

    def prompt(self) -> str:
        # Compose a full prompt. Style anchors stay in the prompt only,
        # not the caption — they are constant across every image.
        if self.style_reference is not None:
            ref_clause = (
                "Use the attached reference image ONLY as a style anchor "
                "(painterly oil aesthetic, dark palette, visible brushwork, "
                "lighting treatment). DO NOT reproduce the reference's "
                "subject, clothing, scene, pose, or composition. "
                "The new portrait must depict an ENTIRELY DIFFERENT "
                "subject as described below.\n\n"
            )
        else:
            ref_clause = ""
        return (
            f"{ref_clause}"
            f"Portrait of a {self.age} {self.build} {self.gender}, "
            f"{self.archetype}. Expression: {self.expression}. "
            f"Lighting: {self.lighting}. {self.composition}. {self.style}."
        )

    def caption(self) -> str:
        return (
            f"dh_portrait, {self.gender} {self.age}, {self.build}, "
            f"{self.archetype}, {self.expression}, {self.lighting}, "
            f"{self.caption_trailer}"
        )


def build_jobs(manifest: dict, only: str | None, supplements_per_archetype: int) -> list[Job]:
    defaults = manifest.get("defaults", {})
    style = defaults.get("style", "Warhammer 40000 grimdark, oil painting style, dark palette")
    composition = defaults.get("composition", "head and shoulders portrait, single character focal subject")
    caption_trailer = defaults.get("caption_trailer", "oil painting dark palette grimdark portrait")

    genders: list[str] = manifest.get("genders", ["man", "woman"])
    ages: list[str] = manifest.get("ages", ["in their 30s"])
    builds: list[str] = manifest.get("builds", ["average build"])
    expressions: list[str] = manifest.get("expressions", ["weary"])
    lightings: list[str] = manifest.get("lightings", ["soft top-down lumen-strip lighting"])

    # Sequence index used for round-robin across all archetypes globally,
    # so two archetypes back-to-back don't end up with the same axis tuple.
    seq = 0
    jobs: list[Job] = []
    for cat in manifest["categories"]:
        folder = cat["folder"]
        if only and only not in folder:
            continue
        cat_dir = LORA_DIR / folder
        if not cat_dir.is_dir():
            print(f"[skip] folder missing: {cat_dir}", file=sys.stderr)
            continue
        style_ref_hint = cat.get("style_reference")
        style_ref = find_style_reference(cat_dir, style_ref_hint)

        archetypes = cat["archetypes"]
        for a_idx, archetype in enumerate(archetypes):
            for v_idx in range(supplements_per_archetype):
                gender = genders[seq % len(genders)]
                age = ages[seq % len(ages)]
                build = builds[seq % len(builds)]
                expression = expressions[seq % len(expressions)]
                lighting = lightings[seq % len(lightings)]
                seq += 1

                slug = slugify(archetype, maxlen=40)
                out_stem = f"{folder.replace('portrait-', '')}_{a_idx + 1:02d}_{v_idx + 1:02d}_{slug}"
                out_png = cat_dir / f"{out_stem}.png"
                out_txt = out_png.with_suffix(".txt")
                jobs.append(Job(
                    category_dir=cat_dir, archetype=archetype,
                    gender=gender, age=age, build=build,
                    expression=expression, lighting=lighting,
                    style=style, composition=composition,
                    caption_trailer=caption_trailer,
                    style_reference=style_ref,
                    out_png=out_png, out_txt=out_txt,
                ))
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="substring filter on category folder (e.g. 'ecclesiarchy')")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N successful generations")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--cost-cap", type=float, default=8.0,
                    help="abort if estimated total cost exceeds this many USD")
    ap.add_argument("--supplements-per-archetype", type=int, default=1,
                    help="how many synthetic supplements to generate per archetype "
                         "(1 ≈ 1 new image per archetype line in the manifest)")
    args = ap.parse_args()

    load_dotenv(HERE / ".env")
    if "GEMINI_API_KEY" not in os.environ:
        print("missing GEMINI_API_KEY", file=sys.stderr)
        return 1

    manifest = yaml.safe_load(args.manifest.read_text())
    jobs = build_jobs(manifest, args.only, args.supplements_per_archetype)
    todo = [j for j in jobs if not j.out_png.exists()]
    skipped = len(jobs) - len(todo)

    print(f"[plan] {len(jobs)} variant slots ({len(set(j.category_dir.name for j in jobs))} categories)")
    print(f"[plan] {skipped} already-existing skip, {len(todo)} to generate")
    est_cost = len(todo) * ESTIMATED_COST_PER_IMAGE
    print(f"[plan] estimated cost @ ${ESTIMATED_COST_PER_IMAGE:.2f}/image = ${est_cost:.2f}")
    if args.limit:
        todo = todo[: args.limit]
        print(f"[plan] --limit {args.limit} truncates to {len(todo)} (${len(todo)*ESTIMATED_COST_PER_IMAGE:.2f})")
    if args.dry_run:
        for j in todo[:30]:
            ref = j.style_reference.name if j.style_reference else "<text-only>"
            print(f"  {j.category_dir.name}: ref={ref} -> {j.out_png.name}")
        if len(todo) > 30:
            print(f"  ... ({len(todo)-30} more)")
        return 0
    if est_cost > args.cost_cap:
        print(f"[abort] estimated ${est_cost:.2f} > cap ${args.cost_cap:.2f}", file=sys.stderr)
        return 2

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    last_call = 0.0
    successes = 0
    failures: list[tuple[Job, str]] = []
    spent = 0.0

    for n, job in enumerate(todo, 1):
        elapsed = time.monotonic() - last_call
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)
        last_call = time.monotonic()

        contents: list = [job.prompt()]
        if job.style_reference is not None:
            contents.append(Image.open(job.style_reference).convert("RGB"))

        ref_label = job.style_reference.name if job.style_reference else "<text-only>"
        print(f"[{n}/{len(todo)}] {job.category_dir.name} ref={ref_label} -> {job.out_png.name}",
              file=sys.stderr)
        try:
            resp = client.models.generate_content(model=args.model, contents=contents)
        except Exception as e:
            print(f"  [fail] {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
            failures.append((job, str(e)[:200]))
            continue
        cand = (resp.candidates or [None])[0]
        if cand is None:
            block_reason = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
            print(f"  [fail] no candidates (block_reason={block_reason})", file=sys.stderr)
            failures.append((job, f"no candidates / block_reason={block_reason}"))
            continue
        if getattr(cand, "content", None) is None:
            finish = getattr(cand, "finish_reason", None)
            print(f"  [fail] content None (finish_reason={finish})", file=sys.stderr)
            failures.append((job, f"content None / finish_reason={finish}"))
            continue
        png_bytes = None
        for part in cand.content.parts or []:
            if part.inline_data and part.inline_data.data:
                png_bytes = part.inline_data.data
                break
            elif part.text:
                print(f"  [text] {part.text[:160]}", file=sys.stderr)
        if not png_bytes:
            finish = getattr(cand, "finish_reason", None)
            print(f"  [fail] no image part (finish_reason={finish})", file=sys.stderr)
            failures.append((job, f"no image part / finish_reason={finish}"))
            continue
        job.out_png.write_bytes(png_bytes)
        job.out_txt.write_text(job.caption() + "\n")
        successes += 1
        spent += ESTIMATED_COST_PER_IMAGE
        print(f"  [ok] saved {len(png_bytes)} bytes (cum est ${spent:.2f})", file=sys.stderr)

    print(f"\n[done] {successes}/{len(todo)} successes, {len(failures)} failures, est spent ${spent:.2f}")
    if failures:
        print("[done] failures:")
        for job, err in failures[:10]:
            print(f"  {job.out_png.name}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
