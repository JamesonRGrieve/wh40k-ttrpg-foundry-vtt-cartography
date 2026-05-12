#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "PyYAML", "requests"]
# ///
"""Pipeline 1 — stamp variant generator (gap-filling + new archetypes).

Two implementation paths:

1. **Geometric rotation** (`rotate --method geometric`) — pure PIL,
   no GPU. For top-down stamps and rotation-symmetric subjects, just
   rotate the PNG 90/180/270°. Fast, deterministic, preserves
   pixel-perfect identity of the subject.

2. **Generative img2img** (`condition`, and `rotate --method generative`
   when added) — Flux img2img with low denoise (0.55-0.65) so the
   source style is preserved while the prompt drives the
   transformation. Built as a client-side workflow dict; no
   server-side workflow file required.

Usage:
    uv run generate_stamp_variants.py rotate \\
        stamps/Gemini_Generated_Image_2m932e2m932e2m93_01.png \\
        --variants south west --method geometric

    uv run generate_stamp_variants.py condition \\
        stamps/Gemini_Generated_Image_2m932e2m932e2m93_01.png \\
        --variants damaged destroyed --strength 0.65 --seed 42

Variants land in `stamps/<source-stem>_<variant>.png`. The rest of
the pipeline (make_sidecars → classify_stamps → assign_groups) picks
them up on the next run; this driver does NOT touch sidecars.

Acceptance for first cut: pick 5 source stamps with obvious gaps,
generate variants, run them through the pipeline, confirm group_id
assigns them to the same group as the source.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image

HERE = Path(__file__).resolve().parent
CAMPAIGN_ROOT = HERE.parent.parent
AI_GEN = CAMPAIGN_ROOT / ".ai-gen"
STAMPS_DIR = AI_GEN / "cartography" / "stamps"

# --- Geometric rotation ----------------------------------------------------

ROTATION_DEGREES = {
    "north": 0,    # alias for "no rotation"
    "south": 180,
    "east": 270,   # PIL rotates counter-clockwise; east = -90 = 270
    "west": 90,
}


def rotate_geometric(source: Path, *, variants: list[str]) -> list[Path]:
    """Rotate `source` to each named variant, save as <stem>_<variant>.png."""
    if not source.exists():
        raise FileNotFoundError(source)
    im = Image.open(source).convert("RGBA")
    out_paths: list[Path] = []
    for variant in variants:
        if variant not in ROTATION_DEGREES:
            raise ValueError(f"unknown rotation variant {variant!r}; known: {list(ROTATION_DEGREES)}")
        deg = ROTATION_DEGREES[variant]
        rotated = im if deg == 0 else im.rotate(deg, expand=True, resample=Image.BICUBIC)
        # Trim transparent borders to match the extractor's tightness.
        bbox = rotated.getbbox()
        if bbox:
            rotated = rotated.crop(bbox)
        out_path = source.parent / f"{source.stem}_{variant}.png"
        rotated.save(out_path)
        out_paths.append(out_path)
        print(f"[rotate-geometric] {source.name} -> {out_path.name} ({deg}°, {rotated.size})", file=sys.stderr)
    return out_paths


def cmd_rotate(args: argparse.Namespace) -> int:
    if args.method == "geometric":
        rotate_geometric(args.source, variants=args.variants)
        return 0
    print("generative rotation not yet implemented; use --method geometric for now",
          file=sys.stderr)
    return 64


# --- Generative img2img (condition variants) -------------------------------

# Per-variant prompt cues.
CONDITION_CUES: dict[str, str] = {
    "intact": "in pristine, undamaged condition, clean and well-maintained",
    "damaged": "with visible damage — scratches, dents, scuffs, cracks, partial wear, broken edges",
    "destroyed": "wrecked beyond repair — shattered, burnt-out, broken apart, ruined",
    "active": "powered on, glowing, screens lit, indicators illuminated, functioning",
    "inactive": "powered off, dark, idle, screens dark, no illumination",
}


def upload_input_image(server: str, path: Path) -> str:
    """Upload a PNG to ComfyUI's /upload/image endpoint, return the server-side filename."""
    with open(path, "rb") as fh:
        files = {"image": (path.name, fh, "image/png")}
        data = {"overwrite": "true"}
        r = requests.post(f"{server}/upload/image", files=files, data=data, timeout=60)
        r.raise_for_status()
    info = r.json()
    name = info.get("name") or info.get("filename") or path.name
    return str(name)


def submit_prompt(server: str, workflow: dict[str, Any], client_id: str) -> str:
    r = requests.post(
        f"{server}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=60,
    )
    r.raise_for_status()
    return str(r.json()["prompt_id"])


def poll_history(server: str, prompt_id: str, timeout_s: int = 600) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(f"{server}/history/{prompt_id}", timeout=30)
        if r.status_code == 200:
            payload = r.json()
            if prompt_id in payload and payload[prompt_id].get("status", {}).get("completed"):
                return payload[prompt_id]
        time.sleep(2)
    raise TimeoutError(f"prompt {prompt_id} did not complete in {timeout_s}s")


def saved_images_from_history(record: dict[str, Any]) -> list[dict[str, str]]:
    saved: list[dict[str, str]] = []
    for node_out in record.get("outputs", {}).values():
        for img in node_out.get("images", []):
            if img.get("type") == "output":
                saved.append(img)
    return saved


def download_saved(server: str, img: dict[str, str], dest: Path) -> Path:
    params = {"filename": img["filename"], "type": img.get("type", "output")}
    if img.get("subfolder"):
        params["subfolder"] = img["subfolder"]
    r = requests.get(f"{server}/view", params=params, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def build_img2img_workflow(
    *,
    server_image: str,
    t5xxl: str,
    clip_l: str,
    neg_t5xxl: str,
    neg_clip_l: str,
    denoise: float,
    seed: int,
    save_prefix: str,
) -> dict[str, Any]:
    """Build a Flux img2img workflow by minimally patching the proven txt2img.

    Loads the working `BattlemapInteriorV1.json` template, then:
      - adds a LoadImage + VAEEncode pair,
      - rewires KSampler.latent_image to read from VAEEncode,
      - lowers KSampler.denoise from 1.0 to `denoise`,
      - replaces the empty-latent node by removing it,
      - sets prompts and seed.

    This avoids re-authoring the model wiring from scratch (which
    produced VAE/scale-mismatch noise output in earlier iterations).
    """
    # Load the proven txt2img template.
    template_path = HERE / "workflows" / "BattlemapInteriorV1.json"
    wf: dict[str, Any] = json.loads(template_path.read_text())

    # Find the VAE node id by class_type so we don't hard-code names.
    def _node_by_class(class_name: str) -> str:
        for nid, node in wf.items():
            if node.get("class_type") == class_name:
                return nid
        raise KeyError(f"no node of class {class_name!r} in template")

    vae_id = _node_by_class("VAELoader")
    sampler_id = _node_by_class("KSampler")

    # Add LoadImage + VAEEncode nodes.
    wf["_stamp_load"] = {
        "class_type": "LoadImage",
        "inputs": {"image": server_image, "upload": "image"},
    }
    wf["_stamp_vae_encode"] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["_stamp_load", 0], "vae": [vae_id, 0]},
    }
    # Rewire KSampler's latent input to the VAE-encoded source.
    wf[sampler_id]["inputs"]["latent_image"] = ["_stamp_vae_encode", 0]
    wf[sampler_id]["inputs"]["denoise"] = denoise
    wf[sampler_id]["inputs"]["seed"] = seed
    wf[sampler_id]["inputs"]["control_after_generate"] = "fixed"

    # Drop the original EmptyLatentImage so it doesn't run.
    empty_latent_id: str | None = None
    for nid, node in wf.items():
        if node.get("class_type") == "EmptyLatentImage":
            empty_latent_id = nid
            break
    if empty_latent_id is not None:
        del wf[empty_latent_id]

    # Set prompts.
    pos_id = "pos" if "pos" in wf else _node_by_class("CLIPTextEncodeFlux")
    neg_id = "neg" if "neg" in wf else None
    wf[pos_id]["inputs"]["t5xxl"] = t5xxl
    wf[pos_id]["inputs"]["clip_l"] = clip_l
    if neg_id and wf[neg_id]["class_type"] == "CLIPTextEncodeFlux":
        wf[neg_id]["inputs"]["t5xxl"] = neg_t5xxl
        wf[neg_id]["inputs"]["clip_l"] = neg_clip_l

    # Save prefix.
    save_id = _node_by_class("SaveImage")
    wf[save_id]["inputs"]["filename_prefix"] = save_prefix

    return wf


CONDITION_NEG_T5 = (
    "Imperial Aquila, two-headed eagle emblem, Inquisition I, Inquisitorial rosette, "
    "Mechanicus cog, half-cog half-skull, Adepta Sororitas fleur-de-lys, "
    "Adeptus Custodes lightning bolt, Astra Militarum winged skull, "
    "Adeptus Ministorum sigil, ornate religious symbology, branded faction emblems, "
    "anime, cartoon, cel shading, low resolution, watermark, text, signature, "
    "different subject, different object, completely changed object"
)
CONDITION_NEG_CLIP_L = (
    "imperial aquila, eagle emblem, inquisition i, mechanicus cog, sigil, different object"
)


FLUX_MIN_EDGE = 512  # Flux/Chroma is under-resolved below this


def _preprocess_for_img2img(source: Path, *, white_bg: bool = True) -> Path:
    """Upscale source to FLUX_MIN_EDGE on the shortest edge and flatten alpha.

    Stamps are tiny (~128px), and Flux at <512px latent decodes to noise.
    The flatten-onto-white step gives Flux a stable backdrop to denoise
    against; we restore the alpha shape from the original source after
    download (caller's job).
    """
    im = Image.open(source).convert("RGBA")
    w, h = im.size
    short = min(w, h)
    if short < FLUX_MIN_EDGE:
        scale = FLUX_MIN_EDGE / short
        new_size = (max(FLUX_MIN_EDGE, int(round(w * scale))),
                    max(FLUX_MIN_EDGE, int(round(h * scale))))
        im = im.resize(new_size, Image.LANCZOS)
    # Round to nearest multiple of 8 for clean VAE latent dims.
    rw = (im.size[0] // 8) * 8
    rh = (im.size[1] // 8) * 8
    if (rw, rh) != im.size:
        im = im.resize((rw, rh), Image.LANCZOS)
    if white_bg:
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg.convert("RGB")
    out = source.with_name(f"_pre_{source.stem}.png")
    im.save(out)
    return out


def _restore_alpha_from(source: Path, generated: Path) -> None:
    """Apply the source's alpha mask to a generated image, preserving
    the stamp's silhouette. Resizes both to the source's dimensions.

    The img2img pass renders against white; on download we resize the
    result down to the source's dimensions and copy the source's alpha
    channel so the variant has the same transparent silhouette as the
    original.
    """
    src = Image.open(source).convert("RGBA")
    gen = Image.open(generated).convert("RGB").resize(src.size, Image.LANCZOS)
    out = Image.new("RGBA", src.size)
    out.paste(gen, (0, 0))
    out.putalpha(src.split()[-1])
    out.save(generated)


def generate_condition_variant(
    *,
    server: str,
    source: Path,
    variant: str,
    strength: float,
    seed: int,
) -> Path:
    if variant not in CONDITION_CUES:
        raise ValueError(f"unknown condition variant {variant!r}; known: {list(CONDITION_CUES)}")
    if not source.exists():
        raise FileNotFoundError(source)

    cue = CONDITION_CUES[variant]
    t5 = (
        f"top-down isolated single object on plain white background, "
        f"warhammer 40000 grimdark aesthetic, oil-painting illustration style, "
        f"object {cue}, "
        f"highly detailed, painterly texture, professional concept art quality, "
        f"same subject and composition as the input image, only the condition is {variant}"
    )
    clip_l = f"warhammer 40k, grimdark, {variant} object, painterly stamp"

    pre_path = _preprocess_for_img2img(source)
    try:
        server_name = upload_input_image(server, pre_path)
        prefix = f"variant_{source.stem}_{variant}_seed{seed}"
        wf = build_img2img_workflow(
            server_image=server_name,
            t5xxl=t5,
            clip_l=clip_l,
            neg_t5xxl=CONDITION_NEG_T5,
            neg_clip_l=CONDITION_NEG_CLIP_L,
            denoise=strength,
            seed=seed,
            save_prefix=prefix,
        )

        client_id = uuid.uuid4().hex
        pid = submit_prompt(server, wf, client_id)
        print(f"[condition] {source.name} -> {variant} (denoise={strength}, seed={seed}) prompt_id={pid}",
              file=sys.stderr)
        record = poll_history(server, pid)
        saved = saved_images_from_history(record)
        if not saved:
            raise RuntimeError(f"no SaveImage outputs in history: {json.dumps(record.get('outputs'), indent=2)[:600]}")

        out_path = source.parent / f"{source.stem}_{variant}.png"
        download_saved(server, saved[0], out_path)
        _restore_alpha_from(source, out_path)
        print(f"[condition] saved {out_path.name}", file=sys.stderr)
        return out_path
    finally:
        pre_path.unlink(missing_ok=True)


def cmd_condition(args: argparse.Namespace) -> int:
    for variant in args.variants:
        generate_condition_variant(
            server=args.server,
            source=args.source,
            variant=variant,
            strength=args.strength,
            seed=args.seed,
        )
    return 0


def cmd_archetype(args: argparse.Namespace) -> int:
    print("net-new archetype generation deferred — needs IPAdapter style-locking workflow.",
          file=sys.stderr)
    return 64


# --- CLI -------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://198.51.100.11:8188")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("rotate", help="generate rotational variants of a source stamp")
    pr.add_argument("source", type=Path)
    pr.add_argument("--variants", nargs="+", required=True,
                    choices=list(ROTATION_DEGREES))
    pr.add_argument("--method", choices=["geometric", "generative"], default="geometric")
    pr.add_argument("--seed", type=int, default=42)
    pr.set_defaults(func=cmd_rotate)

    pc = sub.add_parser("condition", help="generate damage/activation variants of a source stamp")
    pc.add_argument("source", type=Path)
    pc.add_argument("--variants", nargs="+", required=True,
                    choices=list(CONDITION_CUES))
    pc.add_argument("--strength", type=float, default=0.6,
                    help="img2img denoise strength (0.0-1.0); higher = more reinterpretation")
    pc.add_argument("--seed", type=int, default=42)
    pc.set_defaults(func=cmd_condition)

    pa = sub.add_parser("archetype", help="(deferred) net-new archetype generation")
    pa.add_argument("prompt", type=Path)
    pa.add_argument("--style-from", type=Path, required=True)
    pa.add_argument("--count", type=int, default=4)
    pa.add_argument("--seed", type=int, default=42)
    pa.set_defaults(func=cmd_archetype)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
