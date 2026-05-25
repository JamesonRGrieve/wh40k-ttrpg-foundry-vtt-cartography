#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "python-dotenv", "pillow", "PyYAML"]
# ///
"""One-off regen for weak treatments + IMAGE_SAFETY retries.

Strengthens prompts for files where Gemini snapped to the wrong
material (rendered metal when prompted for stone, polished when
prompted for scratched, etc.) and softens prompts for ones that
hit the safety filter.
"""
import os, sys, time
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image
from google import genai

HERE = Path(__file__).resolve().parent
PROJECT = HERE  # dh-campaign/.lora-training (pipeline root; holds .env)
load_dotenv(PROJECT / ".env")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

ISOLATION = ("single symbol focal subject filling most of the frame, "
             "full silhouette visible, no text, no caption.")

# Each entry: (folder, output_filename, reference_filename, prompt, caption)
JOBS = [
    # Weak treatment fixes — strengthened prompts emphasizing the surface
    ("iconography-ministorum-sigil",
     "sym_ministorum_17_carved_stone_frieze_running_along_the_facade_of_.png",
     "ministorum_isolated.png",
     "Reproduce the heraldic silhouette from the reference image (Adeptus Ministorum sigil, "
     "skull within spiked sun circle on capital I-bar). Render it ENTIRELY as raw weathered "
     "stone — the surface IS pale grey limestone with visible chisel marks and surface "
     "erosion, NO metal, NO brass, NO polish. The symbol is carved INTO a stone frieze "
     "running along a hive cathedral facade, framed by additional gothic stone ornament. "
     "View: low-angle looking up. Lighting: diffuse overcast grey daylight. " + ISOLATION,
     "sym_ministorum, Adeptus Ministorum sigil, skull within spiked sun circle on capital "
     "I-bar, carved stone frieze running along the facade of a hive cathedral, " + ISOLATION),

    ("iconography-ministorum-sigil",
     "sym_ministorum_23_scratched_into_ferrocrete_by_a_serf_s_hand_tool_.png",
     "ministorum_isolated.png",
     "Reproduce the heraldic silhouette from the reference image (Adeptus Ministorum sigil, "
     "skull within spiked sun circle on capital I-bar). Render it as ROUGH SHALLOW "
     "SCRATCHES carved by a serf's hand-tool into a raw ferrocrete wall. The surface IS "
     "pitted concrete — the symbol is just shallow scored lines, NO metal, NO polish, NO "
     "depth, like primitive graffiti scratched with a sharp stone. "
     "View: oblique side angle. Lighting: sodium-yellow industrial side light. " + ISOLATION,
     "sym_ministorum, Adeptus Ministorum sigil, skull within spiked sun circle on capital "
     "I-bar, scratched into ferrocrete by a serf's hand-tool, shallow rough lines, " + ISOLATION),

    ("iconography-navy-sigil",
     "sym_imperial_navy_17_carved_stone_frieze_running_along_the_facade_of_.png",
     "imperial_navy_isolated.png",
     "Reproduce ONLY the heraldic silhouette from the reference image (Imperial Navy sigil, "
     "winged eagle above central cog on capital I-bar) — no additional decorative carvings. "
     "Render it ENTIRELY as raw weathered stone — the surface IS pale grey limestone with "
     "visible chisel marks. The single sigil is carved into a stone frieze on a naval "
     "academy facade. NO additional gothic ornament around it, NO secondary statues. "
     "View: low-angle looking up. Lighting: diffuse overcast grey daylight. " + ISOLATION,
     "sym_imperial_navy, Imperial Navy sigil, winged eagle above central cog on capital "
     "I-bar, carved stone frieze running along the facade of a naval academy, " + ISOLATION),

    ("iconography-navy-sigil",
     "sym_imperial_navy_23_scratched_into_ferrocrete_by_a_serf_s_hand_tool_.png",
     "imperial_navy_isolated.png",
     "Reproduce the heraldic silhouette from the reference image (Imperial Navy sigil, "
     "winged eagle above central cog on capital I-bar). Render it as DEEP SCORED "
     "SCRATCHES carved by a serf's hand-tool into a raw ferrocrete wall. The surface IS "
     "pitted concrete — the symbol is bold rough scored lines, NO metal, NO polish, "
     "shadows in the grooves indicate depth. View: oblique side angle. "
     "Lighting: sodium-yellow industrial side light, harsh oblique shadows. " + ISOLATION,
     "sym_imperial_navy, Imperial Navy sigil, winged eagle above central cog on capital "
     "I-bar, scratched into ferrocrete by a serf's hand-tool, deep rough lines, " + ISOLATION),

    # IMAGE_SAFETY retries — softened wording
    ("iconography-administratum-sigil",
     "sym_administratum_19_stained_glass_window_in_a_hive_cathedral_casting.png",
     "administratum_isolated.png",
     "Reproduce the heraldic silhouette from the reference image (Adeptus Administratum "
     "sigil, capital I-bar with circular central glyph) as the central design of a stained "
     "glass window in an Imperial scriptorium. The window is the dominant subject. Soft "
     "afternoon light comes through the glass. "
     "View: front-on, dead centered. Lighting: warm daylight through the colored glass. "
     + ISOLATION,
     "sym_administratum, Adeptus Administratum sigil, capital I-bar with circular central "
     "glyph, stained glass window in a scriptorium, " + ISOLATION),

    ("iconography-administratum-sigil",
     "sym_administratum_24_tattooed_in_black_ink_on_weathered_skin_of_a_gua.png",
     "administratum_isolated.png",
     "Reproduce the heraldic silhouette from the reference image (Adeptus Administratum "
     "sigil, capital I-bar with circular central glyph) as a black ink tattoo design "
     "displayed on a piece of tan parchment beside a tattoo artist's tools. Single design "
     "centered on the parchment. View: high-angle looking down at the parchment on a "
     "wooden table. Lighting: warm candlelight. " + ISOLATION,
     "sym_administratum, Adeptus Administratum sigil, capital I-bar with circular central "
     "glyph, black ink tattoo design on parchment, " + ISOLATION),
]


def run_one(folder: str, fname: str, ref: str, prompt: str, caption: str) -> tuple[bool, str]:
    folder_path = PROJECT / "lora-training" / folder
    out_png = folder_path / fname
    out_txt = out_png.with_suffix(".txt")
    ref_path = folder_path / ref
    if not ref_path.exists():
        return False, f"reference missing: {ref_path}"
    if out_png.exists():
        out_png.unlink()  # always replace for regen
    ref_im = Image.open(ref_path).convert("RGB")
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[prompt, ref_im],
        )
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"
    cand = (resp.candidates or [None])[0]
    if cand is None or getattr(cand, "content", None) is None:
        finish = getattr(cand, "finish_reason", None) if cand else None
        return False, f"content None / finish_reason={finish}"
    png_bytes = None
    for part in cand.content.parts or []:
        if part.inline_data and part.inline_data.data:
            png_bytes = part.inline_data.data
            break
    if not png_bytes:
        finish = getattr(cand, "finish_reason", None)
        return False, f"no image part / finish_reason={finish}"
    out_png.write_bytes(png_bytes)
    out_txt.write_text(caption + "\n")
    return True, f"saved {len(png_bytes)} bytes"


for i, (folder, fname, ref, prompt, caption) in enumerate(JOBS, 1):
    if i > 1:
        time.sleep(4)
    print(f"[{i}/{len(JOBS)}] {folder}/{fname}", file=sys.stderr)
    ok, msg = run_one(folder, fname, ref, prompt, caption)
    print(f"  {'[ok]' if ok else '[fail]'} {msg}", file=sys.stderr)
