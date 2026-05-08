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
    MATERIAL_HINTS,
    SymbolPlacement,
    build_controlnet_guide,
    compose_symbols,
    load_symbol,
    material_hint_phrase,
    validate_symbol,
)
from generate_stamp_variants import (  # type: ignore[import-not-found]
    upload_input_image,
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
    material_hint: str | None = None


def parse_symbol_spec(spec: str) -> SymbolSpec:
    """`name:anchor[,size_label[,material_hint]]` -> SymbolSpec.

    Examples:
        aquila:apse_back
        aquila:apse_back,large
        aquila:apse_back,large,brass-relief
        adeptus_ministorum:lectern_front,small,carved-stone
    """
    if ":" not in spec:
        raise argparse.ArgumentTypeError(f"--symbol expects NAME:anchor[,size[,material]], got {spec!r}")
    name, body = spec.split(":", 1)
    parts = [p.strip() for p in body.split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError(f"--symbol body needs anchor, got {spec!r}")
    anchor = parts[0]
    size = parts[1] if len(parts) >= 2 else "medium"
    material = parts[2] if len(parts) >= 3 else None
    if size not in SIZE_SCALE:
        raise argparse.ArgumentTypeError(
            f"size must be one of {list(SIZE_SCALE)}, got {size!r}"
        )
    if material is not None and material not in MATERIAL_HINTS:
        raise argparse.ArgumentTypeError(
            f"material must be one of {list(MATERIAL_HINTS)}, got {material!r}"
        )
    return SymbolSpec(name=name, anchor=anchor, size_label=size, material_hint=material)


# Friendly anchor labels used in prompt construction. The keys match
# DEFAULT_ANCHORS; values are short noun phrases describing where the
# symbol sits in the scene. Kept separate from the geometry so we can
# evolve the wording without renaming anchors.
ANCHOR_FRIENDLY: dict[str, str] = {
    "apse_back": "apse back wall",
    "altar_face": "altar face",
    "lectern_front": "lectern front face",
    "door_keystone": "door keystone above the entrance",
    "banner_field": "hanging banner",
    "ship_hull_marking": "ship hull marking",
    "center": "central feature",
    "top_left": "upper-left wall",
    "top_right": "upper-right wall",
    "bottom_left": "lower-left wall",
    "bottom_right": "lower-right wall",
}


def build_symbol_prompt_clause(placements: list[SymbolPlacement]) -> str:
    """Compose a prompt fragment that describes the iconography to be
    rendered. The ControlNet locks the silhouette; the prompt drives
    material and lighting integration.

    Returns an empty string if no placements provided.
    """
    if not placements:
        return ""
    parts: list[str] = []
    for p in placements:
        meta, _ = load_symbol(p.name)
        location = p.anchor_label or "the wall"
        material = material_hint_phrase(p.material_hint)
        parts.append(f"a {meta.display_name} on the {location}, {material}")
    return ", with " + "; and ".join(parts)


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
        material_hint=spec.material_hint,
        anchor_label=ANCHOR_FRIENDLY.get(spec.anchor, spec.anchor.replace("_", " ")),
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
    """Run BattlemapInteriorV1.json with scene prompts + anti-symbol negatives.

    Used by the LEGACY paste-on-top symbol path (`--symbol-style flat`).
    """
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


def render_scene_integrated(
    *,
    server: str,
    base_t5: str,
    base_clip_l: str,
    augmented_t5: str,
    placements: list[SymbolPlacement],
    width: int,
    height: int,
    seed: int,
    prefix: str,
    integration_denoise: float = 0.45,
) -> tuple[Path, Path]:
    """Two-pass scene render that integrates symbology as scene material.

    Pass 1: txt2img scene without symbols (anti-symbol negatives apply).
    Composite black-on-white canonical silhouettes onto pass 1 at each
    declared anchor.
    Pass 2: img2img with the silhouette-painted scene as the latent
    starting point and the augmented prompt that describes each
    symbol's intended material (brass relief, embroidered, etc).
    Low denoise (0.40-0.50) keeps the surrounding scene mostly intact
    while reinterpreting the silhouette regions as the requested
    material.

    Returns (rendered_path, guide_path). guide_path is the silhouette-
    painted intermediate, kept for inspection.

    Why this instead of ControlNet: the flux-canny-controlnet model
    on the server is XLabs-format and not directly compatible with
    Chroma-Flux via the generic ControlNetApplyAdvanced node. Hung
    indefinitely on first try. img2img with low denoise produces the
    same "preserve silhouette, fill in material" outcome using the
    proven path that already powers stamp condition variants.
    """
    # --- Pass 1: clean scene render --------------------------------------
    pass1_prefix = f"_p1_{prefix}"
    pass1_path = render_scene(
        server=server,
        t5xxl=base_t5,
        clip_l=base_clip_l,
        width=width,
        height=height,
        seed=seed,
        prefix=pass1_prefix,
    )

    # --- Composite silhouettes -----------------------------------------
    pass1_im = Image.open(pass1_path).convert("RGBA")
    guide_im = pass1_im.copy()
    for p in placements:
        meta, _ = load_symbol(p.name)
        # Build a per-placement RGBA silhouette: BLACK fill, alpha = canonical alpha.
        # Importing here to avoid surfacing _prepare_canonical at module level.
        from symbol_compose import _prepare_canonical  # type: ignore[import-not-found]
        canon = _prepare_canonical(meta, p)  # RGBA at the prepared size
        alpha = canon.split()[-1]
        sil_rgba = Image.new("RGBA", canon.size, (0, 0, 0, 0))
        black = Image.new("RGBA", canon.size, (0, 0, 0, 255))
        sil_rgba.paste(black, (0, 0), alpha)
        guide_im.alpha_composite(sil_rgba, dest=(int(p.x), int(p.y)))
    guide_path = HERE / "battlemaps" / f"_guide_{prefix}.png"
    guide_im.convert("RGB").save(guide_path)

    # --- Pass 2: img2img repaint silhouettes as scene-integrated material -
    # Reuse the stamp-variants img2img workflow constructor (template-patched).
    # Lazy import keeps the cycle clean.
    from generate_stamp_variants import build_img2img_workflow  # type: ignore[import-not-found]

    server_name = upload_input_image(server, guide_path)
    pass2_prefix = f"_p2_{prefix}"
    wf = build_img2img_workflow(
        server_image=server_name,
        t5xxl=augmented_t5,
        clip_l=base_clip_l,
        neg_t5xxl=SCENE_NEG_T5,
        neg_clip_l=SCENE_NEG_CLIP_L,
        denoise=integration_denoise,
        seed=seed,
        save_prefix=pass2_prefix,
    )
    client_id = uuid.uuid4().hex
    print(f"[scene-i2i] integration pass denoise={integration_denoise} seed={seed}", file=sys.stderr)
    pid = submit_prompt(server, wf, client_id)
    print(f"[scene-i2i] prompt_id={pid}", file=sys.stderr)
    record = poll_history(server, pid)
    saved = _saved_images_from_history(record)
    if not saved:
        raise RuntimeError("no SaveImage outputs from integration pass")
    rendered = _download_first(server, saved, pass2_prefix)
    return rendered, guide_path


def cmd_scene(args: argparse.Namespace) -> int:
    if args.aspect not in ASPECT_TO_DIMS:
        print(f"unknown aspect {args.aspect!r}; known: {sorted(ASPECT_TO_DIMS)}", file=sys.stderr)
        return 2
    width, height = ASPECT_TO_DIMS[args.aspect]

    symbol_specs = [parse_symbol_spec(s) for s in args.symbol]
    placements: list[SymbolPlacement] = []
    for s in symbol_specs:
        load_symbol(s.name)  # raises SymbolNotFoundError if missing
        placements.append(resolve_anchor(s, image_w=width, image_h=height))

    base_t5, base_clip_l = build_scene_prompt(location=args.location, mood=args.mood)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    prefix = args.output.stem

    use_integrated = (args.symbol_style == "integrated") and bool(placements)

    if use_integrated:
        # Two-pass img2img path: render scene → composite black silhouettes
        # → low-denoise img2img to repaint silhouettes as scene material.
        augmented_t5 = base_t5 + build_symbol_prompt_clause(placements)
        clip_l = base_clip_l
        t5 = augmented_t5
        raw_path, guide_path = render_scene_integrated(
            server=args.server,
            base_t5=base_t5,
            base_clip_l=base_clip_l,
            augmented_t5=augmented_t5,
            placements=placements,
            width=width,
            height=height,
            seed=args.seed,
            prefix=prefix,
            integration_denoise=args.integration_denoise,
        )
    else:
        # Flat / no-symbol path: legacy txt2img + paste-on-top compose.
        t5 = base_t5
        clip_l = base_clip_l
        raw_path = render_scene(
            server=args.server,
            t5xxl=t5,
            clip_l=clip_l,
            width=width,
            height=height,
            seed=args.seed,
            prefix=prefix,
        )
        guide_path = None

    base = Image.open(raw_path)
    report: list[dict] = []
    if use_integrated:
        # Symbols repainted INTO the scene by img2img integration. The
        # canny-IoU validator is calibrated for paste-on-top fidelity
        # (silhouette pixels exactly match the canonical) and is
        # NOT meaningful here — the integration intentionally
        # transforms edges into scene material. Score is logged for
        # diagnostics only; not a FLAG/OK gate.
        for p in placements:
            _ok, score = validate_symbol(base, p)
            print(f"[scene-i2i] symbol {p.name}@({p.x},{p.y}) size={p.size}: integrated (IoU {score:.3f}, informational)",
                  file=sys.stderr)
            report.append({
                "name": p.name, "x": p.x, "y": p.y, "size": p.size,
                "material_hint": p.material_hint,
                "integrated": True, "iou_informational": float(score),
            })
        if args.output != raw_path:
            base.save(args.output)
    elif placements:
        composed = compose_symbols(base, placements)
        for p in placements:
            ok, score = validate_symbol(composed, p)
            tag = "OK" if ok else "FLAG"
            print(f"[scene] symbol {p.name}@({p.x},{p.y}) size={p.size}: {tag} (IoU {score:.3f})",
                  file=sys.stderr)
            report.append({
                "name": p.name, "x": p.x, "y": p.y, "size": p.size,
                "material_hint": p.material_hint,
                "valid": bool(ok), "iou": float(score),
            })
        composed.save(args.output)
    else:
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
        "symbol_style": args.symbol_style,
        "raw_render": str(raw_path),
        "guide_image": str(guide_path) if guide_path else None,
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
                    metavar="NAME:anchor[,size[,material]]",
                    help="symbol spec; repeatable. anchors in DEFAULT_ANCHORS, "
                    f"sizes in {sorted(SIZE_SCALE)}, materials in {sorted(MATERIAL_HINTS)}.")
    ap.add_argument("--symbol-style", choices=["integrated", "flat"], default="integrated",
                    help="integrated (default): two-pass render — txt2img scene, composite "
                    "black silhouettes at anchors, img2img repaint silhouettes as the "
                    "declared --material. flat: legacy paste-on-top (diagrammatic only).")
    ap.add_argument("--integration-denoise", type=float, default=0.45,
                    help="Pass 2 img2img denoise (0.0-1.0). 0.40-0.55 keeps the scene mostly "
                    "intact while reinterpreting the silhouettes as the requested material. "
                    "Higher = more reinterpretation; risks losing silhouette fidelity.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, required=True)
    ap.set_defaults(func=cmd_scene)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
