#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "python-dotenv", "pillow", "PyYAML"]
# ///
"""Unified corpus generator — drives every LoRA's training corpus build.

A single driver replaces the previous per-LoRA `gen_*_corpus.py`
scripts. The LoRA-specific logic lives in handler classes registered
in `HANDLERS`; the throttle / retry / IMAGE_SAFETY / save loop and
all the cost-cap / dry-run / argparse plumbing is shared.

Each LoRA's manifest declares which handler to use:

    generator: <handler_name>     # at the top level of manifest.yaml

Available handlers (see registry below):
    iconography        — symbol × treatment × angle × lighting matrix
                         with reference-image conditioning per symbol.
    portrait           — archetype × gender × age × build × expression
                         × lighting matrix; optional per-category style
                         reference.
    voidship_hull      — class × hull_state × angle matrix, text-only,
                         emits empty hulls (no interior).
    voidship_layout    — class × archetype-with-zones × hull_state ×
                         lighting matrix; renders zones in spatial
                         order, text-only.

Usage:
    uv run corpus_generator.py --lora iconography --dry-run
    uv run corpus_generator.py --lora voidship-hulls --limit 3
    uv run corpus_generator.py --manifest path/to/manifest.yaml

The `--lora <name>` form auto-resolves to
`lora-training/<name>/manifest.yaml` for convenience.

All handlers share the same append-only filename discipline — output
filenames embed sequential variant indices, so reordering a manifest
re-bills the corpus on the next run. ALWAYS append to the END.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import yaml
from dotenv import load_dotenv
from PIL import Image
from google import genai

HERE = Path(__file__).resolve().parent
LORA_ROOT = HERE / "lora-training"
DEFAULT_MODEL = "gemini-2.5-flash-image"
COST_PER_IMAGE_USD = 0.04
MIN_INTERVAL_S = 4.0


def slugify(text: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:maxlen]


# ── Job ────────────────────────────────────────────────────────────

@dataclass
class Job:
    """One image-generation job. Handler-agnostic."""
    out_png: Path
    out_txt: Path
    prompt: str
    caption: str
    reference_paths: list[Path] = field(default_factory=list)
    label: str = ""           # short human-readable for log lines


# ── Handler base + registry ─────────────────────────────────────────

class Handler:
    """Per-LoRA build logic. Subclass and register in `HANDLERS`."""
    name: ClassVar[str] = ""

    def __init__(self, manifest: dict, lora_dir: Path):
        self.manifest = manifest
        self.lora_dir = lora_dir

    def build_jobs(self, only: str | None) -> list[Job]:
        raise NotImplementedError


HANDLERS: dict[str, type[Handler]] = {}


def register(cls: type[Handler]) -> type[Handler]:
    if not cls.name:
        raise ValueError(f"handler {cls.__name__} missing `name`")
    HANDLERS[cls.name] = cls
    return cls


# ── Iconography handler ─────────────────────────────────────────────

@register
class IconographyHandler(Handler):
    name = "iconography"

    @staticmethod
    def _find_reference(folder: Path) -> Path:
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

    def build_jobs(self, only: str | None) -> list[Job]:
        defaults = self.manifest.get("defaults", {})
        isolation = defaults.get(
            "isolation",
            "isolated reference plate, centered, neutral dark "
            "background, single symbol focal subject")
        shape_invariance = defaults.get(
            "shape_invariance",
            "preserve the exact heraldic silhouette of the reference "
            "image, keeping proportions and internal structure intact")
        common = list(self.manifest.get("common_treatments", []))
        common_extended = list(self.manifest.get("common_treatments_extended", []))
        angles = self.manifest.get("angles", ["front-on, dead centered"])
        lightings = self.manifest.get(
            "lighting", ["soft top-down lumen-strip lighting"])

        jobs: list[Job] = []
        for sym in self.manifest["symbols"]:
            folder_name = sym["folder"]
            if only and only not in folder_name:
                continue
            folder = self.lora_dir / folder_name
            if not folder.is_dir():
                print(f"[skip] folder missing: {folder}", file=sys.stderr)
                continue
            try:
                reference = self._find_reference(folder)
            except FileNotFoundError as exc:
                print(f"[skip] {folder_name}: {exc}", file=sys.stderr)
                continue
            trigger = sym["trigger"]
            shape = sym["shape"]
            treatments = (
                common
                + list(sym.get("extra_treatments", []))
                + common_extended)
            for idx, treatment in enumerate(treatments, start=1):
                angle = angles[(idx - 1) % len(angles)]
                lighting = lightings[(idx - 1) % len(lightings)]
                slug = slugify(treatment)
                out_png = folder / f"{trigger}_{idx:02d}_{slug}.png"
                prompt = (
                    f"{shape_invariance} ({shape}). "
                    f"Render it as {treatment}. "
                    f"View: {angle}. Lighting: {lighting}. "
                    f"{isolation}.")
                caption = f"{trigger}, {shape}, {treatment}, {isolation}"
                jobs.append(Job(
                    out_png=out_png,
                    out_txt=out_png.with_suffix(".txt"),
                    prompt=prompt, caption=caption,
                    reference_paths=[reference],
                    label=f"{folder_name} #{idx:02d}"))
        return jobs


# ── Portrait handler ────────────────────────────────────────────────

@register
class PortraitHandler(Handler):
    name = "portrait"

    @staticmethod
    def _find_style_reference(folder: Path, hint: str | None,
                              lora_dir: Path) -> Path | None:
        if hint:
            cand = folder / hint
            if cand.is_file():
                return cand
            matches = sorted(p for p in folder.glob("*.png") if hint in p.name)
            if matches:
                return matches[0]
            cross = sorted(lora_dir.glob(f"*/{hint}"))
            if cross:
                return cross[0]
            cross = sorted(p for p in lora_dir.rglob("*.png") if hint in p.name)
            if cross:
                return cross[0]
        pngs = sorted(folder.glob("*.png"))
        return pngs[0] if pngs else None

    def build_jobs(self, only: str | None) -> list[Job]:
        d = self.manifest.get("defaults", {})
        style = d.get("style", "Warhammer 40000 grimdark, oil painting style, dark palette")
        composition = d.get("composition", "head and shoulders portrait, single character focal subject")
        caption_trailer = d.get("caption_trailer", "oil painting dark palette grimdark portrait")
        genders = self.manifest.get("genders", ["man", "woman"])
        ages = self.manifest.get("ages", ["in their 30s"])
        builds = self.manifest.get("builds", ["average build"])
        expressions = self.manifest.get("expressions", ["weary"])
        lightings = self.manifest.get("lightings", ["soft top-down lumen-strip lighting"])
        sup_per = int(self.manifest.get("supplements_per_archetype", 1))

        seq = 0
        jobs: list[Job] = []
        for cat in self.manifest["categories"]:
            folder_name = cat["folder"]
            if only and only not in folder_name:
                continue
            folder = self.lora_dir / folder_name
            if not folder.is_dir():
                print(f"[skip] folder missing: {folder}", file=sys.stderr)
                continue
            style_ref = self._find_style_reference(
                folder, cat.get("style_reference"), self.lora_dir)
            for a_idx, archetype in enumerate(cat["archetypes"]):
                for v_idx in range(sup_per):
                    g = genders[seq % len(genders)]
                    a = ages[seq % len(ages)]
                    b = builds[seq % len(builds)]
                    e = expressions[seq % len(expressions)]
                    li = lightings[seq % len(lightings)]
                    seq += 1
                    slug = slugify(archetype, maxlen=40)
                    stem = f"{folder_name.replace('portrait-', '')}_{a_idx + 1:02d}_{v_idx + 1:02d}_{slug}"
                    out_png = folder / f"{stem}.png"
                    if style_ref is not None:
                        ref_clause = (
                            "Use the attached reference image ONLY as a "
                            "style anchor (painterly oil aesthetic, dark "
                            "palette, visible brushwork, lighting "
                            "treatment). DO NOT reproduce the reference's "
                            "subject, clothing, scene, pose, or "
                            "composition. The new portrait must depict an "
                            "ENTIRELY DIFFERENT subject as described "
                            "below.\n\n")
                    else:
                        ref_clause = ""
                    prompt = (
                        f"{ref_clause}"
                        f"Portrait of a {a} {b} {g}, {archetype}. "
                        f"Expression: {e}. Lighting: {li}. "
                        f"{composition}. {style}.")
                    caption = (
                        f"dh_portrait, {g} {a}, {b}, {archetype}, {e}, "
                        f"{li}, {caption_trailer}")
                    jobs.append(Job(
                        out_png=out_png,
                        out_txt=out_png.with_suffix(".txt"),
                        prompt=prompt, caption=caption,
                        reference_paths=[style_ref] if style_ref else [],
                        label=f"{folder_name} #{a_idx + 1:02d}-{v_idx + 1:02d}"))
        return jobs


# ── Voidship-shared utilities ───────────────────────────────────────

# Spatial order for walking the zone grid (bow → stern, port → starboard
# within each section). Full-width zones replace their three-cell siblings.
ZONE_ORDER = [
    "prow_full", "prow_port", "prow_center", "prow_starboard",
    "forward_full", "forward_port", "forward_center", "forward_starboard",
    "mid_full", "mid_port", "mid_center", "mid_starboard",
    "aft_full", "aft_port", "aft_center", "aft_starboard",
    "stern_full", "stern_port", "stern_center", "stern_starboard",
]


def _silhouette_clause(folder: str, manifest: dict) -> str:
    families = manifest.get("silhouette_families", {})
    spec = manifest.get("silhouettes", {}).get(folder)
    if spec is None:
        return ""
    if isinstance(spec, str):
        return spec
    family = families.get(spec.get("family"), "")
    modifier = spec.get("modifier", "")
    return f"{family}. {modifier}".strip(". ").strip()


def _render_zones_block(zones: dict, manifest: dict) -> str:
    """Walk the zone grid in spatial order; render present zones into
    a structured prompt block. Full-width zones are emitted as one
    line; if a `*_full` is set we skip the section's three lateral
    cells. Zones absent from the dict don't appear in the prompt.
    """
    grid = manifest.get("zone_grid", {})
    out: list[str] = []
    sections = ["prow", "forward", "mid", "aft", "stern"]
    for sec in sections:
        full_key = f"{sec}_full"
        if full_key in zones:
            pos = grid.get(full_key, full_key)
            out.append(f"  - {full_key} ({pos}): {zones[full_key]}.")
            continue
        for lane in ("port", "center", "starboard"):
            key = f"{sec}_{lane}"
            if key in zones:
                pos = grid.get(key, key)
                out.append(f"  - {key} ({pos}): {zones[key]}.")
    return "\n".join(out)


def _zone_summary(zones: dict) -> str:
    """Compact one-liner of which zones are present, for the caption."""
    parts: list[str] = []
    for k in ZONE_ORDER:
        if k in zones:
            head = re.sub(r"\s+", " ", zones[k]).strip()[:60]
            parts.append(f"{k}={head}")
    return " | ".join(parts)


# ── Voidship hull handler (Stage 1) ─────────────────────────────────

@register
class VoidshipHullHandler(Handler):
    name = "voidship_hull"

    def build_jobs(self, only: str | None) -> list[Job]:
        d = self.manifest["defaults"]
        composition = d["composition"]
        hull_clause = d["hull_clause"]
        empty_interior_clause = d["empty_interior_clause"]
        exclusions = d["exclusions"]
        caption_trailer = d.get("caption_trailer", "")
        trigger = d.get("trigger", "dh_voidship_hull")
        hull_states = self.manifest["hull_states"]
        angles = self.manifest.get("angles", ["top-down orthographic"])

        seq = 0
        jobs: list[Job] = []
        for cat in self.manifest["categories"]:
            folder_name = cat["folder"]
            if only and only not in folder_name:
                continue
            cat_dir = self.lora_dir / folder_name
            cat_dir.mkdir(parents=True, exist_ok=True)
            class_name = cat.get("class_name") or folder_name.replace(
                "hull-", "").replace("-", " ")
            silhouette = _silhouette_clause(folder_name, self.manifest)

            for v_idx in range(int(cat.get("variants", len(hull_states)))):
                hull_state = hull_states[seq % len(hull_states)]
                angle = angles[seq % len(angles)]
                seq += 1
                stem = f"{folder_name.replace('hull-', '')}_{v_idx + 1:02d}_{slugify(hull_state, 32)}"
                out_png = cat_dir / f"{stem}.png"
                prompt = (
                    f"Top-down orthographic battlemap-grade silhouette "
                    f"of a Warhammer 40000 Imperial voidship — "
                    f"a {class_name}. EMPTY HULL ONLY: there are NO "
                    f"interior rooms, NO furniture, NO doorways visible "
                    f"from this view. The hull is a closed solid "
                    f"silhouette with the exterior plating shown from "
                    f"directly above.\n\n"
                    f"HULL SILHOUETTE (most important — commit to this "
                    f"shape and render it as a closed outline):\n"
                    f"{silhouette}.\n\n"
                    f"HULL TREATMENT: {hull_clause}.\n\n"
                    f"COMPOSITION: {composition}.\n\n"
                    f"INTERIOR: {empty_interior_clause}.\n\n"
                    f"View: {angle}. Hull state: {hull_state}. "
                    f"{exclusions}.")
                caption = (
                    f"{trigger}, {class_name}, hull state: {hull_state}, "
                    f"{angle}, {caption_trailer}").strip(", ").strip()
                jobs.append(Job(
                    out_png=out_png,
                    out_txt=out_png.with_suffix(".txt"),
                    prompt=prompt, caption=caption,
                    label=f"{folder_name} #{v_idx + 1:02d}"))
        return jobs


# ── Voidship layout handler (Stage 2) ───────────────────────────────

@register
class VoidshipLayoutHandler(Handler):
    name = "voidship_layout"

    def build_jobs(self, only: str | None) -> list[Job]:
        d = self.manifest["defaults"]
        composition = d["composition"]
        hull_clause = d["hull_clause"]
        empty_floors_clause = d["empty_floors_clause"]
        lighting_clause = d["lighting_clause"]
        exclusions = d["exclusions"]
        caption_trailer = d.get("caption_trailer", "")
        trigger = d.get("trigger", "dh_layout")
        hull_states = self.manifest["hull_states"]
        lightings = self.manifest["lightings"]

        seq = 0
        jobs: list[Job] = []
        for cat in self.manifest["categories"]:
            folder_name = cat["folder"]
            if only and only not in folder_name:
                continue
            cat_dir = self.lora_dir / folder_name
            cat_dir.mkdir(parents=True, exist_ok=True)
            class_name = cat.get("class_name") or folder_name.replace(
                "map-", "").replace("-", " ")
            silhouette = _silhouette_clause(folder_name, self.manifest)

            for archetype in cat["archetypes"]:
                hull_state = hull_states[seq % len(hull_states)]
                lighting = lightings[seq % len(lightings)]
                seq += 1
                if isinstance(archetype, str):
                    arch_id = slugify(archetype, 24)
                    arch_name = arch_id
                    zones_block = f"  {archetype}"
                    zone_summary = arch_id
                    egress = "single rear cargo / personnel egress as the only external opening"
                else:
                    arch_id = archetype["id"]
                    arch_name = archetype.get("name", arch_id)
                    zones_block = _render_zones_block(
                        archetype.get("zones", {}), self.manifest)
                    zone_summary = _zone_summary(archetype.get("zones", {}))
                    egress = archetype.get(
                        "egress",
                        "single rear egress, only external opening")
                stem = f"{folder_name.replace('map-', '')}_{slugify(arch_id, 40)}"
                out_png = cat_dir / f"{stem}.png"
                prompt = (
                    f"Top-down orthographic battlemap of a Warhammer "
                    f"40000 Imperial voidship — a {class_name}.\n\n"
                    f"HULL SILHOUETTE (most important — commit to this "
                    f"shape BEFORE drawing the interior):\n{silhouette}.\n\n"
                    f"INTERIOR LAYOUT — {arch_name}. Walk the hull "
                    f"bow-to-stern (LEFT to RIGHT), port-to-starboard "
                    f"(TOP to BOTTOM); zones described in spatial order:\n"
                    f"{zones_block}\n\n"
                    f"EGRESS: {egress}.\n\n"
                    f"HULL TREATMENT: {hull_clause}.\n\n"
                    f"COMPOSITION: {composition}.\n\n"
                    f"Hard constraints:\n"
                    f"- Exactly one egress (named above).\n"
                    f"- No additional hatches, airlocks, observation "
                    f"ports, or external openings on the hull.\n"
                    f"- {empty_floors_clause}.\n\n"
                    f"Hull state: {hull_state}. "
                    f"{lighting_clause}, {lighting}. {exclusions}.")
                caption = (
                    f"{trigger}, {class_name}, {arch_id} ({arch_name}), "
                    f"zones: {zone_summary}, hull state: {hull_state}, "
                    f"{lighting}, {caption_trailer}"
                ).strip(", ").strip()
                jobs.append(Job(
                    out_png=out_png,
                    out_txt=out_png.with_suffix(".txt"),
                    prompt=prompt, caption=caption,
                    label=f"{folder_name}/{arch_id}"))
        return jobs


# ── Shared run loop ─────────────────────────────────────────────────

def run_jobs(jobs: list[Job], args: argparse.Namespace,
             client: genai.Client | None) -> int:
    todo = [j for j in jobs if not j.out_png.exists()]
    skipped = len(jobs) - len(todo)
    print(f"[plan] {len(jobs)} variant slots — "
          f"{skipped} already exist (skipped), {len(todo)} to generate")
    est = len(todo) * COST_PER_IMAGE_USD
    print(f"[plan] estimated cost @ ${COST_PER_IMAGE_USD:.2f}/image = ${est:.2f}")
    if args.limit:
        todo = todo[: args.limit]
        print(f"[plan] --limit {args.limit} truncates to {len(todo)} "
              f"(${len(todo) * COST_PER_IMAGE_USD:.2f})")
    if args.dry_run:
        for j in todo[:30]:
            print(f"  [{j.label}] -> {j.out_png}")
            if args.show_prompt:
                for line in j.prompt.splitlines():
                    print(f"      {line}")
                print(f"      caption: {j.caption}")
                if j.reference_paths:
                    for r in j.reference_paths:
                        print(f"      ref: {r}")
                print()
        if len(todo) > 30:
            print(f"  ... ({len(todo) - 30} more)")
        return 0
    if est > args.cost_cap:
        print(f"[abort] estimated ${est:.2f} > cap ${args.cost_cap:.2f}",
              file=sys.stderr)
        return 2

    assert client is not None
    last_call = 0.0
    successes = 0
    failures: list[tuple[Job, str]] = []
    spent = 0.0
    for n, job in enumerate(todo, 1):
        elapsed = time.monotonic() - last_call
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)
        last_call = time.monotonic()

        contents: list = [job.prompt]
        for ref in job.reference_paths:
            contents.append(Image.open(ref).convert("RGB"))

        print(f"[{n}/{len(todo)}] {job.label} -> {job.out_png.name}",
              file=sys.stderr)
        try:
            resp = client.models.generate_content(model=args.model, contents=contents)
        except Exception as e:
            print(f"  [fail] {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
            failures.append((job, str(e)[:200]))
            continue
        cand = (resp.candidates or [None])[0]
        if cand is None or getattr(cand, "content", None) is None:
            fr = getattr(cand, "finish_reason", None) if cand else None
            br = getattr(getattr(resp, "prompt_feedback", None),
                         "block_reason", None)
            print(f"  [fail] no content (finish_reason={fr}, "
                  f"block_reason={br})", file=sys.stderr)
            failures.append((job, f"no content / finish_reason={fr}"))
            continue
        png = None
        for part in cand.content.parts or []:
            if part.inline_data and part.inline_data.data:
                png = part.inline_data.data
                break
            elif part.text:
                print(f"  [text] {part.text[:160]}", file=sys.stderr)
        if not png:
            fr = getattr(cand, "finish_reason", None)
            print(f"  [fail] no image part (finish_reason={fr})",
                  file=sys.stderr)
            failures.append((job, f"no image part / finish_reason={fr}"))
            continue

        job.out_png.parent.mkdir(parents=True, exist_ok=True)
        job.out_png.write_bytes(png)
        job.out_txt.write_text(job.caption + "\n")
        successes += 1
        spent += COST_PER_IMAGE_USD
        print(f"  [ok] saved {len(png)} bytes (cum est ${spent:.2f})",
              file=sys.stderr)

    print(f"\n[done] {successes}/{len(todo)} successes, "
          f"{len(failures)} failures, est spent ${spent:.2f}")
    if failures:
        print("[done] failures:")
        for job, err in failures[:10]:
            print(f"  {job.out_png.name}: {err}")
    return 0


# ── Manifest resolution ─────────────────────────────────────────────

def resolve_manifest(args: argparse.Namespace) -> tuple[Path, Path]:
    """Return (manifest_path, lora_dir)."""
    if args.manifest:
        mp = args.manifest.resolve()
        return mp, mp.parent
    if args.lora:
        lora_dir = LORA_ROOT / args.lora
        mp = lora_dir / "manifest.yaml"
        if not mp.is_file():
            raise FileNotFoundError(f"no manifest at {mp}")
        return mp, lora_dir
    raise SystemExit("specify --lora <name> or --manifest <path>")


# ── Main ────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lora", help="LoRA subfolder name under lora-training/ "
                                   "(e.g. iconography, voidship-hulls)")
    ap.add_argument("--manifest", type=Path,
                    help="explicit manifest.yaml path (overrides --lora)")
    ap.add_argument("--only", help="substring filter on subfolder name")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N successful generations")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show-prompt", action="store_true",
                    help="with --dry-run, print full composed prompts")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--cost-cap", type=float, default=8.0,
                    help="abort if estimated total exceeds this many USD")
    args = ap.parse_args()

    load_dotenv(HERE / ".env")
    manifest_path, lora_dir = resolve_manifest(args)
    manifest = yaml.safe_load(manifest_path.read_text())

    handler_name = manifest.get("generator")
    if not handler_name:
        raise SystemExit(f"manifest {manifest_path} missing top-level "
                         f"`generator: <name>` field. Available handlers: "
                         f"{sorted(HANDLERS)}")
    if handler_name not in HANDLERS:
        raise SystemExit(f"unknown generator {handler_name!r}; "
                         f"registered: {sorted(HANDLERS)}")
    handler = HANDLERS[handler_name](manifest, lora_dir)

    print(f"[gen] handler={handler_name} manifest={manifest_path}")
    print(f"[gen] lora_dir={lora_dir}")

    jobs = handler.build_jobs(only=args.only)

    client: genai.Client | None = None
    if not args.dry_run:
        if "GEMINI_API_KEY" not in os.environ:
            print("missing GEMINI_API_KEY", file=sys.stderr)
            return 1
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    return run_jobs(jobs, args, client)


if __name__ == "__main__":
    sys.exit(main())
