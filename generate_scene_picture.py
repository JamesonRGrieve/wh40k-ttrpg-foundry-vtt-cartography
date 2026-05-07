#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "opencv-python-headless", "PyYAML", "requests"]
# ///
"""Pipeline 3 — scene picture generator.

Establishing shots, lore illustrations, document handouts. Uses the
existing Flux txt2img workflow (BattlemapInteriorV1.json) with
scene-specific prompts + anti-symbol negatives + a symbol_compose
pass after render so canonical Imperial iconography is pasted, never
rendered by diffusion.

Symbol-preservation flow:
1. Flux render with negatives forbidding Aquila / I / cog / etc.
2. Optional symbol composite pass at named anchor points.
3. canny-IoU validation per composite (flagged if drift exceeds
   the symbol's metadata threshold).

Usage:
    uv run generate_scene_picture.py \\
        --location "[[Hab District 4]]" --aspect 16:9 \\
        --mood "grimdark, smog, midday" \\
        --output Lore/handouts/hab_4_establishing.png

    uv run generate_scene_picture.py \\
        --location "[[District 4 Chapel]]" --aspect 4:3 \\
        --mood "candlelit, somber, post-service" \\
        --symbol "aquila:apse_back,large" \\
        --symbol "adeptus_ministorum:lectern_front,small" \\
        --output Lore/handouts/district_4_chapel.png
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Reuse the existing battlemap driver helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_battlemap import (  # type: ignore[import-not-found]
    _extend_negative,
    load_template,
    poll_history,
    set_dimensions,
    set_prompt,
    set_save_prefix,
    set_seed,
    submit_prompt,
    _saved_images_from_history,
    _download_first,
)
from symbol_compose import (  # type: ignore[import-not-found]
    SymbolPlacement,
    compose_symbols,
    load_symbol,
    validate_symbol,
)

import uuid
from PIL import Image

HERE = Path(__file__).resolve().parent

ASPECT_TO_DIMS: dict[str, tuple[int, int]] = {
    "16:9": (1280, 720),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "1:1": (1024, 1024),
    "21:9": (1536, 656),
    "9:16": (720, 1280),
}

# Anti-symbol negative — forbids Flux from rendering canonical
# iconography. Symbols are composited separately by symbol_compose.
SCENE_NEG_T5 = (
    "Imperial Aquila, two-headed eagle emblem, Inquisition I, Inquisitorial rosette, "
    "Mechanicus cog, half-cog half-skull, Adepta Sororitas fleur-de-lys, "
    "Adeptus Custodes lightning bolt, Astra Militarum winged skull, "
    "Adeptus Ministorum sigil, fleur-de-lys, ornate religious symbology, "
    "specific religious sigils, branded faction emblems, "
    "anime, cartoon, cel shading, low resolution, watermark, text, signature"
)
SCENE_NEG_CLIP_L = (
    "Imperial Aquila, eagle emblem, Inquisition I, Mechanicus cog, sigils"
)

# Per-aspect anchor map: where each symbol slot lives in image coords.
# Anchors are FRACTIONS of (width, height) so they scale with aspect.
# Each entry: anchor_name -> (cx_frac, cy_frac, default_size_frac)
DEFAULT_ANCHORS: dict[str, tuple[float, float, float]] = {
    # Architectural / scenic placements
    "apse_back": (0.50, 0.30, 0.18),
    "altar_face": (0.50, 0.55, 0.12),
    "lectern_front": (0.40, 0.65, 0.10),
    "door_keystone": (0.50, 0.18, 0.10),
    "banner_field": (0.30, 0.40, 0.20),
    "ship_hull_marking": (0.50, 0.30, 0.30),
    # Generic
    "center": (0.50, 0.50, 0.20),
    "top_left": (0.20, 0.20, 0.12),
    "top_right": (0.80, 0.20, 0.12),
    "bottom_left": (0.20, 0.80, 0.12),
    "bottom_right": (0.80, 0.80, 0.12),
}

SIZE_SCALE: dict[str, float] = {
    "small": 0.6,
    "medium": 1.0,
    "large": 1.5,
    "xlarge": 2.0,
}


@dataclass
class SymbolSpec:
    name: str
    anchor: str
    size_label: str = "medium"


def parse_symbol_spec(spec: str) -> SymbolSpec:
    """`name:anchor[,size_label]` -> SymbolSpec."""
    if ":" not in spec:
        raise argparse.ArgumentTypeError(f"--symbol expects NAME:anchor[,size], got {spec!r}")
    name, body = spec.split(":", 1)
    parts = [p.strip() for p in body.split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError(f"--symbol body needs anchor, got {spec!r}")
    anchor = parts[0]
    size = parts[1] if len(parts) >= 2 else "medium"
    if size not in SIZE_SCALE:
        raise argparse.ArgumentTypeError(
            f"size must be one of {list(SIZE_SCALE)}, got {size!r}"
        )
    return SymbolSpec(name=name, anchor=anchor, size_label=size)


def build_scene_prompt(*, location: str, mood: str) -> tuple[str, str]:
    """Compose the t5xxl + clip_l prompt for a scene render.

    The location is a wikilink-style id (e.g. `[[District 4 Chapel]]`)
    that we strip and use as a noun phrase. Mood is operator prose.
    """
    clean_loc = location.strip().lstrip("[").rstrip("]").strip()
    t5 = (
        f"establishing-shot illustration of {clean_loc}, "
        f"warhammer 40000 grimdark aesthetic, oil-painting style, "
        f"{mood}, "
        f"painterly atmosphere, dramatic lighting, "
        f"highly detailed, professional concept art quality"
    )
    clip_l = f"warhammer 40k, grimdark, {clean_loc}, {mood}"
    return t5, clip_l


def resolve_anchor(
    spec: SymbolSpec, *, image_w: int, image_h: int
) -> SymbolPlacement:
    """Convert a symbol spec + scene dims into a pixel placement."""
    if spec.anchor not in DEFAULT_ANCHORS:
        raise ValueError(
            f"unknown anchor {spec.anchor!r}; known: {sorted(DEFAULT_ANCHORS)}"
        )
    cx_frac, cy_frac, base_size_frac = DEFAULT_ANCHORS[spec.anchor]
    meta, _ = load_symbol(spec.name)
    base_size_px = int(min(image_w, image_h) * base_size_frac)
    size_px = max(64, int(base_size_px * SIZE_SCALE[spec.size_label]))
    cx = int(image_w * cx_frac)
    cy = int(image_h * cy_frac)
    # SymbolPlacement uses top-left, so adjust.
    return SymbolPlacement(
        name=spec.name,
        x=cx - size_px // 2,
        y=cy - size_px // 2,
        size=size_px,
    )


def render_scene(
    *,
    server: str,
    t5xxl: str,
    clip_l: str,
    width: int,
    height: int,
    seed: int,
    prefix: str,
) -> Path:
    """Run BattlemapInteriorV1.json with scene prompts + anti-symbol negatives."""
    wf = load_template("BattlemapInteriorV1")
    set_prompt(wf, "pos", t5xxl=t5xxl, clip_l=clip_l)
    _extend_negative(wf, t5_addendum=SCENE_NEG_T5, clip_l_addendum=SCENE_NEG_CLIP_L)
    set_dimensions(wf, "latent", width=width, height=height)
    set_seed(wf, "sampler", seed)
    set_save_prefix(wf, "save", prefix)

    client_id = uuid.uuid4().hex
    print(f"[scene] submitting prefix={prefix} {width}x{height} seed={seed}", file=sys.stderr)
    pid = submit_prompt(server, wf, client_id)
    print(f"[scene] prompt_id={pid}", file=sys.stderr)
    record = poll_history(server, pid)
    saved = _saved_images_from_history(record)
    if not saved:
        raise RuntimeError(f"no SaveImage outputs in history")
    return _download_first(server, saved, prefix)


def cmd_scene(args: argparse.Namespace) -> int:
    if args.aspect not in ASPECT_TO_DIMS:
        print(f"unknown aspect {args.aspect!r}; known: {sorted(ASPECT_TO_DIMS)}", file=sys.stderr)
        return 2
    width, height = ASPECT_TO_DIMS[args.aspect]

    symbol_specs = [parse_symbol_spec(s) for s in args.symbol]
    # Pre-resolve anchors and load symbols early so missing canonicals
    # fail BEFORE we burn GPU time.
    placements: list[SymbolPlacement] = []
    for s in symbol_specs:
        load_symbol(s.name)  # raises SymbolNotFoundError if missing
        placements.append(resolve_anchor(s, image_w=width, image_h=height))

    t5, clip_l = build_scene_prompt(location=args.location, mood=args.mood)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    prefix = args.output.stem

    raw_path = render_scene(
        server=args.server,
        t5xxl=t5,
        clip_l=clip_l,
        width=width,
        height=height,
        seed=args.seed,
        prefix=prefix,
    )

    base = Image.open(raw_path)
    if placements:
        composed = compose_symbols(base, placements)
        report: list[dict] = []
        for p in placements:
            ok, score = validate_symbol(composed, p)
            tag = "OK" if ok else "FLAG"
            print(f"[scene] symbol {p.name}@({p.x},{p.y}) size={p.size}: {tag} (IoU {score:.3f})",
                  file=sys.stderr)
            report.append({
                "name": p.name, "x": p.x, "y": p.y, "size": p.size,
                "valid": bool(ok), "iou": float(score),
            })
        composed.save(args.output)
    else:
        report = []
        if args.output != raw_path:
            base.save(args.output)

    sidecar = args.output.with_suffix(".json")
    sidecar.write_text(json.dumps({
        "location": args.location,
        "aspect": args.aspect,
        "mood": args.mood,
        "seed": args.seed,
        "width": width,
        "height": height,
        "t5xxl": t5,
        "clip_l": clip_l,
        "raw_render": str(raw_path),
        "symbols": report,
    }, indent=2))
    print(f"[scene] wrote {args.output} (+ {sidecar.name})", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://198.51.100.11:8188")
    ap.add_argument("--location", required=True,
                    help="wikilink-style location id (e.g. '[[District 4 Chapel]]')")
    ap.add_argument("--aspect", default="16:9", choices=sorted(ASPECT_TO_DIMS))
    ap.add_argument("--mood", required=True,
                    help="prose mood/lighting description fed into the prompt")
    ap.add_argument("--symbol", action="append", default=[],
                    metavar="NAME:anchor[,size]",
                    help="symbol composite spec; repeatable. anchors are named in DEFAULT_ANCHORS.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, required=True)
    ap.set_defaults(func=cmd_scene)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
