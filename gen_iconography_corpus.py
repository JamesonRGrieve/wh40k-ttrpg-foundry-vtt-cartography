#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "python-dotenv", "pillow", "PyYAML"]
# ///
"""40K iconography LoRA corpus generator.

Reads ``lora-training/manifest.yaml`` and generates per-symbol material
variants via Gemini 2.5 Flash Image with **reference image conditioning**.
Each symbol's existing ``*_isolated.png`` (or first .png in the folder) is
passed as the canonical-shape reference; the per-variant prompt drives
material / state / context. This guarantees shape fidelity (the
canonical silhouette is supplied, not hoped-for) while letting the model
vary surface treatment.

Output naming: ``<folder>/<trigger>_<NN>_<material_slug>.png`` plus
sibling ``.txt`` caption with the trigger token + shape clause +
material clause. Resumable — files that already exist are skipped.

Usage:
    uv run gen_iconography_corpus.py                    # all symbols
    uv run gen_iconography_corpus.py --only aquilla     # one folder slug
    uv run gen_iconography_corpus.py --dry-run          # show what would be generated
    uv run gen_iconography_corpus.py --limit 10         # stop after N successful generations

The script throttles itself to ~1 request / 4 s to stay well under the
gemini-2.5-flash-image rate limit and prints a running cost estimate
(@ $0.04 / image, conservative).
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
LORA_DIR = HERE / "lora-training"
MANIFEST_PATH = LORA_DIR / "manifest.yaml"
DEFAULT_MODEL = "gemini-2.5-flash-image"
ESTIMATED_COST_PER_IMAGE = 0.04  # USD; conservative
MIN_INTERVAL_S = 4.0


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:48]


def find_reference(folder: Path) -> Path:
    """Pick the canonical-shape reference for a symbol folder.

    Prefers a file ending in `_isolated.png`. Falls back to the first
    `.png` (excluding any already-generated variant files which carry
    the `_NN_` numbered suffix).
    """
    isolated = sorted(folder.glob("*_isolated.png"))
    if isolated:
        return isolated[0]
    candidates = [
        p for p in sorted(folder.glob("*.png"))
        if not re.match(r".+_\d{2}_.+\.png$", p.name)
    ]
    if not candidates:
        raise FileNotFoundError(f"no reference image in {folder}")
    return candidates[0]


@dataclass
class Job:
    folder: Path
    trigger: str
    shape: str
    treatment: str          # material + context phrase
    angle: str              # viewing angle phrase
    lighting: str           # lighting phrase
    isolation: str
    shape_invariance: str
    reference: Path
    out_png: Path
    out_txt: Path

    def caption(self) -> str:
        # Caption omits angle / lighting so the LoRA learns to bind the
        # trigger to the SHAPE and the treatment vocabulary, while
        # angle and lighting variations teach view-invariance without
        # entering the bound concept.
        return f"{self.trigger}, {self.shape}, {self.treatment}, {self.isolation}"


def build_jobs(manifest: dict, only: str | None) -> list[Job]:
    defaults = manifest.get("defaults", {})
    isolation = defaults.get("isolation", "isolated reference plate, centered, "
                                          "neutral dark background, single symbol focal subject")
    shape_invariance = defaults.get("shape_invariance",
        "preserve the exact heraldic silhouette of the reference image, "
        "keeping proportions and internal structure intact")
    common_treatments: list[str] = manifest.get("common_treatments", [])
    angles: list[str] = manifest.get("angles", ["front-on, dead centered"])
    lightings: list[str] = manifest.get("lighting", ["soft top-down lumen-strip lighting"])

    jobs: list[Job] = []
    for sym in manifest["symbols"]:
        folder_name = sym["folder"]
        if only and only not in folder_name:
            continue
        folder = LORA_DIR / folder_name
        if not folder.is_dir():
            print(f"[skip] folder missing: {folder}", file=sys.stderr)
            continue
        try:
            reference = find_reference(folder)
        except FileNotFoundError as exc:
            print(f"[skip] {folder_name}: {exc}", file=sys.stderr)
            continue
        trigger = sym["trigger"]
        shape = sym["shape"]
        treatments = list(common_treatments) + list(sym.get("extra_treatments", []))
        for idx, treatment in enumerate(treatments, start=1):
            angle = angles[(idx - 1) % len(angles)]
            lighting = lightings[(idx - 1) % len(lightings)]
            slug = slugify(treatment)
            out_png = folder / f"{trigger}_{idx:02d}_{slug}.png"
            out_txt = out_png.with_suffix(".txt")
            jobs.append(Job(
                folder=folder, trigger=trigger, shape=shape,
                treatment=treatment, angle=angle, lighting=lighting,
                isolation=isolation, shape_invariance=shape_invariance,
                reference=reference, out_png=out_png, out_txt=out_txt,
            ))
    return jobs


def build_prompt(job: Job) -> str:
    return (
        f"{job.shape_invariance} ({job.shape}). "
        f"Render it as {job.treatment}. "
        f"View: {job.angle}. Lighting: {job.lighting}. "
        f"{job.isolation}."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="substring filter on folder name (e.g. 'aquilla')")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N successful generations (cost-cap safety)")
    ap.add_argument("--dry-run", action="store_true", help="show jobs without generating")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--cost-cap", type=float, default=15.0,
                    help="abort if estimated total cost exceeds this many USD")
    args = ap.parse_args()

    load_dotenv(HERE / ".env")
    if "GEMINI_API_KEY" not in os.environ:
        print("missing GEMINI_API_KEY (load .env or set in env)", file=sys.stderr)
        return 1

    manifest = yaml.safe_load(args.manifest.read_text())
    jobs = build_jobs(manifest, args.only)
    todo = [j for j in jobs if not j.out_png.exists()]
    skipped = len(jobs) - len(todo)

    print(f"[plan] {len(jobs)} variant slots across {len(set(j.folder.name for j in jobs))} symbols")
    print(f"[plan] {skipped} already-existing (resumable skip), {len(todo)} to generate")
    est_cost = len(todo) * ESTIMATED_COST_PER_IMAGE
    print(f"[plan] estimated cost @ ${ESTIMATED_COST_PER_IMAGE:.2f}/image = ${est_cost:.2f}")
    if args.limit:
        todo = todo[: args.limit]
        print(f"[plan] --limit {args.limit} truncates to {len(todo)} (${len(todo)*ESTIMATED_COST_PER_IMAGE:.2f})")
    if args.dry_run:
        for j in todo[:30]:
            print(f"  {j.folder.name} <- ref={j.reference.name}  ->  {j.out_png.name}")
        if len(todo) > 30:
            print(f"  ... ({len(todo)-30} more)")
        return 0
    if est_cost > args.cost_cap:
        print(f"[abort] estimated cost ${est_cost:.2f} exceeds --cost-cap ${args.cost_cap:.2f}",
              file=sys.stderr)
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

        ref_im = Image.open(job.reference).convert("RGB")
        prompt = build_prompt(job)
        print(f"[{n}/{len(todo)}] {job.folder.name} -> {job.out_png.name}", file=sys.stderr)
        try:
            resp = client.models.generate_content(
                model=args.model, contents=[prompt, ref_im],
            )
        except Exception as e:
            print(f"  [fail] {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
            failures.append((job, str(e)[:200]))
            continue
        png_bytes = None
        for part in resp.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                png_bytes = part.inline_data.data
                break
            elif part.text:
                print(f"  [text] {part.text[:160]}", file=sys.stderr)
        if not png_bytes:
            print("  [fail] no image part in response", file=sys.stderr)
            failures.append((job, "no image part"))
            continue
        job.out_png.write_bytes(png_bytes)
        job.out_txt.write_text(job.caption() + "\n")
        successes += 1
        spent += ESTIMATED_COST_PER_IMAGE
        print(f"  [ok] saved {len(png_bytes)} bytes (cum est ${spent:.2f})", file=sys.stderr)

    print(f"\n[done] {successes}/{len(todo)} successes, {len(failures)} failures",
          f" -- est spent ${spent:.2f}")
    if failures:
        print("[done] failures:")
        for job, err in failures[:10]:
            print(f"  {job.out_png.name}: {err}")
    return 0 if not failures else (0 if successes else 1)


if __name__ == "__main__":
    sys.exit(main())
