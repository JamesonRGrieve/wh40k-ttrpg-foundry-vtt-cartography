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
Zero-shot state classifier for stamps.

The `state` field in stamp sidecars is currently ~25% populated. The
caption-based heuristics in classify_stamps.py only catch overt
keywords ("damaged", "destroyed", "active"). Most stamps don't trigger
those, so they stay null even when visibly damaged or active.

This script runs CLIP zero-shot directly against each stamp PNG to
classify the visible state. Two-stage:

1. **Damage state**: intact / damaged / destroyed / n/a.
   - intact: clean, undamaged
   - damaged: visible scoring, scoring, dents, cracks, partial wear
   - destroyed: shattered, on fire, broken apart, ruined
   - n/a: state-neutral (e.g. parchment scroll, abstract symbol)
2. **Activation state** (only when angle suggests "device-like" — see
   ACTIVATABLE_HINT_LABELS): active / inactive / n/a.

`active` and `damaged` are independently meaningful, so we encode the
final state field as one of the seven values currently allowed in
the schema {intact, damaged, destroyed, active, inactive,
contagii-bond, n/a}. Two writeable layers:
  - If activation is meaningful AND determinative, write active/inactive.
  - Else write the damage-state result.

Owner-only on `state`. Caption-derived values are preserved; CLIP
overwrites only when CONF_MARGIN is exceeded AND the existing value
is null.

Usage:
    uv run classify_state.py [--source <stem>] [--force]
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
MODEL_NAME = "openai/clip-vit-large-patch14"

# The state field in the schema accepts these values (per CLAUDE.md /
# template). We only attempt to populate the visually-determinable
# subset; contagii-bond is narratively-determined and stays manual.
SCHEMA_STATES = {"intact", "damaged", "destroyed", "active", "inactive", "contagii-bond"}

CONF_MARGIN = 0.12
ACTIVATION_TRIGGER_MARGIN = 0.18  # higher bar — only override damage when activation is clear

DAMAGE_PROMPTS = {
    "intact": [
        "an undamaged object in pristine condition",
        "a clean, whole, well-maintained object",
        "an object in good repair with no visible damage",
    ],
    "damaged": [
        "an object with visible scratches, dents, or partial wear",
        "an object that has been damaged but is still mostly whole",
        "a worn, scuffed, or partially broken object",
    ],
    "destroyed": [
        "a shattered, broken-apart object in pieces",
        "a wrecked or burnt-out object beyond repair",
        "a completely destroyed object, ruined and disassembled",
    ],
    "stateless": [
        "a flat document, scroll, or piece of paper",
        "an abstract symbol or sigil with no physical wear concept",
        "a soft fabric item where damage is not meaningful",
    ],
}

ACTIVATION_PROMPTS = {
    "active": [
        "a device that is currently powered on, glowing or emitting light",
        "an active machine with visible illumination from screens or indicators",
        "a piece of equipment in operation, lit up and functioning",
    ],
    "inactive": [
        "a device that is currently powered off, dark and idle",
        "an unpowered machine with no visible illumination",
        "a piece of equipment in standby, not currently in use",
    ],
    "non-device": [
        "an inanimate object that cannot be powered on or off",
        "a piece of furniture, container, or static prop with no electronic state",
        "a passive object that has no electrical or mechanical activation",
    ],
}


def load_image_for_clip(png_path: Path) -> Image.Image:
    im = Image.open(png_path).convert("RGBA")
    canvas = Image.new("RGBA", im.size, (255, 255, 255, 255))
    canvas.paste(im, (0, 0), im)
    return canvas.convert("RGB")


_DUMMY_IMG: Image.Image | None = None


def _dummy_image() -> Image.Image:
    global _DUMMY_IMG
    if _DUMMY_IMG is None:
        _DUMMY_IMG = Image.new("RGB", (224, 224), (255, 255, 255))
    return _DUMMY_IMG


def encode_label_set(processor: AutoProcessor, model: AutoModel,
                     prompts: dict[str, list[str]], device: str) -> tuple[list[str], torch.Tensor]:
    labels: list[str] = []
    embeddings: list[torch.Tensor] = []
    img = _dummy_image()
    for label, paraphrases in prompts.items():
        inputs = processor(text=paraphrases, images=[img] * len(paraphrases),
                           return_tensors="pt", padding=True).to(device)
        with torch.no_grad():
            out = model(**inputs)
        emb = out.text_embeds
        emb = emb / emb.norm(dim=-1, keepdim=True)
        avg = emb.mean(dim=0, keepdim=True)
        avg = avg / avg.norm(dim=-1, keepdim=True)
        labels.append(label)
        embeddings.append(avg)
    return labels, torch.cat(embeddings, dim=0)


def classify_image(im: Image.Image, processor: AutoProcessor, model: AutoModel,
                   labels: list[str], label_emb: torch.Tensor, device: str) -> tuple[str, float]:
    inputs = processor(text=["x"], images=[im], return_tensors="pt", padding=True).to(device)
    with torch.no_grad():
        out = model(**inputs)
    img_emb = out.image_embeds
    img_emb = img_emb / img_emb.norm(dim=-1, keepdim=True)
    sim = (img_emb @ label_emb.T).squeeze(0)
    probs = torch.softmax(sim * 100.0, dim=0).cpu().tolist()
    sorted_pairs = sorted(zip(labels, probs), key=lambda kv: -kv[1])
    margin = sorted_pairs[0][1] - sorted_pairs[1][1]
    return sorted_pairs[0][0], margin


def update_yaml_state(yaml_path: Path, state: str | None) -> bool:
    text = yaml_path.read_text()
    new_value = "null" if state is None else state
    new_text, n = re.subn(r"^state:.*$", f"state: {new_value}",
                          text, count=1, flags=re.MULTILINE)
    if n == 0:
        return False
    if new_text == text:
        return False
    yaml_path.write_text(new_text)
    return True


def decide_state(damage: str, dam_margin: float, activation: str, act_margin: float,
                 conf_margin: float, act_margin_min: float) -> tuple[str | None, str]:
    """Combine damage + activation classifications into a final state value.

    Returns (state, reason). state is None if neither classifier is
    confident enough.

    Damage takes precedence — most stamps are static props and damage
    state is the more useful field. Activation overrides damage ONLY
    when:
      1. Activation classifier picked active/inactive (NOT non-device).
      2. Activation margin >= act_margin_min (high bar).
      3. Activation margin EXCEEDS the damage margin (i.e. CLIP is more
         sure this is a device-state question than a damage-state one).
      4. Damage said "intact" or "stateless" — never override "damaged"
         or "destroyed", which are stronger signals than "powered off".

    Without (3) and (4), "inactive" wins on every dim object because
    Flux-rendered stamps tend to be dim regardless of whether they're
    actually devices.
    """
    activation_eligible = (
        activation in {"active", "inactive"}
        and act_margin >= act_margin_min
        and act_margin > dam_margin
        and damage in {"intact", "stateless"}
    )
    if activation_eligible:
        return activation, f"activation={activation} (margin {act_margin:.2f}, beats damage {damage}/{dam_margin:.2f})"

    if dam_margin < conf_margin:
        return None, f"damage margin too low ({dam_margin:.2f})"
    if damage == "stateless":
        return None, f"stateless object (margin {dam_margin:.2f})"
    if damage in {"intact", "damaged", "destroyed"}:
        return damage, f"damage={damage} (margin {dam_margin:.2f})"
    return None, f"unknown damage label {damage!r}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=None,
                    help="filter to PNG stems starting with this string")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing non-null state values")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap number of stamps processed (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print classifications but don't write yamls")
    ap.add_argument("--conf-margin", type=float, default=CONF_MARGIN,
                    help=f"required prob margin for damage (default {CONF_MARGIN})")
    ap.add_argument("--activation-margin", type=float, default=ACTIVATION_TRIGGER_MARGIN,
                    help=f"required prob margin for activation override (default {ACTIVATION_TRIGGER_MARGIN})")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"loading {MODEL_NAME} on {device}...", file=sys.stderr)
    processor = AutoProcessor.from_pretrained(MODEL_NAME)
    model = AutoModel.from_pretrained(MODEL_NAME).to(device).eval()

    dam_labels, dam_emb = encode_label_set(processor, model, DAMAGE_PROMPTS, device)
    act_labels, act_emb = encode_label_set(processor, model, ACTIVATION_PROMPTS, device)

    pngs = sorted(STAMPS_DIR.glob("*.png"))
    if args.source:
        pngs = [p for p in pngs if p.stem.startswith(args.source)]
    if args.limit:
        pngs = pngs[: args.limit]

    counts: dict[str, int] = {}
    written = 0
    skipped_low_conf = 0
    skipped_existing = 0
    for i, png in enumerate(pngs, 1):
        yaml_path = png.with_suffix(".yaml")
        if not yaml_path.exists():
            continue
        d = yaml.safe_load(yaml_path.read_text()) or {}
        existing = d.get("state")
        if existing and not args.force:
            skipped_existing += 1
            continue

        im = load_image_for_clip(png)
        damage, dam_margin = classify_image(im, processor, model, dam_labels, dam_emb, device)
        activation, act_margin = classify_image(im, processor, model, act_labels, act_emb, device)
        decision, reason = decide_state(
            damage, dam_margin, activation, act_margin,
            conf_margin=args.conf_margin, act_margin_min=args.activation_margin,
        )

        counts[decision or "null"] = counts.get(decision or "null", 0) + 1
        if decision is None:
            skipped_low_conf += 1
            if args.dry_run:
                print(f"[skip] {png.name}: {reason}")
            continue

        if args.dry_run:
            print(f"[dry] {png.name}: {decision}  ({reason})")
            continue

        if update_yaml_state(yaml_path, decision):
            written += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(pngs)}] {png.name}: {decision}", file=sys.stderr)

    print(f"\nwrote: {written}")
    print(f"skipped (existing): {skipped_existing}")
    print(f"skipped (low confidence): {skipped_low_conf}")
    print("distribution:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
