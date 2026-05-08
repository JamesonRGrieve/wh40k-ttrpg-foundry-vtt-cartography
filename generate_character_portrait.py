#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "opencv-python-headless", "PyYAML", "requests"]
# ///
"""Pipeline 2 — character portrait generator.

Bust / three-quarter / full-body portraits matched to the campaign's
illustrated style. Uses the proven Flux txt2img workflow
(BattlemapInteriorV1) with three additions:

1. Class-specific portrait prompts (Inquisitor / Acolyte / Tech-priest
   / Guardsman / Preacher / Astropath / Hive-ganger / Civilian).
2. Anti-symbol negative prompts so Flux doesn't draw mangled Aquila /
   Inquisition / Mechanicus iconography.
3. Symbol-compose pass at class-specific anchor points (chest, collar,
   pauldron, etc.) so canonical 40K iconography is pasted from the
   library instead of hallucinated.

ControlNet OpenPose for explicit pose composition is deferred to a
future iteration; for now portrait composition is prompt-driven plus
seed selection.

Usage:
    uv run generate_character_portrait.py "Inquisitor Vael" \\
        --slot bust --class inquisitor --seed 42 \\
        --output ../../Characters/portraits/Vael_bust.png
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image
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

HERE = Path(__file__).resolve().parent

SLOT_DIMS: dict[str, tuple[int, int]] = {
    "bust": (768, 1024),
    "three-quarter": (768, 1280),
    "full-body": (768, 1536),
}

# Per-slot token-crop center (fractional cy in the portrait). The face is
# higher in the frame for longer compositions because the head occupies a
# smaller portion of the canvas.
TOKEN_CY_FRAC: dict[str, float] = {
    "bust": 0.30,           # head/shoulders bust — face in upper third
    "three-quarter": 0.20,  # face in top fifth
    "full-body": 0.13,      # face near top of frame
}

# Token edge length (px). 512 is a comfortable Foundry token size that scales
# down cleanly to the system's default ~100px tile grid. The crop is square.
TOKEN_EDGE_PX = 512

# Class -> (prompt cue, list of symbol placements). Each placement is
# (name, anchor, size_label, material_hint, anchor_label).
# Symbols anchor at fractions of (image_w, image_h) — see _ANCHOR_FRACS.
CLASS_PROFILES: dict[str, dict] = {
    "inquisitor": {
        "prompt": "an Inquisitor of the Holy Ordos, severe weathered face, long dark coat with high collar, "
                  "embellished gunmetal armor under the coat, ornate chest carapace, "
                  "carrying a power weapon at the hip, somber gaze, oil-painting portrait style",
        "symbols": [("inquisition_rosette", "chest_center", "large", "armor-inlay", "chest carapace")],
    },
    "acolyte": {
        "prompt": "a hard-bitten Inquisitorial acolyte, scarred face, practical fatigues with a personal sigil, "
                  "weathered armor pieces, holstered laspistol, tense alert expression, oil-painting portrait style",
        "symbols": [("inquisition_i", "collar_left", "medium", "stamped-metal", "left collar")],
    },
    "tech-priest": {
        "prompt": "an Adeptus Mechanicus Tech-priest, half-flesh half-mechanical face, robotic eye lens, "
                  "mechadendrites emerging from red robes, brass and steel cybernetic augmentations, "
                  "cogitator implants, dim red glow, oil-painting portrait style",
        "symbols": [("mechanicus_cog", "chest_center", "large", "brass-relief", "chest plate")],
    },
    "guardsman": {
        "prompt": "an Imperial Guardsman, weathered helmeted face with chin strap, flak armor over fatigues, "
                  "regimental insignia on the shoulder, lasgun slung at the side, dirt-streaked, "
                  "weary determined expression, oil-painting portrait style",
        "symbols": [("astra_militarum", "shoulder_right", "medium", "stamped-metal", "right shoulder pauldron")],
    },
    "preacher": {
        "prompt": "an Ecclesiarchy preacher, robed cleric with a censer at the belt, severe ascetic face, "
                  "holy book under one arm, candle-lit warm illumination, oil-painting portrait style",
        "symbols": [("adeptus_ministorum", "chest_center", "large", "embroidered-banner", "robe centerpiece")],
    },
    "astropath": {
        "prompt": "an Astropath, blind sealed eyes, gaunt skull-like face, gold and bone-white robes, "
                  "warp-touched aura, faintly glowing skin, ethereal painterly atmosphere, oil-painting portrait style",
        "symbols": [],
    },
    "hive-ganger": {
        "prompt": "a hive-world ganger, scarred and tattooed face, stitched-together leather and salvage armor, "
                  "improvised stub weapon, defiant snarling expression, neon-stained underhive lighting, "
                  "oil-painting portrait style",
        "symbols": [],
    },
    "civilian": {
        "prompt": "a hive-world Imperial citizen, drab worker's clothing with a personal Aquila pendant, "
                  "tired careworn face, muted brown and gray palette, oil-painting portrait style",
        "symbols": [("aquila", "collar_center", "small", "stamped-metal", "collar pendant")],
    },
}

# Fractional anchors keyed by name. Same convention as the scene picture
# generator: (cx_frac, cy_frac, base_size_frac of min(w, h)).
_ANCHOR_FRACS: dict[str, tuple[float, float, float]] = {
    "chest_center": (0.50, 0.62, 0.18),
    "collar_left":  (0.40, 0.42, 0.10),
    "collar_center": (0.50, 0.40, 0.10),
    "shoulder_right": (0.72, 0.45, 0.12),
    "pauldron_left": (0.30, 0.45, 0.14),
}

_SIZE_SCALE: dict[str, float] = {
    "small": 0.6,
    "medium": 1.0,
    "large": 1.5,
}

PORTRAIT_NEG_T5 = (
    "Imperial Aquila, two-headed eagle emblem, Inquisition I, Inquisitorial rosette, "
    "Mechanicus cog, half-cog half-skull, Adepta Sororitas fleur-de-lys, "
    "Adeptus Custodes lightning bolt, Astra Militarum winged skull, "
    "Adeptus Ministorum sigil, ornate religious symbology, branded faction emblems, "
    "anime, cartoon, cel shading, photorealistic, photograph, low resolution, watermark, text, signature, "
    "extra arms, extra heads, missing limbs, deformed face, disfigured, blurry, ugly, messy"
)
PORTRAIT_NEG_CLIP_L = (
    "imperial aquila, eagle emblem, inquisition i, mechanicus cog, sigil, deformed, blurry"
)


@dataclass
class PortraitSpec:
    name: str
    cls: str
    slot: str
    seed: int
    output: Path


def build_portrait_prompt(*, name: str, cls: str, slot: str, gender: str | None = None, age: str | None = None) -> tuple[str, str]:
    if cls not in CLASS_PROFILES:
        raise ValueError(f"unknown class {cls!r}; known: {list(CLASS_PROFILES)}")
    body = CLASS_PROFILES[cls]["prompt"]
    composition = {
        "bust": "head and shoulders bust portrait, neutral background, centered composition",
        "three-quarter": "three-quarter length portrait from the thighs up, neutral background, centered composition",
        "full-body": "full-body standing portrait, neutral background, centered composition",
    }[slot]
    subject_bits: list[str] = []
    if age:
        subject_bits.append(age)
    if gender:
        subject_bits.append({"male": "man", "female": "woman", "nonbinary": "person"}.get(gender.lower(), gender))
    subject_clause = (" ".join(subject_bits) + ", ") if subject_bits else ""
    t5 = (
        f"{composition}, "
        f"warhammer 40000 grimdark aesthetic, painterly oil-painting illustration, "
        f"{subject_clause}{body}, "
        f"highly detailed character portrait, dramatic chiaroscuro lighting, "
        f"professional concept art quality, single character, plain dark background"
    )
    clip_l = f"warhammer 40k, grimdark portrait, {subject_clause}{cls}, painterly oil painting"
    return t5, clip_l


def resolve_portrait_anchor(
    spec: tuple,
    *,
    image_w: int,
    image_h: int,
) -> SymbolPlacement:
    """Accept either the legacy 3-tuple (name, anchor, size_label) or
    the extended 5-tuple (name, anchor, size_label, material_hint,
    anchor_label). Material hint and anchor label power the ControlNet
    prompt-augmentation step.
    """
    if len(spec) == 3:
        sym_name, anchor, size_label = spec
        material_hint = None
        anchor_label = None
    elif len(spec) == 5:
        sym_name, anchor, size_label, material_hint, anchor_label = spec
    else:
        raise ValueError(f"bad symbol spec arity {len(spec)}: {spec!r}")
    if anchor not in _ANCHOR_FRACS:
        raise ValueError(f"unknown anchor {anchor!r}; known: {sorted(_ANCHOR_FRACS)}")
    cx_frac, cy_frac, base_size_frac = _ANCHOR_FRACS[anchor]
    base_size_px = int(min(image_w, image_h) * base_size_frac)
    size_px = max(48, int(base_size_px * _SIZE_SCALE[size_label]))
    cx = int(image_w * cx_frac)
    cy = int(image_h * cy_frac)
    return SymbolPlacement(
        name=sym_name,
        x=cx - size_px // 2,
        y=cy - size_px // 2,
        size=size_px,
        material_hint=material_hint,
        anchor_label=anchor_label,
    )


def build_portrait_symbol_clause(placements: list[SymbolPlacement]) -> str:
    """Append-clause that describes the iconography to be rendered IN
    the portrait via ControlNet. Empty if no placements."""
    if not placements:
        return ""
    parts: list[str] = []
    for p in placements:
        meta, _ = load_symbol(p.name)
        location = p.anchor_label or "the chest"
        material = material_hint_phrase(p.material_hint)
        parts.append(f"a {meta.display_name} on the character's {location}, {material}")
    return ", with " + "; and ".join(parts)


def render_portrait_integrated(
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
    """Two-pass portrait: txt2img → composite silhouettes → img2img repaint.

    Same architecture as render_scene_integrated; see that function's
    docstring for rationale (in short: ControlNet hangs on Chroma-Flux,
    img2img with low denoise produces equivalent "preserve silhouette,
    fill in material" behavior via the proven path).
    """
    pass1_prefix = f"_p1_{prefix}"
    pass1_path = render_portrait(
        server=server, t5xxl=base_t5, clip_l=base_clip_l,
        width=width, height=height, seed=seed, prefix=pass1_prefix,
    )

    pass1_im = Image.open(pass1_path).convert("RGBA")
    guide_im = pass1_im.copy()
    from symbol_compose import _prepare_canonical  # type: ignore[import-not-found]
    for p in placements:
        meta, _ = load_symbol(p.name)
        canon = _prepare_canonical(meta, p)
        alpha = canon.split()[-1]
        sil_rgba = Image.new("RGBA", canon.size, (0, 0, 0, 0))
        black = Image.new("RGBA", canon.size, (0, 0, 0, 255))
        sil_rgba.paste(black, (0, 0), alpha)
        guide_im.alpha_composite(sil_rgba, dest=(int(p.x), int(p.y)))
    guide_path = HERE / "battlemaps" / f"_guide_{prefix}.png"
    guide_im.convert("RGB").save(guide_path)

    from generate_stamp_variants import build_img2img_workflow  # type: ignore[import-not-found]
    server_name = upload_input_image(server, guide_path)
    pass2_prefix = f"_p2_{prefix}"
    wf = build_img2img_workflow(
        server_image=server_name,
        t5xxl=augmented_t5,
        clip_l=base_clip_l,
        neg_t5xxl=PORTRAIT_NEG_T5,
        neg_clip_l=PORTRAIT_NEG_CLIP_L,
        denoise=integration_denoise,
        seed=seed,
        save_prefix=pass2_prefix,
    )
    client_id = uuid.uuid4().hex
    print(f"[portrait-i2i] integration pass denoise={integration_denoise} seed={seed}", file=sys.stderr)
    pid = submit_prompt(server, wf, client_id)
    print(f"[portrait-i2i] prompt_id={pid}", file=sys.stderr)
    record = poll_history(server, pid)
    saved = _saved_images_from_history(record)
    if not saved:
        raise RuntimeError("no SaveImage outputs from integration pass")
    rendered = _download_first(server, saved, pass2_prefix)
    return rendered, guide_path


def render_portrait(
    *,
    server: str,
    t5xxl: str,
    clip_l: str,
    width: int,
    height: int,
    seed: int,
    prefix: str,
) -> Path:
    wf = load_template("BattlemapInteriorV1")
    set_prompt(wf, "pos", t5xxl=t5xxl, clip_l=clip_l)
    _extend_negative(wf, t5_addendum=PORTRAIT_NEG_T5, clip_l_addendum=PORTRAIT_NEG_CLIP_L)
    set_dimensions(wf, "latent", width=width, height=height)
    set_seed(wf, "sampler", seed)
    set_save_prefix(wf, "save", prefix)

    client_id = uuid.uuid4().hex
    print(f"[portrait] submitting prefix={prefix} {width}x{height} seed={seed}", file=sys.stderr)
    pid = submit_prompt(server, wf, client_id)
    print(f"[portrait] prompt_id={pid}", file=sys.stderr)
    record = poll_history(server, pid)
    saved = _saved_images_from_history(record)
    if not saved:
        raise RuntimeError(f"no SaveImage outputs in history")
    return _download_first(server, saved, prefix)


def cmd_portrait(args: argparse.Namespace) -> int:
    if args.cls not in CLASS_PROFILES:
        print(f"unknown class {args.cls!r}; known: {list(CLASS_PROFILES)}", file=sys.stderr)
        return 2
    if args.slot not in SLOT_DIMS:
        print(f"unknown slot {args.slot!r}; known: {list(SLOT_DIMS)}", file=sys.stderr)
        return 2

    width, height = SLOT_DIMS[args.slot]
    profile_symbols = CLASS_PROFILES[args.cls]["symbols"]

    # Pre-resolve symbols so missing canonicals fail BEFORE GPU.
    placements: list[SymbolPlacement] = []
    for sym_spec in profile_symbols:
        load_symbol(sym_spec[0])
        placements.append(resolve_portrait_anchor(sym_spec, image_w=width, image_h=height))

    base_t5, base_clip_l = build_portrait_prompt(name=args.name, cls=args.cls, slot=args.slot, gender=args.gender, age=args.age)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    prefix = args.output.stem

    use_integrated = (args.symbol_style == "integrated") and bool(placements)
    guide_path: Path | None = None

    if use_integrated:
        augmented_t5 = base_t5 + build_portrait_symbol_clause(placements)
        clip_l = base_clip_l
        t5 = augmented_t5
        raw_path, guide_path = render_portrait_integrated(
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
        t5 = base_t5
        clip_l = base_clip_l
        raw_path = render_portrait(
            server=args.server, t5xxl=t5, clip_l=clip_l,
            width=width, height=height, seed=args.seed, prefix=prefix,
        )

    base = Image.open(raw_path)
    report: list[dict] = []
    if use_integrated:
        # Two-pass img2img integrated the symbol IN the portrait — final = raw.
        # IoU validator is calibrated for paste-on-top fidelity and is NOT
        # meaningful here; logged informationally.
        for p in placements:
            _ok, score = validate_symbol(base, p)
            print(f"[portrait-i2i] symbol {p.name}@({p.x},{p.y}) size={p.size}: integrated (IoU {score:.3f}, informational)",
                  file=sys.stderr)
            report.append({"name": p.name, "x": p.x, "y": p.y, "size": p.size,
                           "material_hint": p.material_hint,
                           "integrated": True, "iou_informational": float(score)})
        final = base
        if args.output != raw_path:
            base.save(args.output)
    elif placements:
        composed = compose_symbols(base, placements)
        for p in placements:
            ok, score = validate_symbol(composed, p)
            tag = "OK" if ok else "FLAG"
            print(f"[portrait] symbol {p.name}@({p.x},{p.y}) size={p.size}: {tag} (IoU {score:.3f})",
                  file=sys.stderr)
            report.append({"name": p.name, "x": p.x, "y": p.y, "size": p.size,
                           "material_hint": p.material_hint,
                           "valid": bool(ok), "iou": float(score)})
        final = composed
        composed.save(args.output)
    else:
        final = base
        if args.output != raw_path:
            base.save(args.output)

    # --- Token: 1:1 square crop centered on the face -----------------------
    # Foundry actors have a portrait (full image, sidebar) AND a token (1:1,
    # canvas). The token is typically the head + shoulders cropped from the
    # portrait. Crop center is per-slot because the face occupies a different
    # vertical fraction depending on portrait length.
    cy_frac = TOKEN_CY_FRAC[args.slot]
    img_w, img_h = final.size
    edge = min(img_w, img_h)  # crop within the portrait's smaller dimension
    cy = int(img_h * cy_frac)
    # Clamp so the square stays inside the canvas.
    half = edge // 2
    cy = max(half, min(img_h - half, cy))
    cx = img_w // 2
    crop_box = (cx - half, cy - half, cx + half, cy + half)
    token = final.convert("RGBA").crop(crop_box).resize((TOKEN_EDGE_PX, TOKEN_EDGE_PX), Image.LANCZOS)
    token_path = args.output.with_name(f"{args.output.stem}_token.png")
    token.save(token_path)
    print(f"[portrait] token: {token_path.name} ({TOKEN_EDGE_PX}x{TOKEN_EDGE_PX} from crop {crop_box})",
          file=sys.stderr)

    sidecar = args.output.with_suffix(".json")
    sidecar.write_text(json.dumps({
        "name": args.name, "class": args.cls, "slot": args.slot,
        "seed": args.seed, "width": width, "height": height,
        "t5xxl": t5, "clip_l": clip_l,
        "symbol_style": args.symbol_style,
        "raw_render": str(raw_path),
        "guide_image": str(guide_path) if guide_path else None,
        "symbols": report,
        "token": {"path": str(token_path), "edge_px": TOKEN_EDGE_PX, "crop_box": list(crop_box)},
    }, indent=2))
    print(f"[portrait] wrote {args.output} (+ {sidecar.name})", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://198.51.100.11:8188")
    ap.add_argument("name", help="character name (matches Characters/<name>.md)")
    ap.add_argument("--slot", choices=sorted(SLOT_DIMS), default="bust")
    ap.add_argument("--class", dest="cls", required=True, choices=sorted(CLASS_PROFILES))
    ap.add_argument("--symbol-style", choices=["integrated", "flat"], default="integrated",
                    help="integrated (default): two-pass render — txt2img portrait, composite "
                    "silhouettes, img2img repaint as the class's --material hint. flat: legacy "
                    "paste-on-top of black canonical SVG.")
    ap.add_argument("--integration-denoise", type=float, default=0.45,
                    help="Pass 2 img2img denoise (0.0-1.0). 0.40-0.55 is the working range.")
    ap.add_argument("--gender", choices=["male", "female", "nonbinary"], default=None,
                    help="Subject gender. Without this, Flux defaults to a masculine read.")
    ap.add_argument("--age", default=None,
                    help="Free-text age cue, e.g. 'late 50s', 'early 30s'.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, required=True)
    ap.set_defaults(func=cmd_portrait)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
