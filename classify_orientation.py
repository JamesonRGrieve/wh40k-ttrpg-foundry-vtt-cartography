#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "Pillow",
#   "torch",
#   "transformers",
#   "sentencepiece",
#   "protobuf",
#   "PyYAML",
# ]
# ///
"""
Zero-shot orientation classifier for stamps.

Florence-2 captions almost never include directional words ("facing
east", "from the left"), so the caption-based `derive_orientation` in
classify_stamps.py only catches the ~3% of stamps where the model
mentioned a direction. This script runs CLIP zero-shot directly
against each stamp PNG to classify its viewing angle and facing
direction independently of caption content.

Two-stage classification:
1. Camera angle: top-down vs isometric vs uncertain.
   - Most stamps in the vault are illustrative top-down or
     three-quarter isometric. "uncertain" is reserved for stamps
     CLIP can't confidently place in either bucket.
2. Facing direction (only run if isometric): north / south / east /
   west, or null when the object is rotation-symmetric.

Uses HuggingFace `openai/clip-vit-large-patch14` from transformers.
First run downloads ~1.7 GB of weights into the HF cache; subsequent
runs are local. CUDA used if torch finds a device, else CPU. Single
stamp: ~50 ms on a 3090, ~300 ms on CPU.

Writes orientation back to each stamp's yaml. Caption-derived values
are preserved when the script is uncertain — the existing field is
overwritten only when CLIP's confidence margin exceeds CONF_MARGIN.

Usage:
    python classify_orientation.py [--source <stem>] [--force]
                                   [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import torch
import yaml
from PIL import Image
from transformers import AutoModel, AutoProcessor

HERE = Path(__file__).resolve().parent
CAMPAIGN_ROOT = HERE.parent.parent
AI_GEN = CAMPAIGN_ROOT / ".ai-gen"
STAMPS_DIR = AI_GEN / "cartography" / "stamps"
# CLIP-ViT-L-14: tested better than SigLIP-so400m on this stamp set
# despite SigLIP's stronger general accuracy. The contrastive softmax
# at temperature 100 maps well to the binary "top-down vs isometric"
# choice; SigLIP's sigmoid scoring biased the verbose top-down label
# even for clear isometric stamps. CLIP measures: ~71% angle accuracy
# on the 4lrua5 hand-grounded test set, vs ~3% via Florence-2 caption
# parsing alone.
MODEL_NAME = "openai/clip-vit-large-patch14"

# Confidence margin: probability of the winner minus the runner-up
# must exceed this for the result to be accepted. Below it, the
# stamp is left as null (or the existing value preserved).
CONF_MARGIN = 0.12

# Stage 1 — camera angle. Each label has multiple paraphrases; we
# average their embeddings to soak up phrasing noise. Prompts are
# tuned for ILLUSTRATED stamps (digital painting / 3D render style),
# not natural photographs — that's the dominant style of the
# Gemini-generated stamp grids in this campaign.
ANGLE_PROMPTS = {
    "top-down": [
        "a top-down view of an object",
        "an overhead bird's-eye illustration",
        "an object seen from straight above",
    ],
    "isometric": [
        "a three-quarter isometric view of an object",
        "an angled 3D rendering with visible side face",
        "an object drawn at an oblique tilted perspective",
    ],
}

# Stage 2 — facing direction. Only applied to isometric stamps,
# and only when one direction wins by CONF_MARGIN. Many stamps are
# rotation-symmetric (lamps, jars, crates) — these stay null.
FACING_PROMPTS = {
    "north": [
        "an object facing away from the viewer, its back toward the camera",
        "an object oriented with its front toward the top of the frame",
    ],
    "south": [
        "an object facing toward the viewer, its front toward the camera",
        "an object oriented with its front toward the bottom of the frame",
    ],
    "east": [
        "an object facing to the right, its front toward the right side of the frame",
        "an object oriented with its front toward the right edge of the image",
    ],
    "west": [
        "an object facing to the left, its front toward the left side of the frame",
        "an object oriented with its front toward the left edge of the image",
    ],
}


def load_image_for_clip(png_path: Path, target: int = 224) -> Image.Image:
    """Open the PNG, flatten transparent areas to white, return PIL.

    CLIP models train on RGB; transparent backgrounds confuse them
    (they read as zeros = black, so transparent stamp + black canvas
    = invisible object). White flattening makes orientation cues
    (cast shadows, asymmetric details) readable.
    """
    im = Image.open(png_path).convert("RGBA")
    canvas = Image.new("RGBA", im.size, (255, 255, 255, 255))
    canvas.paste(im, (0, 0), im)
    return canvas.convert("RGB")


_DUMMY_IMG: Image.Image | None = None


def _dummy_image() -> Image.Image:
    """White 224x224 placeholder used only to satisfy AutoModel.forward's
    image input when we want text embeddings via the unified forward.

    `model.get_text_features(**inputs)` returns BaseModelOutputWithPooling
    on the transformers version pinned in this script's deps (a known
    upstream regression — see HF issue tracker), so we call the
    full forward and read `out.text_embeds` instead.
    """
    global _DUMMY_IMG
    if _DUMMY_IMG is None:
        _DUMMY_IMG = Image.new("RGB", (224, 224), (255, 255, 255))
    return _DUMMY_IMG


def encode_label_set(processor: AutoProcessor, model: AutoModel,
                     prompts: dict[str, list[str]], device: str) -> tuple[list[str], torch.Tensor]:
    """Average-pool the text embeddings of each label's paraphrase set."""
    labels: list[str] = []
    embeddings: list[torch.Tensor] = []
    img = _dummy_image()
    is_siglip = "siglip" in (model.config._name_or_path or "").lower() if hasattr(model.config, "_name_or_path") else False
    pad_kwargs = {"padding": "max_length"} if is_siglip else {"padding": True}
    for label, paraphrases in prompts.items():
        inputs = processor(text=paraphrases, images=[img] * len(paraphrases),
                           return_tensors="pt", **pad_kwargs).to(device)
        with torch.no_grad():
            out = model(**inputs)
        emb = out.text_embeds  # already projected; not yet normalized
        emb = emb / emb.norm(dim=-1, keepdim=True)
        avg = emb.mean(dim=0, keepdim=True)
        avg = avg / avg.norm(dim=-1, keepdim=True)
        labels.append(label)
        embeddings.append(avg)
    return labels, torch.cat(embeddings, dim=0)  # (n_labels, dim)


def classify_image(im: Image.Image, processor: AutoProcessor, model: AutoModel,
                   labels: list[str], label_emb: torch.Tensor, device: str) -> tuple[str | None, float]:
    """Return (label, margin) where margin = top_prob - second_prob."""
    # Pair the image with a single throwaway text to drive the unified
    # forward, then read image_embeds.
    is_siglip = "siglip" in (model.config._name_or_path or "").lower() if hasattr(model.config, "_name_or_path") else False
    pad_kwargs = {"padding": "max_length"} if is_siglip else {"padding": True}
    inputs = processor(text=["x"], images=[im], return_tensors="pt", **pad_kwargs).to(device)
    with torch.no_grad():
        out = model(**inputs)
    img_emb = out.image_embeds
    img_emb = img_emb / img_emb.norm(dim=-1, keepdim=True)
    sim = (img_emb @ label_emb.T).squeeze(0)  # (n_labels,)
    probs = torch.softmax(sim * 100.0, dim=0).cpu().tolist()  # CLIP uses temp 100
    sorted_pairs = sorted(zip(labels, probs), key=lambda kv: -kv[1])
    margin = sorted_pairs[0][1] - sorted_pairs[1][1]
    return sorted_pairs[0][0], margin


def update_yaml_orientation(yaml_path: Path, orientation: str | None) -> bool:
    """Set `orientation: <value>` (preserving file structure). Returns True if changed."""
    text = yaml_path.read_text()
    new_value = "null" if orientation is None else orientation
    new_text, n = re.subn(r"^orientation:.*$", f"orientation: {new_value}",
                          text, count=1, flags=re.MULTILINE)
    if n == 0:
        return False
    if new_text == text:
        return False
    yaml_path.write_text(new_text)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None,
                    help="filter to PNG stems starting with this string")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing non-null orientation values")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap number of stamps processed (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print classifications but don't write yamls")
    ap.add_argument("--conf-margin", type=float, default=CONF_MARGIN,
                    help=f"required prob margin (default {CONF_MARGIN})")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"loading {MODEL_NAME} on {device}...", file=sys.stderr)
    processor = AutoProcessor.from_pretrained(MODEL_NAME)
    model = AutoModel.from_pretrained(MODEL_NAME).to(device).eval()
    is_siglip = "siglip" in MODEL_NAME.lower()

    angle_labels, angle_emb = encode_label_set(processor, model, ANGLE_PROMPTS, device)
    facing_labels, facing_emb = encode_label_set(processor, model, FACING_PROMPTS, device)

    pngs = sorted(STAMPS_DIR.glob("*.png"))
    if args.source:
        pngs = [p for p in pngs if p.stem.startswith(args.source)]
    if args.limit:
        pngs = pngs[:args.limit]

    counts: dict[str, int] = {}
    written = 0
    skipped_low_conf = 0
    skipped_existing = 0
    for i, png in enumerate(pngs, 1):
        yaml_path = png.with_suffix(".yaml")
        if not yaml_path.exists():
            continue
        d = yaml.safe_load(yaml_path.read_text()) or {}
        existing = d.get("orientation")
        if existing and not args.force:
            skipped_existing += 1
            continue

        im = load_image_for_clip(png)
        angle, ang_margin = classify_image(im, processor, model, angle_labels, angle_emb, device)
        if ang_margin < args.conf_margin:
            decision: str | None = None
            reason = f"angle margin too low ({ang_margin:.2f})"
        elif angle == "top-down":
            decision = "top-down"
            reason = f"top-down (margin {ang_margin:.2f})"
        else:  # isometric
            facing, fac_margin = classify_image(im, processor, model, facing_labels, facing_emb, device)
            if fac_margin < args.conf_margin:
                decision = "isometric"
                reason = f"isometric, facing-uncertain (margin {fac_margin:.2f})"
            else:
                decision = facing  # north/south/east/west
                reason = f"isometric → {facing} (angle margin {ang_margin:.2f}, facing margin {fac_margin:.2f})"

        counts[decision or "null"] = counts.get(decision or "null", 0) + 1
        if decision is None:
            skipped_low_conf += 1
            if args.dry_run:
                print(f"[skip] {png.name}: {reason}")
            continue

        if args.dry_run:
            print(f"[dry] {png.name}: {decision}  ({reason})")
            continue

        if update_yaml_orientation(yaml_path, decision):
            written += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(pngs)}] {png.name}: {decision}", file=sys.stderr)

    print(f"\nwrote: {written}")
    print(f"skipped (existing): {skipped_existing}")
    print(f"skipped (low confidence): {skipped_low_conf}")
    print(f"distribution:")
    for label, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
