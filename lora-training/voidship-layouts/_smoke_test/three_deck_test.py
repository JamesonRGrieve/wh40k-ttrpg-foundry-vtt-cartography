#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "python-dotenv", "pillow"]
# ///
"""3-deck frigate inference test — pass one frigate hull as reference,
generate three different deck layouts on that same hull bbox.

Validates the two-LoRA architecture intent: the hull is a fixed
input image, the deck layouts are language-described variations
overlaid on the hull. All three decks register on the same bbox
because the hull image is identical across all three calls.

Decks rendered:
  1. Bridge deck      — short floor plan; only forward 50% has rooms,
                        aft 50% is plain plating (no interior on this
                        deck — internal stairwell to deck 2).
  2. Main deck        — full layout with crew, broadside batteries,
                        and the single rear airlock egress.
  3. Mechanical deck  — engineering throughout, engine cutouts at
                        stern visible, internal-only access (no egress).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image
from google import genai

REPO = Path("/home/jameson/Documents/dh-campaign/.foundry/cartography")
HULL = REPO / "lora-training/voidship-hulls/hull-frigate-escort/frigate-escort_01_weathered_with_rust_streaks_and_.png"
OUT = REPO / "lora-training/voidship-layouts/_smoke_test/3deck_frigate"

PREAMBLE = (
    "Use the attached reference image as the EXACT hull silhouette. "
    "Preserve the hull outline, plating, lateral sponson positions, "
    "gothic prow shape, dorsal heraldry, and aspect ratio of the "
    "reference image PIXEL-FOR-PIXEL — the new image must be the "
    "SAME ship rendered from the SAME top-down angle, with the "
    "interior layout described below superimposed onto the hull.\n\n"
    "Composition: top-down orthographic battlemap. Bow at the LEFT, "
    "stern at the RIGHT, port at the TOP, starboard at the BOTTOM. "
    "Outside the hull is flat black void. The hull outline is "
    "identical to the reference — do not change the silhouette, do "
    "not move the sponsons, do not redraw the prow. Only the "
    "interior changes between this image and the reference.\n\n"
)

DECKS = [
    {
        "id": "deck_3_bridge",
        "name": "Deck 3 — Bridge Deck (top deck, short floor plan)",
        "layout": (
            "BRIDGE DECK (top of the stack — short floor plan, only "
            "the forward half of the hull is occupied with rooms; the "
            "aft half is solid plating from this top-down view "
            "because the deck physically does not extend that far "
            "back, the hull continues but there is no deck floor "
            "there from this deck's perspective).\n\n"
            "Zones:\n"
            "  - prow_port: port-side forward sensor blister, small "
            "    wedge room with a single sensor console facing "
            "    port-forward.\n"
            "  - prow_center: command bridge — sunken pit with five "
            "    console stations (helm, navigation, sensors, comms, "
            "    weapons) arranged in a shallow arc facing the prow "
            "    tip, elevated commander's chair on a raised platform "
            "    at the aft end of the pit.\n"
            "  - prow_starboard: starboard-side forward sensor "
            "    blister, small wedge room with a single sensor "
            "    console facing starboard-forward.\n"
            "  - forward_port: officer's wardroom with desk and "
            "    chairs (empty in this base map).\n"
            "  - forward_center: short central corridor running aft "
            "    to a single internal stairwell down to the main "
            "    deck (drawn as a small square stairwell hatch in "
            "    the floor at the aft end of this corridor).\n"
            "  - forward_starboard: navigation chartroom with a "
            "    central plotting table.\n\n"
            "MID, AFT, AND STERN ZONES ARE EMPTY — render those "
            "sections as plain hull plating with no doorways, no "
            "rooms, no corridors, no furniture (this deck does not "
            "extend that far back; the hull continues but there is "
            "no floor here from this deck's perspective). The "
            "lateral broadside sponson positions visible in the "
            "reference image remain present as part of the hull "
            "outline but are not accessible from this deck.\n\n"
            "EGRESS: NONE on this deck — internal stairwell only "
            "(drawn as a square hatch in the floor at the aft end "
            "of the bridge's central corridor)."
        ),
    },
    {
        "id": "deck_2_main",
        "name": "Deck 2 — Main Deck (with rear airlock egress)",
        "layout": (
            "MAIN DECK (middle of the stack — full hull-length floor "
            "plan, every section has rooms).\n\n"
            "Zones:\n"
            "  - prow_full: secondary command station and forward "
            "    damage-control center spanning the full prow width "
            "    (this deck is BELOW the bridge so it has its own "
            "    smaller command station).\n"
            "  - forward_full: central spinal corridor running "
            "    bow-to-stern, lined with empty ordnance lockers "
            "    along port and starboard inner walls.\n"
            "  - mid_port: lateral broadside gun-battery room — "
            "    three empty turret pintles aligned along the port "
            "    hull edge, gun barrels pointing OUTWARD TO PORT "
            "    (NOT FORWARD) and protruding from the port "
            "    sponsons visible in the reference image. Single "
            "    door from spinal corridor.\n"
            "  - mid_center: central spinal corridor continuation, "
            "    doors port and starboard to broadside batteries.\n"
            "  - mid_starboard: lateral broadside gun-battery room "
            "    — three empty turret pintles aligned along the "
            "    starboard hull edge, gun barrels pointing OUTWARD "
            "    TO STARBOARD (NOT FORWARD) and protruding from the "
            "    starboard sponsons visible in the reference image. "
            "    Single door from spinal corridor.\n"
            "  - aft_port: officer's cabin (single small room with "
            "    a desk against the port hull).\n"
            "  - aft_center: crew bunkroom — two rows of empty bunk "
            "    frames stacked along port and starboard inner "
            "    walls, central aisle.\n"
            "  - aft_starboard: officer's cabin (single small room "
            "    with a desk against the starboard hull).\n"
            "  - stern_full: rear airlock vestibule and small "
            "    storage room, full beam, single egress airlock at "
            "    the centerline of the stern bulkhead.\n\n"
            "EGRESS: rear personnel airlock at the stern centerline, "
            "single small rectangular hatch flush with the stern "
            "bulkhead — the ONLY external opening on the entire "
            "ship across all three decks."
        ),
    },
    {
        "id": "deck_1_mechanical",
        "name": "Deck 1 — Mechanical Deck (bottom deck, engine cutouts)",
        "layout": (
            "MECHANICAL DECK (bottom of the stack — engineering "
            "throughout. The engines are ONLY on this deck; the "
            "stern engine block visible on the reference hull is "
            "this deck's stern).\n\n"
            "Zones:\n"
            "  - prow_port: forward fuel handling room with empty "
            "    fuel-line manifolds along the port hull.\n"
            "  - prow_center: forward capacitor bank — banks of "
            "    plasma capacitors recessed into the deck plating, "
            "    arranged in two rows.\n"
            "  - prow_starboard: forward fuel handling room with "
            "    empty fuel-line manifolds along the starboard hull.\n"
            "  - forward_full: central engineering corridor lined "
            "    with reactor monitoring stations (empty consoles) "
            "    along port and starboard.\n"
            "  - mid_port: port broadside ammunition magazine for "
            "    the deck-2 broadside guns above (empty munitions "
            "    racks visible).\n"
            "  - mid_center: main reactor chamber — large central "
            "    cylindrical reactor housing recessed into the "
            "    deck, with a circular maintenance walkway around "
            "    its base.\n"
            "  - mid_starboard: starboard broadside ammunition "
            "    magazine for the deck-2 broadside guns above "
            "    (empty munitions racks visible).\n"
            "  - aft_full: plasma drive interface bay — the forward "
            "    coupling between the reactor and the main engine "
            "    cores at the stern. Visible as a network of thick "
            "    plasma conduits running aft.\n"
            "  - stern_full: rear engineering bay and main engine "
            "    cores. ENGINE CUTOUTS VISIBLE: three large "
            "    circular plasma drive cores recessed into the "
            "    deck, each one flush with the stern bulkhead. "
            "    This is where the stern engine block on the "
            "    reference hull lives.\n\n"
            "EGRESS: NONE on this deck — internal stairwell from "
            "the main deck above is the only access (drawn as a "
            "square hatch in the floor at the forward end of the "
            "central engineering corridor)."
        ),
    },
]

HARD_RULES = (
    "Hard constraints:\n"
    "- The hull silhouette MUST match the reference image exactly. "
    "Do not change the prow, do not change the sponson positions, "
    "do not change the aspect ratio, do not change the heraldry on "
    "the dorsal spine.\n"
    "- Render rooms as empty floor plates with thin wall lines "
    "between them; do NOT render furniture, crates, consoles, "
    "bunks, equipment, or NPCs (those go on the Foundry stamp "
    "layer at the table).\n"
    "- The lateral broadside sponsons in the reference image are "
    "the ONLY hull protrusions; do NOT add forward-facing turrets, "
    "dorsal turrets, or bow gun arrays.\n"
    "- This is a battlemap, not a cutaway diagram. The interior is "
    "drawn AS A TOP-DOWN FLOOR PLAN inside the hull silhouette.\n"
    "- No text, no compass, no scale, no labels, no legend.\n"
)

def main() -> int:
    load_dotenv(REPO / ".env")
    if "GEMINI_API_KEY" not in os.environ:
        print("missing GEMINI_API_KEY"); return 1
    if not HULL.is_file():
        print(f"missing hull reference: {HULL}"); return 1
    OUT.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    hull_im = Image.open(HULL).convert("RGB")
    last = 0.0
    for n, deck in enumerate(DECKS, 1):
        elapsed = time.monotonic() - last
        if elapsed < 4.0:
            time.sleep(4.0 - elapsed)
        last = time.monotonic()
        prompt = PREAMBLE + f"INTERIOR LAYOUT: {deck['name']}.\n\n{deck['layout']}\n\n{HARD_RULES}"
        out_png = OUT / f"{deck['id']}.png"
        out_txt = OUT / f"{deck['id']}.prompt.txt"
        out_txt.write_text(prompt)
        print(f"[{n}/{len(DECKS)}] {deck['id']} -> {out_png.name}")
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[prompt, hull_im])
        except Exception as e:
            print(f"  [fail] {type(e).__name__}: {str(e)[:160]}"); continue
        cand = (resp.candidates or [None])[0]
        if cand is None or getattr(cand, "content", None) is None:
            fr = getattr(cand, "finish_reason", None) if cand else None
            print(f"  [fail] no content (finish_reason={fr})"); continue
        png = None
        for p in cand.content.parts or []:
            if p.inline_data and p.inline_data.data:
                png = p.inline_data.data; break
            elif p.text:
                print(f"  [text] {p.text[:160]}")
        if not png:
            print(f"  [fail] no image part"); continue
        out_png.write_bytes(png)
        print(f"  [ok] saved {len(png)} bytes -> {out_png}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
