#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "python-dotenv", "pillow", "PyYAML"]
# ///
"""Voidship deckmap LoRA corpus generator.

Reads ``lora-training-maps-voidships/manifest.yaml`` and generates one
top-down battlemap per (ship-class, deck-archetype, hull-state,
lighting) tuple. Always uses the operator-validated style reference
(``_references/style_reference_attempt3.png``) to anchor hull rendering
+ lumen-strip lighting + Imperial gothic plating.

Prompt template — built from the manifest's `defaults` block:

    Top-down battlemap of a basic Warhammer 40000 voidship,
    {category-class-name}, {archetype}.
    {hull_clause}.
    {composition}.
    Hard constraints:
    - Exactly one egress ramp.
    - No additional hatches, airlocks, observation ports, or external
      openings.
    - {empty_floors_clause}.
    Hull state: {hull_state}.
    {lighting_clause}, {lighting_variant}.
    {exclusions}.

The generator is resumable, throttled to ~1 req / 4s, cost-capped, and
prints a running estimated spend.

Usage:
    uv run gen_voidship_corpus.py --dry-run                # preview jobs
    uv run gen_voidship_corpus.py --only freighter-small   # one class
    uv run gen_voidship_corpus.py --limit 3                # smoke test
    uv run gen_voidship_corpus.py                          # full run
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
LORA_DIR = HERE / "lora-training" / "voidship-layouts"
MANIFEST_PATH = LORA_DIR / "manifest.yaml"
DEFAULT_MODEL = "gemini-2.5-flash-image"
ESTIMATED_COST_PER_IMAGE = 0.04
MIN_INTERVAL_S = 4.0


def slugify(text: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:maxlen]


@dataclass
class Job:
    category_dir: Path
    class_name: str             # display class name, e.g. "small civilian freighter"
    silhouette: str             # per-class hull silhouette descriptor
    archetype: str
    hull_state: str
    lighting: str
    composition: str
    hull_clause: str
    empty_floors_clause: str
    lighting_clause: str
    exclusions: str
    caption_trailer: str
    style_reference: Path | None
    out_png: Path
    out_txt: Path

    def prompt(self) -> str:
        return (
            f"Top-down orthographic battlemap of a Warhammer 40000 "
            f"Imperial voidship — a {self.class_name}.\n\n"
            f"HULL SILHOUETTE (most important — commit to this shape "
            f"BEFORE drawing the interior):\n{self.silhouette}.\n\n"
            f"INTERIOR LAYOUT: {self.archetype}.\n\n"
            f"HULL TREATMENT: {self.hull_clause}.\n\n"
            f"COMPOSITION: {self.composition}.\n\n"
            f"Hard constraints:\n"
            f"- Exactly one egress ramp.\n"
            f"- No additional hatches, airlocks, observation ports, or "
            f"external openings on the hull.\n"
            f"- {self.empty_floors_clause}.\n\n"
            f"Hull state: {self.hull_state}. "
            f"{self.lighting_clause}, {self.lighting}. {self.exclusions}."
        )

    def caption(self) -> str:
        # Captions exclude the boilerplate style anchor and constraint
        # block — those are constant. Trigger + class + archetype +
        # hull-state + lighting are the variable axes the LoRA learns.
        return (
            f"dh_voidship_map, top-down battlemap of {self.class_name}, "
            f"{self.archetype}, hull state: {self.hull_state}, "
            f"{self.lighting}, {self.caption_trailer}"
        )


# Map folder slug -> human-readable class name for prompt composition.
CLASS_NAMES = {
    "map-freighter-small": "small civilian freighter",
    "map-freighter-medium": "medium civilian freighter",
    "map-frigate-escort": "Imperial Navy escort frigate",
    "map-destroyer-light": "Imperial Navy light destroyer",
    "map-transport-bulk": "civilian bulk transport",
    "map-yacht-roguetrader": "Rogue Trader's private yacht",
}


def build_jobs(manifest: dict, only: str | None) -> list[Job]:
    defaults = manifest["defaults"]
    style_ref_rel = defaults.get("style_reference")
    if style_ref_rel:
        style_ref = LORA_DIR / style_ref_rel
        if not style_ref.is_file():
            raise FileNotFoundError(f"missing style reference: {style_ref}")
    else:
        style_ref = None
    silhouette_families: dict[str, str] = manifest.get("silhouette_families", {})
    silhouette_specs: dict[str, dict] = manifest.get("silhouettes", {})
    silhouettes: dict[str, str] = {}
    for folder, spec in silhouette_specs.items():
        if isinstance(spec, str):
            silhouettes[folder] = spec
            continue
        family_key = spec.get("family")
        family_clause = silhouette_families.get(family_key, "")
        modifier = spec.get("modifier", "")
        silhouettes[folder] = f"{family_clause}. {modifier}".strip()
    composition = defaults["composition"]
    hull_clause = defaults["hull_clause"]
    empty_floors_clause = defaults["empty_floors_clause"]
    lighting_clause = defaults["lighting_clause"]
    exclusions = defaults["exclusions"]
    caption_trailer = defaults["caption_trailer"]

    hull_states: list[str] = manifest["hull_states"]
    lightings: list[str] = manifest["lightings"]

    seq = 0
    jobs: list[Job] = []
    for cat in manifest["categories"]:
        folder = cat["folder"]
        if only and only not in folder:
            continue
        cat_dir = LORA_DIR / folder
        cat_dir.mkdir(parents=True, exist_ok=True)
        class_name = CLASS_NAMES.get(folder, folder.replace("map-", "").replace("-", " "))

        for a_idx, archetype in enumerate(cat["archetypes"], start=1):
            hull_state = hull_states[seq % len(hull_states)]
            lighting = lightings[seq % len(lightings)]
            seq += 1
            stem = f"{folder.replace('map-', '')}_{a_idx:02d}_{slugify(archetype, maxlen=40)}"
            out_png = cat_dir / f"{stem}.png"
            out_txt = out_png.with_suffix(".txt")
            jobs.append(Job(
                category_dir=cat_dir,
                class_name=class_name,
                silhouette=silhouettes.get(folder, ""),
                archetype=archetype,
                hull_state=hull_state,
                lighting=lighting,
                composition=composition,
                hull_clause=hull_clause,
                empty_floors_clause=empty_floors_clause,
                lighting_clause=lighting_clause,
                exclusions=exclusions,
                caption_trailer=caption_trailer,
                style_reference=style_ref,
                out_png=out_png, out_txt=out_txt,
            ))
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="substring filter on category folder")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show-prompt", action="store_true",
                    help="with --dry-run, print full composed prompts (for paste-into-Gemini-web testing)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--cost-cap", type=float, default=4.0,
                    help="abort if estimated total exceeds this many USD")
    args = ap.parse_args()

    load_dotenv(HERE / ".env")
    if "GEMINI_API_KEY" not in os.environ and not args.dry_run:
        print("missing GEMINI_API_KEY", file=sys.stderr)
        return 1

    manifest = yaml.safe_load(args.manifest.read_text())
    jobs = build_jobs(manifest, args.only)
    todo = [j for j in jobs if not j.out_png.exists()]
    skipped = len(jobs) - len(todo)

    print(f"[plan] {len(jobs)} variant slots ({len(set(j.category_dir.name for j in jobs))} ship classes)")
    print(f"[plan] {skipped} already-existing skip, {len(todo)} to generate")
    est_cost = len(todo) * ESTIMATED_COST_PER_IMAGE
    print(f"[plan] estimated cost @ ${ESTIMATED_COST_PER_IMAGE:.2f}/image = ${est_cost:.2f}")
    if args.limit:
        todo = todo[: args.limit]
        print(f"[plan] --limit {args.limit} truncates to {len(todo)} (${len(todo)*ESTIMATED_COST_PER_IMAGE:.2f})")
    if args.dry_run:
        for j in todo[:30]:
            print(f"  {j.category_dir.name}: -> {j.out_png.name}")
            if args.show_prompt:
                print("    PROMPT:")
                for line in j.prompt().splitlines():
                    print(f"      {line}")
                print("    CAPTION:")
                print(f"      {j.caption()}\n")
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

        prompt = job.prompt()
        contents: list = [prompt]
        if job.style_reference is not None:
            contents.append(Image.open(job.style_reference).convert("RGB"))

        print(f"[{n}/{len(todo)}] {job.category_dir.name} -> {job.out_png.name}", file=sys.stderr)
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
