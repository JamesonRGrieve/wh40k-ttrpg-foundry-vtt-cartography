#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "opencv-python-headless", "PyYAML", "requests", "ruamel.yaml"]
# ///
"""Generate the PDF-trooper portrait pool for the wh40k-rpg homebrew bestiary.

Renders role-appropriate Planetary Defence Force portraits on the lab ComfyUI
(Chroma-Flux, via the proven BattlemapInteriorV1 workflow), auto-frames each into
a token bust {cx,cy,zoom} with YuNet, saves them into the packs-private image
tree, and (with --wire) appends each as a {img, tokenFrame} entry to the matching
actor's system.portraits.variants[] — the multi-art pool #567 draws from on spawn.

Phases:
  (default)  render + autoframe + save PNGs + write manifest.json
  --wire     read manifest.json and append variants[] into the actor _source JSON

  --limit N  cap total renders (validation); --role SLUG restrict to one role
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VAULT = Path("/home/jameson/Source/dh-campaign")
LORA = VAULT / ".lora-training"
SCRIPTS = VAULT / "scripts"
PACKS = VAULT / ".foundry-system/src/packs-private"
IMG_DIR = PACKS / "images/bestiary/dh2"
ACTORS_DIR = PACKS / "homebrew-gw-copyright/hb-dh2-actors-bestiary/_source"
IMG_URL_PREFIX = "systems/wh40k-rpg/packs/images/bestiary/dh2"
SERVER = "http://198.51.100.11:8188"

sys.path.insert(0, str(LORA))
sys.path.insert(0, str(SCRIPTS))
from generate_character_portrait import render_portrait  # type: ignore[import-not-found]
from autoframe_tokens import compute_frame, detect_face  # type: ignore[import-not-found]
from PIL import Image  # noqa: E402

# Bust portraits: face high in frame, ~768x1024 (matches the character bust slot).
WIDTH, HEIGHT = 768, 1024

# clip_l is the short style/mood anchor shared by every PDF portrait.
CLIP_L = "grimdark sci-fi portrait, warhammer 40k, planetary defence force, painterly concept illustration"

# The shared PDF-levy look, prepended to every role prompt.
BASE = (
    "A head-and-shoulders bust portrait of an Imperial Planetary Defence Force soldier, "
    "a hive-world conscript in mass-issue stamped flak armour over drab olive-grey fatigues, "
    "worn webbing and pouches, "
)
# The campaign style tail, appended to every role prompt. Slightly painterly —
# loose visible brushwork over the detail, not a smooth photo, not a full oil.
TAIL = (
    " Dark muted earth tones, industrial grime, painterly illustration with loose visible brushwork, "
    "fine detail on the face, dramatic chiaroscuro lighting, dark moody atmosphere, "
    "highly detailed, single character."
)

# Random grimdark backdrops so the pool isn't a wall of identical studio busts.
BACKGROUNDS = [
    "a smog-choked hive trench line",
    "a battered rockcrete bulkhead streaked with rust",
    "a burning war-torn manufactorum",
    "a rubble-strewn hab-block under a dark sky",
    "a fortified sandbagged firing line wreathed in smoke",
    "an ash-wasteland beneath roiling storm clouds",
    "a dim garrison corridor lit by caged lumen strips",
    "a shattered hive spire silhouetted against a blood-red sky",
    "a mud-and-razorwire trench under falling ash",
    "a cavernous manufactorum gantry in green phosphor light",
]

# Variation axes cycled by image index so a squad reads as distinct people.
GENDERS = ["a young man", "a weathered woman", "a middle-aged man", "a hard-faced woman",
           "a gaunt young woman", "a thickset man", "a scarred man", "a stern woman"]
AGES = ["in their early twenties", "in their thirties", "in their forties", "grey at the temples"]
CONDITION = ["helmet on, visor up", "bareheaded, cropped hair", "helmet on, chin-strap tight",
             "bareheaded, sweat-streaked", "hooded against the cold"]
WEAR = ["kit clean and freshly issued", "armour scuffed and dust-caked",
        "battle-worn, soot on the face", "rain-soaked and mud-spattered"]

# role slug -> (weight, role-specific descriptor clause)
ROLES: dict[str, tuple[int, str]] = {
    "pdf-trooper":      (30, "cradling a mass-issue autogun, a rank-and-file line trooper, "
                             "a stamped double-headed eagle pressed into the shoulder plate"),
    "pdf-lastrooper":   (15, "shouldering a standard-pattern lasgun with a glowing power cell, line infantry"),
    "pdf-sergeant":     (6,  "a section sergeant with rank chevrons stencilled on the pauldron, "
                             "a holstered laspistol and a chainsword at the hip, commanding and grim"),
    "pdf-heavy-gunner": (6,  "a heavy weapons trooper braced behind a belt-fed heavy stubber, "
                             "draped in linked ammunition, reinforced shoulder guard"),
    "pdf-breacher":     (6,  "an assault breacher behind a heavy ballistic riot slab-shield, "
                             "a short combat shotgun, extra-thick armour plates"),
    "pdf-grenadier":    (6,  "a grenadier hung with a bandolier of frag grenades, "
                             "a stubby grenade launcher, ammo satchels"),
    "pdf-medic":        (6,  "a field medic with a bulging medicae satchel and blood-stained gloves, "
                             "a red medicae marking on the shoulder, a diagnostor slung at the neck"),
    "pdf-vox-operator": (6,  "a vox-operator carrying a bulky backpack vox-caster with a tall whip antenna, "
                             "a handset pressed to one ear, cables looping to the set"),
    "pdf-sharpshooter": (6,  "a marksman with a long-barrelled scoped long-las, "
                             "a drab sniper's shroud over the shoulders, one eye narrowed"),
    "pdf-riot-officer": (6,  "a riot-control officer with a visored enclosed helmet, a transparent riot shield, "
                             "a crackling shock maul, segmented armour"),
    "pdf-officer":      (7,  "a PDF officer in a peaked cap and long storm-coat over the flak, "
                             "gold rank braid, a power sword and ornate laspistol, an air of cold command"),
}


def build_prompt(role_clause: str, idx: int) -> str:
    subj = f"{GENDERS[idx % len(GENDERS)]} {AGES[idx % len(AGES)]}, {CONDITION[idx % len(CONDITION)]}"
    bg = BACKGROUNDS[idx % len(BACKGROUNDS)]
    return f"{BASE}{subj}, {role_clause}, {WEAR[idx % len(WEAR)]}, set against {bg}.{TAIL}"


def render_role(slug: str, count: int, start_seed: int, dry: bool) -> list[dict]:
    _, clause = ROLES[slug]
    out: list[dict] = []
    for n in range(1, count + 1):
        seed = start_seed + n
        stem = f"{slug}-{n:02d}"
        dest = IMG_DIR / f"{stem}.png"
        t5 = build_prompt(clause, n - 1)
        # Resumable: an already-rendered portrait is reused (frame recomputed),
        # so an interrupted batch continues cleanly and validated art is kept.
        if dest.exists() and not dry:
            w, h = Image.open(dest).size
            face, _ = detect_face(dest)
            cx, cy, zoom, _had = compute_frame(w, h, face)
            out.append({"img": f"{IMG_URL_PREFIX}/{stem}.png",
                        "tokenFrame": {"cx": cx, "cy": cy, "zoom": zoom}})
            print(f"[{slug}] {n}/{count} exists, reuse -> {dest.name}", file=sys.stderr)
            continue
        print(f"[{slug}] {n}/{count} seed={seed} -> {dest.name}", file=sys.stderr)
        if dry:
            continue
        raw = render_portrait(server=SERVER, t5xxl=t5, clip_l=CLIP_L,
                              width=WIDTH, height=HEIGHT, seed=seed, prefix=f"_pdf_{stem}")
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, dest)
        w, h = Image.open(dest).size
        face, _ = detect_face(dest)
        cx, cy, zoom, had = compute_frame(w, h, face)
        print(f"        framed cx={cx} cy={cy} zoom={zoom} face={had}", file=sys.stderr)
        out.append({"img": f"{IMG_URL_PREFIX}/{stem}.png",
                    "tokenFrame": {"cx": cx, "cy": cy, "zoom": zoom}})
    return out


def actor_path(slug: str) -> Path:
    hits = sorted(ACTORS_DIR.glob(f"{slug}_*.json"))
    if not hits:
        sys.exit(f"no actor _source for {slug} under {ACTORS_DIR}")
    return hits[0]


def cmd_render(args: argparse.Namespace) -> int:
    roles = {args.role: ROLES[args.role]} if args.role else ROLES
    manifest: dict[str, list[dict]] = {}
    seed = args.seed
    made = 0
    for slug, (count, _) in roles.items():
        if args.limit and made >= args.limit:
            break
        n = min(count, args.limit - made) if args.limit else count
        manifest[slug] = render_role(slug, n, seed, args.dry)
        made += n
        seed += 1000
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2))
    total = sum(len(v) for v in manifest.values())
    print(f"{'DRY ' if args.dry else ''}rendered {total} portraits across {len(manifest)} roles; "
          f"manifest -> {HERE / 'manifest.json'}")
    return 0


def cmd_wire(_args: argparse.Namespace) -> int:
    manifest = json.loads((HERE / "manifest.json").read_text())
    for slug, variants in manifest.items():
        if not variants:
            continue
        p = actor_path(slug)
        doc = json.loads(p.read_text())
        sysd = doc.setdefault("system", {})
        pool = sysd.setdefault("portraits", {"variants": [], "pinned": None})
        existing = {v.get("img") for v in pool.get("variants") or []}
        added = [v for v in variants if v["img"] not in existing]
        pool.setdefault("variants", [])
        pool["variants"].extend(added)
        pool.setdefault("pinned", None)
        p.write_text(json.dumps(doc, indent=4, ensure_ascii=False) + "\n")
        print(f"{slug}: +{len(added)} variants (pool now {len(pool['variants'])}) -> {p.name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wire", action="store_true", help="append manifest variants into actor _source JSON")
    ap.add_argument("--role", choices=sorted(ROLES), help="restrict to one role")
    ap.add_argument("--limit", type=int, default=0, help="cap total renders (validation)")
    ap.add_argument("--seed", type=int, default=70000)
    ap.add_argument("--dry", action="store_true", help="print plan, render nothing")
    args = ap.parse_args()
    return cmd_wire(args) if args.wire else cmd_render(args)


if __name__ == "__main__":
    raise SystemExit(main())
