#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "Pillow",
#   "numpy",
# ]
# ///
"""Drive the saved Chroma-Flux battlemap workflows on the ComfyUI server.

The two workflows that ship with the project (saved server-side under
`workflows/`) are loaded here as templates and submitted via the HTTP
API with parameter overrides. Outputs are downloaded into `battlemaps/`.

Workflows:

  interior   — txt2img Chroma-Flux at 1024x1024. Pure prompt-driven; no
               spatial control. Good for first-pass exploration.
  spacecraft — img2img with regional ConditioningSetMask per color in
               the input layout PNG. Strong spatial control; needs a
               hand-painted layout.

The script never edits the saved workflow files. Templates are loaded
fresh each run, mutated in memory, and submitted. Update the templates
on the ComfyUI server and re-pull (`./pull-workflows.sh` or curl the
`/api/userdata` endpoint) when the canonical pos/neg prompts change.

Stackable layers
----------------
Foundry V14 scenes accept a background image AND a foreground image.
Treating these as layers:

  * Base pass — full architectural render (floor + walls). Foundry
    background.
  * Walls-only pass (optional, --layered with --layout) — re-runs with
    every non-wall region prompt replaced by a "do not render anything,
    transparent flat color" prompt, then chromakeys the result. Foundry
    foreground.

Stamps populate the tile layer on top.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_SERVER = "http://198.51.100.11:8188"
HERE = Path(__file__).resolve().parent
CAMPAIGN_ROOT = HERE.parent.parent
AI_GEN = CAMPAIGN_ROOT / ".ai-gen"
WORKFLOWS_DIR = HERE / "workflows"
OUT_DIR = AI_GEN / "cartography" / "battlemaps"
POLL_TIMEOUT_S = 1500  # Chroma at 1024² is slow; ControlNet adds ~3-5x overhead.


# --- ComfyUI HTTP helpers (mirrors assign_groups.py patterns) ---------------


def submit_prompt(server: str, workflow: dict[str, Any], client_id: str) -> str:
    body = json.dumps({"prompt": workflow, "client_id": client_id}).encode()
    req = urllib.request.Request(
        f"{server}/prompt",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    if "prompt_id" not in payload:
        raise RuntimeError(f"ComfyUI rejected workflow: {payload}")
    return payload["prompt_id"]


def poll_history(server: str, prompt_id: str, *, timeout: float = POLL_TIMEOUT_S) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"{server}/history/{prompt_id}", timeout=10) as resp:
            data = json.loads(resp.read())
        record = data.get(prompt_id)
        if record and (record.get("status") or {}).get("completed"):
            return record
        time.sleep(2.0)
    raise TimeoutError(f"prompt {prompt_id} did not complete within {timeout}s")


def fetch_output_image(server: str, filename: str, subfolder: str = "") -> bytes:
    qs = f"filename={urllib.parse.quote(filename)}&type=output"
    if subfolder:
        qs += f"&subfolder={urllib.parse.quote(subfolder)}"
    with urllib.request.urlopen(f"{server}/view?{qs}", timeout=30) as resp:
        return resp.read()


def list_server_workflows(server: str) -> list[str]:
    with urllib.request.urlopen(f"{server}/api/userdata?dir=workflows", timeout=10) as resp:
        return json.loads(resp.read())


def fetch_server_workflow(server: str, name: str) -> dict[str, Any]:
    qname = urllib.parse.quote(f"workflows/{name}", safe="")
    with urllib.request.urlopen(f"{server}/api/userdata/{qname}", timeout=10) as resp:
        return json.loads(resp.read())


def write_server_workflow(server: str, name: str, body: dict[str, Any]) -> None:
    qname = urllib.parse.quote(f"workflows/{name}", safe="")
    req = urllib.request.Request(
        f"{server}/api/userdata/{qname}",
        data=json.dumps(body, indent=2).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def upload_input_image(server: str, image_path: Path, *, subfolder: str = "battlemap_layouts") -> str:
    """POST a local PNG to ComfyUI's /upload/image. Returns the server-side filename."""
    boundary = f"----dhmap{uuid.uuid4().hex}"
    image_bytes = image_path.read_bytes()
    body = bytearray()
    for field, value in (("subfolder", subfolder), ("type", "input"), ("overwrite", "true")):
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{value}\r\n".encode())
    body.extend(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{image_path.name}\"\r\n"
        "Content-Type: image/png\r\n\r\n".encode()
    )
    body.extend(image_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"{server}/upload/image",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        info = json.loads(resp.read())
    name = info.get("name") or image_path.name
    sub = info.get("subfolder") or subfolder
    return f"{sub}/{name}" if sub else name


# --- Workflow mutation ------------------------------------------------------


def load_template(name: str) -> dict[str, Any]:
    path = WORKFLOWS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"workflow template not found: {path}")
    return json.loads(path.read_text())


def set_prompt(workflow: dict[str, Any], node_id: str, *, t5xxl: str | None = None, clip_l: str | None = None) -> None:
    node = workflow.get(node_id)
    if not node or node.get("class_type") != "CLIPTextEncodeFlux":
        raise KeyError(f"node {node_id!r} is not a CLIPTextEncodeFlux")
    if t5xxl is not None:
        node["inputs"]["t5xxl"] = t5xxl
    if clip_l is not None:
        node["inputs"]["clip_l"] = clip_l


def set_dimensions(workflow: dict[str, Any], node_id: str, *, width: int, height: int) -> None:
    node = workflow[node_id]
    node["inputs"]["width"] = width
    node["inputs"]["height"] = height


def set_seed(workflow: dict[str, Any], node_id: str, seed: int) -> None:
    node = workflow[node_id]
    node["inputs"]["seed"] = seed
    # Defeat ComfyUI's auto-randomize on subsequent submissions.
    node["inputs"]["control_after_generate"] = "fixed"


def set_save_prefix(workflow: dict[str, Any], node_id: str, prefix: str) -> None:
    workflow[node_id]["inputs"]["filename_prefix"] = prefix


def set_load_image(workflow: dict[str, Any], node_id: str, server_path: str) -> None:
    workflow[node_id]["inputs"]["image"] = server_path


# --- High-level driver -----------------------------------------------------


INTERIOR_DEFAULT_T5 = (
    "top-down overhead orthographic view of an empty grimdark sci-fi interior room, "
    "warhammer 40000 aesthetic, "
    "camera looking straight down at 90 degrees, pure orthographic projection, "
    "image fills the frame edge-to-edge with no border, "
    "corroded metal deck plating floor with seam lines and diamond plate patches, "
    "thick bulkhead walls around the perimeter with dark gunmetal armor plating, "
    "rivets and weld seams, structural ribs along the walls, "
    "selective dramatic lighting from overhead amber lumen strips, heavy shadows in corners, "
    "muted color palette with teal and amber accent lighting, oil painting style, "
    "tabletop RPG battle map, highly detailed floor and wall textures, "
    "completely empty room with no furniture, no props, no objects, no tables, no chairs, "
    "no characters or people, no decorations on the floor"
)
INTERIOR_DEFAULT_CLIP_L = (
    "grimdark sci-fi, top-down battle map, empty room, bare floor, bulkhead walls, tabletop rpg"
)

# Universal negative addendum applied to every interior render. Targets
# the three failure modes observed in the first round of smoketests:
#   (1) the rendered metal frame/bezel that wraps every interior render
#       and destroys tileability;
#   (2) isometric drift — visible vertical wall faces and ceiling
#       structures bleeding into the top-down render;
#   (3) furniture leak — Flux rendering objects named in the positive
#       prompt even when negated ("racks bare of weapons" still produces
#       racks).
# Concatenated onto the workflow's static neg.t5xxl / neg.clip_l before
# submission. See run_interior().
INTERIOR_NEG_ADDENDUM_T5 = (
    "frame, bezel, border, decorative border, vignette, dark vignette edges, "
    "picture frame, image border, walls forming a border around the image, "
    "thick metal trim around image edges, dark edge falloff, "
    "vertical wall faces visible, ceiling structures visible, "
    "ceiling beams, exposed rafters, side perspective, three-quarter view, "
    "weapon racks, banners, vehicles, bunks, crates, barrels, hanging chains, "
    "hanging lights as objects, pendants as objects"
)
INTERIOR_NEG_ADDENDUM_CLIP_L = (
    "frame, border, vignette, side view, vertical walls, ceiling beams"
)

# Per-archetype prompt overrides for typical Solenne campaign locations.
# Each entry maps to a t5xxl string. The clip_l is synthesized via
# `_clip_l_for_style()` from a small style-specific tag prepended to a
# common base. The negative prompt and the empty-room invariant are
# unchanged across styles — every archetype produces a BARE map without
# props, suitable for stamp overlay.
INTERIOR_STYLES: dict[str, str] = {
    "hab": (
        "top-down overhead orthographic view of an empty hive-world hab apartment interior, "
        "warhammer 40000 aesthetic, "
        "stained ferrocrete floor with cracks and oil stains and grime patches, "
        "low cinderblock and rebar walls with peeling paint and water damage, "
        "exposed conduit and pipework along the walls, "
        "single bare lumen panel on the ceiling casting harsh cold light, "
        "muted brown and gray palette with a single sickly yellow accent, oil painting style, "
        "tabletop RPG battle map, highly detailed cracked floor and water-stained wall textures, "
        "completely empty room with no furniture, no props, no objects, no characters"
    ),
    "tunnel": (
        "top-down overhead orthographic view of an empty narrow underground maintenance tunnel, "
        "warhammer 40000 aesthetic, grimy hive sub-level, "
        "corrugated steel floor grating with seam lines and rust patches, "
        "thick concrete and steel walls with bundles of cable and pipework along both sides, "
        "occasional emergency lumen strip glowing red, deep darkness between lights, "
        "muted gray and rust palette with single red accent, oil painting style, "
        "tabletop RPG battle map, highly detailed grating floor and cabled wall textures, "
        "completely empty corridor with no furniture, no props, no characters"
    ),
    "industrial": (
        "top-down overhead orthographic view of an empty grimdark sci-fi industrial processing bay, "
        "warhammer 40000 aesthetic, ore processor facility interior, "
        "heavy plate steel floor with hazard stripes and grime stains and oil splatter, "
        "thick reinforced bulkhead walls with massive structural beams and pressure conduits, "
        "overhead crane rails visible at the ceiling, deep shadows between work zones, "
        "selective amber industrial lighting, muted gray and orange palette, oil painting style, "
        "tabletop RPG battle map, highly detailed floor and wall textures, "
        "completely empty bay with no machinery, no props, no objects, no characters"
    ),
    "chapel": (
        "top-down overhead orthographic view of an empty Imperial chapel interior, "
        "warhammer 40000 aesthetic, hive ministorum chapel, "
        "camera looking straight down at 90 degrees, pure top-down floorplan view, "
        "image fills the frame edge-to-edge with no border, no ceiling visible, no side walls visible, "
        "polished stone floor with mosaic Aquila pattern, candle wax and grime accumulated at edges, "
        "thin stone wall outlines forming the room perimeter, "
        "colored light pools on the floor from stained-glass slit windows, votive candles around the perimeter, "
        "muted earth-tone palette with golden accent, oil painting style, "
        "tabletop RPG battle map, highly detailed mosaic floor texture, "
        "completely empty nave with no pews, no furniture, no columns, no characters"
    ),
    "bar": (
        "top-down overhead orthographic view of an empty grimy underground bar interior, "
        "warhammer 40000 aesthetic, sub-level hive watering hole, "
        "camera looking straight down at 90 degrees, image fills the frame edge-to-edge, "
        "scuffed wood plank floor with stains and burn marks and old blood, "
        "low brick walls with peeling posters at the perimeter, "
        "amber pools of lumen light cast onto the floor, deep shadows in corners, "
        "muted brown and amber palette, oil painting style, "
        "tabletop RPG battle map, highly detailed floor and wall textures, "
        "completely empty room with no tables, no chairs, no bar counter, no props, no hanging lights as objects, no characters"
    ),
    "garrison": (
        "top-down overhead orthographic view of an empty Imperial Guard garrison barracks interior, "
        "warhammer 40000 aesthetic, regimental quarters, "
        "camera looking straight down at 90 degrees, image fills the frame edge-to-edge, "
        "scuffed concrete floor with painted hazard markings and dirt drag patterns, "
        "spartan reinforced concrete walls with bolt fixtures and faded paint, "
        "harsh overhead fluorescent strip lighting, deep shadow gaps between fixtures, "
        "muted gray and military-green palette, oil painting style, "
        "tabletop RPG battle map, highly detailed floor and wall textures, "
        "completely empty barracks, no bunks, no furniture, no equipment, no racks, no banners, no vehicles, no characters"
    ),
    "lair": (
        "top-down overhead orthographic view of an empty biomorphic genestealer cult lair chamber, "
        "warhammer 40000 aesthetic, alien xenos brood-nest interior, "
        "irregular organic floor surface with chitinous ridges and dried mucous patches and bone fragments, "
        "fleshy biological wall growths with pulsing veins and cartilaginous formations, "
        "phosphorescent bioluminescent patches casting sickly green-yellow light, "
        "deep wet shadows in alcove cavities, "
        "muted purple and bile-yellow palette, oil painting style, horror atmosphere, "
        "tabletop RPG battle map, highly detailed organic floor and biological wall textures, "
        "completely empty chamber with no creatures, no eggs, no characters"
    ),
    "medicae": (
        "top-down overhead orthographic view of an empty Imperial medicae examination room interior, "
        "warhammer 40000 aesthetic, sterile medical bay, "
        "polished white ceramic tile floor with grout lines and faint blood stains long-scrubbed, "
        "smooth pale-green walls with medicae symbols and cabinetry outlines, "
        "harsh white examination lights overhead with surgical brightness, "
        "muted white and pale green palette with cold blue accent, oil painting style, "
        "tabletop RPG battle map, highly detailed tile floor and wall textures, "
        "completely empty room with no examination tables, no equipment, no characters"
    ),
    "archive": (
        "top-down overhead orthographic view of an empty Munitorum records archive interior, "
        "warhammer 40000 aesthetic, Imperial document repository, "
        "dust-covered wooden plank floor with dropped paper fragments and ink stains, "
        "tall stone walls lined with empty record-shelf alcoves and the Aquila in relief, "
        "single dim brass lumen fixtures casting yellow warmth between deep shadows, "
        "muted brown and parchment palette with brass accent, oil painting style, "
        "tabletop RPG battle map, highly detailed floor and shelving wall textures, "
        "completely empty archive with no books, no shelves filled, no characters"
    ),
    "mechanicus": (
        "top-down overhead orthographic view of an empty Adeptus Mechanicus shrine interior, "
        "warhammer 40000 aesthetic, sanctified machine-cult chamber, "
        "polished black metal floor with engraved cog-iconography and mechanicus runes, "
        "tall walls of brass piping and exposed cogitator banks with Aquila Mechanicus reliefs, "
        "ritual red lumen pendants casting blood-red light, deep shadow between fixtures, "
        "muted black and blood-red palette with brass accent, oil painting style, "
        "tabletop RPG battle map, highly detailed floor and machine-wall textures, "
        "completely empty shrine with no machinery, no servitors, no characters"
    ),
    # ── Wide-scale archetypes (above interior scale) ─────────────────
    # These render city/region/planet/system views as base maps. Stamps
    # placed on top represent locations, factions, or fleets at scale.
    "district": (
        "top-down overhead orthographic satellite view of a grimdark hive city district, "
        "warhammer 40000 aesthetic, "
        "dense ferrocrete hab-spires and manufactorum blocks arranged in irregular grids, "
        "narrow alleyways and processional avenues between blocks, "
        "rooftop structures including chimneys and antenna arrays and crane gantries, "
        "smog-filled air with patches of orange-amber industrial light leaking up from streets, "
        "muted brown and gray palette with warm sodium-light accents, oil painting style, "
        "tabletop RPG strategic map, highly detailed rooftop textures, "
        "completely empty district with no characters, no vehicles"
    ),
    "region": (
        "high-altitude aerial reconnaissance map of a hive world wasteland region, "
        "warhammer 40000 aesthetic, "
        "two or three large hive cities visible as massive dense gray fortress complexes, "
        "each hive a clear central cluster with concentric defensive walls and spire silhouettes, "
        "connected by long imperial maglev rail lines drawn as dark thin straight lines, "
        "open toxic wasteland between the hives — ash flats, pollution lakes with sickly green water, "
        "scattered imperial bunker outposts and small mining operations as dark dots, "
        "muted earth-tone palette with sickly green and toxic yellow accents, "
        "imperial military cartography style with subtle hand-drawn shading, parchment overlay tone, "
        "tabletop RPG strategic regional war map, highly detailed terrain features, "
        "no characters, no vehicles, no aircraft visible"
    ),
    "planet": (
        "orbital satellite reconnaissance image of a hive world from low orbit, "
        "warhammer 40000 aesthetic, "
        "the curved horizon of the planet visible at the frame edges, "
        "continental landmasses crusted with sprawling gray-brown hive city megastructures, "
        "huge industrial scarring and slag heaps visible from orbit, "
        "polluted oceans with toxic algal blooms tinged sickly green, "
        "polar ice caps at the top and bottom of the visible disc, "
        "atmospheric haze layer of orbital pollution clearly visible at the limb, "
        "imperial red administratum markings overlaid on key urban centres, "
        "muted brown and gray-green palette with imperial red highlights, "
        "tabletop RPG strategic planetary map, highly detailed continental terrain, "
        "no characters, no spacecraft, no fleets visible"
    ),
    "system": (
        "top-down stylized cartographic chart of a solar system, "
        "warhammer 40000 aesthetic, dark void background with star field, "
        "central yellow-white star, multiple planets at varying orbital distances each shown as a small disc, "
        "thin orbital ring lines connecting planets to the star, "
        "asteroid belts as scattered specks, gas giant rings, "
        "Imperial Navy patrol routes as dashed amber lines, "
        "imperial gothic typography labels for each body, parchment overlay borders, "
        "muted cosmic palette with imperial gold accents, hand-illuminated chart style, "
        "tabletop RPG strategic system chart, no ships, no characters"
    ),
}

# Floor-only prompt fragments per archetype. The base interior render
# in `--floor-only` mode SHOULD NOT include walls — they leak as 3D
# perimeter bezels even with strong negatives because Flux interprets
# "bulkhead walls around the perimeter" as a rendered object, not a
# negative-space. The stackable design already has a separate walls
# layer (`run_spacecraft --walls-only` or hand-drawn), so the base map
# is canonically the floor texture filling the entire frame.
#
# Each value here is a TEXTURE fragment describing only the floor
# surface. The driver wraps it in a fixed top-down envelope and a
# strong "no walls" negative when rendering.
INTERIOR_STYLE_FLOOR_TEXTURES: dict[str, str] = {
    "hab": (
        "heavily weathered ferrocrete slab floor, high contrast warm rust-brown "
        "and gray-brown texture, deep dark cracks running across the slabs, "
        "thick oil stain patches with sharp edges, scattered water damage rings, "
        "exposed rebar showing through chipped patches, sickly yellow stained "
        "lumen pool, painterly grimdark hive sub-level floor texture, "
        "distinct stained concrete look"
    ),
    "tunnel": (
        "corrugated steel floor grating with bolt seams and rust patches, "
        "scattered cable bundles running along the floor, "
        "occasional emergency red lumen pool, deep ambient darkness"
    ),
    "industrial": (
        "heavy plate steel floor with grime stains and oil splatter, "
        "subtle weld seams between plates, ambient orange-amber light"
    ),
    "chapel": (
        "polished stone floor with intricate Aquila mosaic centered, "
        "scattered candle wax drips and dust patches across the slabs, "
        "diffuse soft golden ambient illumination, no decorative borders"
    ),
    "bar": (
        "scuffed wood plank flooring with deep stains, burn marks, old blood, "
        "dim warm amber light pools, scattered cigarette burns"
    ),
    "garrison": (
        "scuffed concrete floor with painted hazard markings and dirt drag patterns, "
        "regimental boot scuffs, harsh white overhead light pools"
    ),
    "lair": (
        "irregular organic floor surface with chitinous ridges, dried mucous patches, "
        "bone fragments embedded in the substrate, phosphorescent green glow patches"
    ),
    "medicae": (
        "polished white ceramic tile floor with grout lines, "
        "faint blood stains long-scrubbed, harsh sterile white overhead light"
    ),
    "archive": (
        "dust-covered wooden plank flooring, dropped paper fragments, "
        "ink stains, dim warm brass lumen pools"
    ),
    "mechanicus": (
        "polished black metal floor with engraved cog-iconography and Mechanicus runes, "
        "diffuse ambient blood-red illumination across the floor, no light fixtures, no studs, "
        "deep shadows in the darker areas"
    ),
    # Ship-deck floor textures. Each pairs with a `ship-*` floorplan
    # preset so multi-deck stacks share footprint but render distinct
    # interior surfaces.
    "ship-bridge": (
        "polished dark steel deck plating with brass inlay accents, "
        "subtle indicator lighting reflecting off the surface, "
        "command-deck flooring, clean and well-maintained, "
        "muted blue-grey palette with warm brass highlights"
    ),
    "ship-engineering": (
        "ferro-grate engineering deck flooring over reactor coils, "
        "warm orange-red light glowing up through the grate slits, "
        "scuffed industrial steel surface, oil stains and burn marks, "
        "muted dark steel palette with hot orange undercast"
    ),
    "ship-barracks": (
        "scuffed steel decking, regimental boot scuffs, painted hazard markings, "
        "harsh white overhead light pools, "
        "utilitarian military barracks flooring, "
        "muted gray palette with cold white highlights"
    ),
    "ship-cargo": (
        "heavy plate steel cargo deck, painted yellow loading bay markings, "
        "scuffed by container drag, oil stains, hazard stripes near openings, "
        "muted gray-brown palette with amber industrial accents"
    ),
}

# Wrap fragment in this envelope to force a pure-floor render.
INTERIOR_FLOOR_PROMPT_TEMPLATE = (
    "top-down overhead orthographic view of a bare floor surface filling the entire frame, "
    "warhammer 40000 aesthetic, "
    "camera looking straight down at 90 degrees, pure orthographic projection, "
    "image fills the frame edge-to-edge with no border and no walls, "
    "{texture}, "
    "oil painting style, tabletop RPG battle map floor texture, "
    "highly detailed seamless floor surface, "
    "no walls, no perimeter walls, no bulkheads, no doorways, "
    "no furniture, no props, no objects, no characters, no people"
)

# Negative addendum specifically for floor-only renders. Layers on top of
# INTERIOR_NEG_ADDENDUM_T5 to actively suppress walls.
INTERIOR_FLOOR_ONLY_NEG_T5 = (
    "walls, bulkheads, perimeter walls, room walls, wall faces, vertical surfaces, "
    "doorways, archways, columns, pillars, room boundaries, edge bezel"
)
INTERIOR_FLOOR_ONLY_NEG_CLIP_L = (
    "walls, bulkheads, perimeter walls, doorways, columns"
)


INTERIOR_STYLE_TAGS: dict[str, str] = {
    "hab": "hab apartment, ferrocrete floor, hive sub-level",
    "tunnel": "maintenance tunnel, narrow corridor, cabled walls",
    "industrial": "industrial bay, ore processor, hazard stripes",
    "chapel": "Imperial chapel, mosaic floor, stone walls",
    "bar": "underground bar, wood floor, dim hanging lights",
    "garrison": "Imperial Guard barracks, military",
    "lair": "biomorphic xenos lair, organic walls, alien horror",
    "medicae": "medicae bay, white tile, sterile examination",
    "archive": "Munitorum archive, parchment, brass lumen",
    "mechanicus": "Mechanicus shrine, brass piping, red lumen",
    "district": "hive city district, top-down satellite, manufactorum",
    "region": "hive world region, aerial wastes, multiple hives",
    "planet": "hive world orbital, planetary continents",
    "system": "system chart, orbital diagram, imperial cartography",
}


def _clip_l_for_style(style: str) -> str:
    return f"grimdark sci-fi, top-down battle map, empty room, {INTERIOR_STYLE_TAGS[style]}, tabletop rpg"


def _extend_negative(workflow: dict[str, Any], *, t5_addendum: str, clip_l_addendum: str) -> None:
    """Concatenate addenda onto the workflow's existing neg.t5xxl / neg.clip_l.

    The static negative baked into BattlemapInteriorV1.json on the server
    targets generic anti-style (anime, cartoon, photo). The addendum
    layers domain-specific negatives on top: anti-bezel, anti-isometric,
    anti-furniture-leak. Done client-side so the server-side workflow
    file stays unchanged (it is authoritative; we don't push edits).
    """
    node = workflow.get("neg")
    if not node or node.get("class_type") != "CLIPTextEncodeFlux":
        return
    inputs = node["inputs"]
    base_t5 = inputs.get("t5xxl", "")
    base_clip = inputs.get("clip_l", "")
    inputs["t5xxl"] = (base_t5 + ", " + t5_addendum) if base_t5 else t5_addendum
    inputs["clip_l"] = (base_clip + ", " + clip_l_addendum) if base_clip else clip_l_addendum


def run_interior(
    server: str,
    *,
    t5xxl: str,
    clip_l: str,
    width: int,
    height: int,
    seed: int,
    prefix: str,
    floor_only: bool = False,
) -> Path:
    wf = load_template("BattlemapInteriorV1")
    set_prompt(wf, "pos", t5xxl=t5xxl, clip_l=clip_l)
    neg_t5 = INTERIOR_NEG_ADDENDUM_T5
    neg_clip = INTERIOR_NEG_ADDENDUM_CLIP_L
    if floor_only:
        neg_t5 = neg_t5 + ", " + INTERIOR_FLOOR_ONLY_NEG_T5
        neg_clip = neg_clip + ", " + INTERIOR_FLOOR_ONLY_NEG_CLIP_L
    _extend_negative(wf, t5_addendum=neg_t5, clip_l_addendum=neg_clip)
    set_dimensions(wf, "latent", width=width, height=height)
    set_seed(wf, "sampler", seed)
    set_save_prefix(wf, "save", prefix)

    client_id = uuid.uuid4().hex
    print(f"[interior] submitting prompt prefix={prefix} {width}x{height} seed={seed}", file=sys.stderr)
    pid = submit_prompt(server, wf, client_id)
    print(f"[interior] prompt_id={pid}", file=sys.stderr)
    record = poll_history(server, pid)

    saved = _saved_images_from_history(record)
    if not saved:
        raise RuntimeError(f"no SaveImage outputs in history: {json.dumps(record.get('outputs'), indent=2)[:600]}")
    return _download_first(server, saved, prefix)


# Per-region color codes (RGB) baked into BattlemapSpacecraft.json's
# ImageColorToMask nodes. ARCHITECTURE-ONLY by design — the saved
# workflow includes chair/locker/console regions but those are
# *furniture* and belong on the stamp layer, not in the rendered base
# map. The driver auto-overrides chair/locker/console prompts to
# "empty floor" so layouts which accidentally paint those colors don't
# leak furniture into the architectural map. See SPACECRAFT_NEUTRALIZED.
SPACECRAFT_REGION_RGB: dict[str, tuple[int, int, int]] = {
    "wall": (0x30, 0x30, 0x30),       # 3158064  — bulkhead walls
    "floor": (0x80, 0x80, 0x80),      # 8421504  — deck plating
    "ramp": (0xA0, 0xA0, 0xA0),       # 10526880 — loading ramp
    "windscreen": (0x1A, 0x27, 0x50), # 1716304  — cockpit viewport
    "lighting": (0xD4, 0xB2, 0x60),   # 13934624 — lumen strip
}

# Roles that are architecturally meaningful (wall/floor/ramp/lighting/
# viewport openings) and which the driver actively conditions on.
SPACECRAFT_ARCHITECTURAL_ROLES = set(SPACECRAFT_REGION_RGB)

# Roles preserved for backward-compat with the saved workflow file but
# which the driver actively NEUTRALIZES — overriding their prompts to
# "empty deck plating" so accidental paint of these colors in a layout
# doesn't render furniture into the architectural base map. Furniture
# belongs on the stamp/tile layer in Foundry, not on the base.
SPACECRAFT_NEUTRALIZED: dict[str, tuple[int, int, int]] = {
    "chair": (0x8B, 0x5E, 0x2B),      # 9132587  — was pilot chair
    "locker": (0x4A, 0x6F, 0x40),     # 4876928  — was storage locker
    "console": (0x2A, 0x42, 0x50),    # 2771536  — was instrument console
}
NEUTRAL_PROMPT_T5 = "corroded metal deck plating, empty floor, seam lines, rust patches"
NEUTRAL_PROMPT_CLIP = "deck plating, empty floor"

# Mapping role -> CLIPTextEncodeFlux node id in BattlemapSpacecraft.json.
# Includes both architectural and neutralized roles so the driver can
# rewrite all 8 region prompts deterministically on every render.
SPACECRAFT_REGION_NODE_FOR: dict[str, str] = {
    "wall": "11",
    "floor": "14",
    "ramp": "17",
    "windscreen": "20",
    "chair": "23",      # neutralized
    "locker": "26",     # neutralized
    "console": "29",    # neutralized
    "lighting": "32",
}


def run_spacecraft(
    server: str,
    *,
    layout_path: Path,
    seed: int,
    prefix: str,
    keep_only_role: str | None = None,
    prompt_overrides: dict[str, str] | None = None,
    render_furniture: tuple[str, ...] = (),
) -> Path:
    """Run the regional-conditioning Spacecraft workflow.

    `keep_only_role`: if provided (e.g. "wall"), the workflow runs
    normally to produce a full render, then post-processes by using
    the layout image as an alpha mask — pixels whose layout-image
    color is close to the requested role's color stay opaque;
    everything else becomes transparent. This is more reliable than
    asking Flux to render a chromakey color (Flux mutes saturated
    out-of-gamut prompts to gray); the layout itself is the
    deterministic source of truth for "where is the wall vs. the
    floor."
    """
    wf = load_template("BattlemapSpacecraft")
    server_path = upload_input_image(server, layout_path)
    set_load_image(wf, "load", server_path)
    set_seed(wf, "sampler", seed)
    set_save_prefix(wf, "save", prefix)

    # Architecture-by-default: every neutralized (furniture) role gets its
    # prompt blanked unless the caller explicitly opts in via
    # render_furniture. Furniture belongs on the stamp/tile layer; we
    # don't want the diffusion model leaking chairs/lockers/consoles
    # into the base map.
    for role in SPACECRAFT_NEUTRALIZED:
        if role in render_furniture:
            continue
        node_id = SPACECRAFT_REGION_NODE_FOR[role]
        set_prompt(wf, node_id, t5xxl=NEUTRAL_PROMPT_T5, clip_l=NEUTRAL_PROMPT_CLIP)

    if prompt_overrides:
        for role, t5 in prompt_overrides.items():
            node_id = SPACECRAFT_REGION_NODE_FOR[role]
            set_prompt(wf, node_id, t5xxl=t5)
            print(f"[spacecraft] override role={role}: {t5[:60]!r}", file=sys.stderr)

    client_id = uuid.uuid4().hex
    print(f"[spacecraft] uploaded layout={server_path}", file=sys.stderr)
    mode = f"keep_only={keep_only_role}" if keep_only_role else "full"
    print(f"[spacecraft] submitting prompt prefix={prefix} seed={seed} mode={mode}", file=sys.stderr)
    pid = submit_prompt(server, wf, client_id)
    print(f"[spacecraft] prompt_id={pid}", file=sys.stderr)
    record = poll_history(server, pid)

    saved = _saved_images_from_history(record)
    if not saved:
        raise RuntimeError(f"no SaveImage outputs in history: {json.dumps(record.get('outputs'), indent=2)[:600]}")
    base_path = _download_first(server, saved, prefix)
    if keep_only_role is not None:
        if keep_only_role not in SPACECRAFT_REGION_RGB:
            raise ValueError(
                f"unknown region role: {keep_only_role!r}; known: {list(SPACECRAFT_REGION_RGB)}"
            )
        base_path = _mask_render_by_layout(
            base_path,
            layout_path=layout_path,
            target_rgb=SPACECRAFT_REGION_RGB[keep_only_role],
        )
    return base_path


def _compose_layers(base: Path, overlay: Path, out: Path) -> None:
    """Alpha-composite `overlay` onto `base` and save to `out`.

    The overlay must be RGBA (transparent background). The base may be
    RGB or RGBA. If sizes differ, the overlay is resampled to the base's
    dimensions with NEAREST (preserves pixel-perfect alpha edges).
    """
    from PIL import Image

    bg = Image.open(base).convert("RGBA")
    ov = Image.open(overlay).convert("RGBA")
    if ov.size != bg.size:
        ov = ov.resize(bg.size, Image.NEAREST)
    composed = Image.alpha_composite(bg, ov)
    composed.save(out)


def _make_rectangular_room(
    output: Path,
    *,
    width: int,
    height: int,
    wall_thickness: int,
    ramp_side: str | None,
    light_count: int,
) -> None:
    """Paint a canonical-color rectangular-room layout PNG.

    Layout:
      * Black background everywhere outside the room footprint.
      * Wall color (#303030) around the perimeter at `wall_thickness`.
      * Floor color (#808080) filling the interior.
      * Optional `ramp_side` extends a 1/3-width ramp out from that wall.
      * Optional `light_count` evenly-spaced amber fixtures inset from
        each side of the perimeter.

    Output is ready to feed directly to `spacecraft` mode without
    needing a quantize pass — colors are painted with hard edges at
    exact canonical values.
    """
    import numpy as np
    from PIL import Image

    arr = np.zeros((height, width, 3), dtype=np.uint8)
    wall = SPACECRAFT_REGION_RGB["wall"]
    floor = SPACECRAFT_REGION_RGB["floor"]
    ramp = SPACECRAFT_REGION_RGB["ramp"]
    light = SPACECRAFT_REGION_RGB["lighting"]

    # Frame everything in walls, then overpaint the interior with floor.
    arr[:, :] = wall
    arr[wall_thickness:height - wall_thickness, wall_thickness:width - wall_thickness] = floor
    # Carve the area outside the room (i.e. before walls) back to black.
    # In this rectangular form, the room fills the whole canvas — no
    # carve-out needed unless `ramp_side` is set, in which case we extend
    # outside on that side and want the rest still black on the same axis.
    # For simplicity we keep the layout to-the-edges; the BattlemapSpacecraft
    # workflow expects black around the spacecraft outline only when there's
    # a ramp protrusion. Adjust the framing if that matters for your prompt.

    if ramp_side is not None:
        ramp_len = max(wall_thickness * 4, min(width, height) // 6)
        if ramp_side in ("north", "south"):
            ramp_w = width // 3
            x0 = (width - ramp_w) // 2
            x1 = x0 + ramp_w
            if ramp_side == "north":
                # Extend the ramp into the wall and through (so it reads as a
                # ramp connecting through the bulkhead, not a notch).
                arr[0:ramp_len, x0:x1] = ramp
            else:
                arr[height - ramp_len:height, x0:x1] = ramp
        else:
            ramp_h = height // 3
            y0 = (height - ramp_h) // 2
            y1 = y0 + ramp_h
            if ramp_side == "west":
                arr[y0:y1, 0:ramp_len] = ramp
            else:
                arr[y0:y1, width - ramp_len:width] = ramp

    # Lighting fixtures: small disks evenly spaced inside the wall band.
    if light_count > 0:
        radius = max(8, wall_thickness // 2)
        cx_inset = wall_thickness // 2
        per_side = max(1, light_count // 4)
        positions: list[tuple[int, int]] = []
        # Top + bottom rows
        for i in range(per_side):
            x = int(width * (i + 1) / (per_side + 1))
            positions.append((x, cx_inset))
            positions.append((x, height - cx_inset))
        # Left + right columns
        for j in range(per_side):
            y = int(height * (j + 1) / (per_side + 1))
            positions.append((cx_inset, y))
            positions.append((width - cx_inset, y))
        ys, xs = np.ogrid[0:height, 0:width]
        for cx, cy in positions:
            mask = (xs - cx) ** 2 + (ys - cy) ** 2 <= radius * radius
            arr[mask] = light

    Image.fromarray(arr, mode="RGB").save(output)


def _make_corridor(
    output: Path,
    *,
    length: int,
    width: int,
    wall_thickness: int,
    orientation: str,
    light_count: int,
) -> None:
    """Paint a canonical-color corridor layout PNG.

    A corridor is a long rectangular floor with walls on the two long
    sides only — the short ends extend off-canvas (or open to other
    rooms in larger composites). Lights are placed evenly along both
    long walls, alternating between the inside edges of each wall.
    """
    import numpy as np
    from PIL import Image

    if orientation == "horizontal":
        w, h = length, width
    else:
        w, h = width, length

    arr = np.zeros((h, w, 3), dtype=np.uint8)
    wall = SPACECRAFT_REGION_RGB["wall"]
    floor = SPACECRAFT_REGION_RGB["floor"]
    light = SPACECRAFT_REGION_RGB["lighting"]

    if orientation == "horizontal":
        arr[0:wall_thickness, :] = wall
        arr[h - wall_thickness:h, :] = wall
        arr[wall_thickness:h - wall_thickness, :] = floor
    else:
        arr[:, 0:wall_thickness] = wall
        arr[:, w - wall_thickness:w] = wall
        arr[:, wall_thickness:w - wall_thickness] = floor

    if light_count > 0:
        radius = max(8, wall_thickness // 2)
        ys, xs = np.ogrid[0:h, 0:w]
        if orientation == "horizontal":
            for i in range(light_count):
                cx = int(w * (i + 1) / (light_count + 1))
                cy = wall_thickness // 2 if i % 2 == 0 else h - wall_thickness // 2
                mask = (xs - cx) ** 2 + (ys - cy) ** 2 <= radius * radius
                arr[mask] = light
        else:
            for i in range(light_count):
                cy = int(h * (i + 1) / (light_count + 1))
                cx = wall_thickness // 2 if i % 2 == 0 else w - wall_thickness // 2
                mask = (xs - cx) ** 2 + (ys - cy) ** 2 <= radius * radius
                arr[mask] = light

    Image.fromarray(arr, mode="RGB").save(output)


# --- Multi-room floor-plan layouts -----------------------------------------
#
# A floor plan is a composition of room rectangles + corridor rectangles +
# doorway cuts on a single canvas, all painted in canonical region colors so
# the spacecraft workflow can condition each region with a different prompt.
#
# Spec format (a plain dict, since a YAML/JSON callsite is most convenient):
#
#     {
#       "canvas": (width, height),
#       "wall_thickness": 32,
#       "rooms": [(x, y, w, h), ...],          # interior spaces with walls + lights
#       "corridors": [(x, y, w, h), ...],      # interior spaces with walls + lights, fewer
#       "doors": [(x, y, w, h), ...],          # rectangles to overpaint with floor
#       "light_count_per_room": 4,
#       "light_count_per_corridor": 4,
#     }
#
# Rooms and corridors are painted identically here (wall band + floor fill) —
# the distinction matters only for light density and naming. The order of
# operations: walls first, then floor inside walls, then doors carve through
# the walls.


def _paint_lights_around_perimeter(
    arr,  # type: ignore[no-untyped-def]
    rect: tuple[int, int, int, int],
    *,
    wall_thickness: int,
    light_count: int,
    light_rgb: tuple[int, int, int],
) -> None:
    """Place `light_count` light disks evenly around the perimeter of `rect`."""
    import numpy as np

    if light_count <= 0:
        return
    x, y, w, h = rect
    cx_inset = max(8, wall_thickness // 2)
    radius = max(8, wall_thickness // 2)
    per_side = max(1, light_count // 4)
    positions: list[tuple[int, int]] = []
    for i in range(per_side):
        px = x + int(w * (i + 1) / (per_side + 1))
        positions.append((px, y + cx_inset))
        positions.append((px, y + h - cx_inset))
    for j in range(per_side):
        py = y + int(h * (j + 1) / (per_side + 1))
        positions.append((x + cx_inset, py))
        positions.append((x + w - cx_inset, py))
    H, W = arr.shape[:2]
    ys, xs = np.ogrid[0:H, 0:W]
    for cx, cy in positions:
        mask = (xs - cx) ** 2 + (ys - cy) ** 2 <= radius * radius
        arr[mask] = light_rgb


def _make_floorplan(output: Path, *, spec: dict) -> None:
    """Paint a multi-room/corridor canonical-color layout PNG.

    Spec keys (all optional except `canvas` and `wall_thickness`):
      canvas: (width, height)
      wall_thickness: int
      rooms: [(x, y, w, h), ...]              walled rooms (lit)
      corridors: [(x, y, w, h), ...]          walled corridors (lit, fewer)
      extra_walls: [(x, y, w, h), ...]        walled regions WITHOUT lights
                                              (use for raised consoles, sub-structures)
      doors: [(x, y, w, h), ...]              floor cuts through walls
      windscreen: {side, thickness, frac}     paints a windscreen band along
                                              the named hull edge ('north',
                                              'south', 'east', 'west').
                                              `frac` is band length as a
                                              fraction of the hull's edge.
      ramp: {side, x_frac, width_frac}        cuts a ramp opening through the
                                              hull's named edge, replacing
                                              wall+floor with ramp color from
                                              the hull edge to the canvas edge.
      light_count_per_room: int
      light_count_per_corridor: int

    Output is ready to feed directly to the spacecraft workflow as a layout PNG.
    """
    import numpy as np
    from PIL import Image

    canvas_w, canvas_h = spec["canvas"]
    wall_thickness = int(spec.get("wall_thickness", 32))

    arr = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)  # outside = black
    wall = SPACECRAFT_REGION_RGB["wall"]
    floor = SPACECRAFT_REGION_RGB["floor"]
    light = SPACECRAFT_REGION_RGB["lighting"]
    ramp_rgb = SPACECRAFT_REGION_RGB["ramp"]
    windscreen_rgb = SPACECRAFT_REGION_RGB["windscreen"]

    def paint_box(x: int, y: int, w: int, h: int) -> None:
        # Wall band first, then carve interior to floor.
        arr[y : y + h, x : x + w] = wall
        arr[
            y + wall_thickness : y + h - wall_thickness,
            x + wall_thickness : x + w - wall_thickness,
        ] = floor

    for rect in spec.get("rooms", []):
        paint_box(*rect)
    for rect in spec.get("corridors", []):
        paint_box(*rect)
    for rect in spec.get("extra_walls", []):
        paint_box(*rect)

    # Doors: overpaint walls with floor in the door rectangle. This naturally
    # connects adjacent rooms / room-to-corridor with a clean opening.
    for x, y, w, h in spec.get("doors", []):
        arr[y : y + h, x : x + w] = floor

    # Windscreen: paint along the named hull edge (assumes the first room is
    # the outer hull). The band is centered along the edge with `frac` length.
    ws = spec.get("windscreen")
    if ws and spec.get("rooms"):
        hull = spec["rooms"][0]
        hx, hy, hw, hh = hull
        side = ws["side"]
        ws_thick = int(ws.get("thickness", wall_thickness))
        ws_frac = float(ws.get("frac", 0.5))
        if side in ("north", "south"):
            band_w = int(hw * ws_frac)
            band_x0 = hx + (hw - band_w) // 2
            if side == "north":
                arr[hy : hy + ws_thick, band_x0 : band_x0 + band_w] = windscreen_rgb
            else:
                arr[hy + hh - ws_thick : hy + hh, band_x0 : band_x0 + band_w] = windscreen_rgb
        else:
            band_h = int(hh * ws_frac)
            band_y0 = hy + (hh - band_h) // 2
            if side == "west":
                arr[band_y0 : band_y0 + band_h, hx : hx + ws_thick] = windscreen_rgb
            else:
                arr[band_y0 : band_y0 + band_h, hx + hw - ws_thick : hx + hw] = windscreen_rgb

    # Ramp: cut a rectangular opening through the hull's named edge from the
    # hull boundary out to the canvas edge. Painted ramp color the whole way.
    rp = spec.get("ramp")
    if rp and spec.get("rooms"):
        hull = spec["rooms"][0]
        hx, hy, hw, hh = hull
        side = rp["side"]
        x_frac = float(rp.get("x_frac", 0.5))
        width_frac = float(rp.get("width_frac", 0.25))
        if side in ("north", "south"):
            ramp_w = int(hw * width_frac)
            cx = hx + int(hw * x_frac)
            ramp_x0 = max(hx, cx - ramp_w // 2)
            ramp_x1 = min(hx + hw, ramp_x0 + ramp_w)
            if side == "north":
                arr[0 : hy + wall_thickness, ramp_x0:ramp_x1] = ramp_rgb
            else:
                arr[hy + hh - wall_thickness : canvas_h, ramp_x0:ramp_x1] = ramp_rgb
        else:
            ramp_h = int(hh * width_frac)
            cy = hy + int(hh * x_frac)
            ramp_y0 = max(hy, cy - ramp_h // 2)
            ramp_y1 = min(hy + hh, ramp_y0 + ramp_h)
            if side == "west":
                arr[ramp_y0:ramp_y1, 0 : hx + wall_thickness] = ramp_rgb
            else:
                arr[ramp_y0:ramp_y1, hx + hw - wall_thickness : canvas_w] = ramp_rgb

    # Lights AFTER doorways/windscreen/ramp so they don't paint over openings.
    # Skip extra_walls — those are sub-structures, not separate rooms.
    n_room_lights = int(spec.get("light_count_per_room", 4))
    n_corr_lights = int(spec.get("light_count_per_corridor", 4))
    for rect in spec.get("rooms", []):
        _paint_lights_around_perimeter(
            arr, rect,
            wall_thickness=wall_thickness, light_count=n_room_lights, light_rgb=light,
        )
    for rect in spec.get("corridors", []):
        _paint_lights_around_perimeter(
            arr, rect,
            wall_thickness=wall_thickness, light_count=n_corr_lights, light_rgb=light,
        )

    Image.fromarray(arr, mode="RGB").save(output)


# Named presets — easy starting points without hand-spec'ing rectangles.
# Sizes target Foundry's default 100px grid: a 1024×768 plan is about a
# 10×8-square map, comfortable as a single-scene encounter battlemap.
def _preset_hab_2room(canvas_w: int = 1280, canvas_h: int = 640, wall: int = 32) -> dict:
    """Two square hab rooms side-by-side, one shared doorway."""
    door_w = 96
    room_w = (canvas_w - wall) // 2  # leave the shared interior wall
    rooms = [
        (0, 0, room_w + wall // 2, canvas_h),                                  # left
        (room_w - wall // 2, 0, canvas_w - (room_w - wall // 2), canvas_h),    # right
    ]
    door_y = (canvas_h - door_w) // 2
    door_x = room_w - wall // 2
    doors = [(door_x, door_y, wall, door_w)]
    return {
        "canvas": (canvas_w, canvas_h),
        "wall_thickness": wall,
        "rooms": rooms,
        "corridors": [],
        "doors": doors,
        "light_count_per_room": 4,
    }


def _preset_hab_3room_corridor(
    canvas_w: int = 1792, canvas_h: int = 1024, wall: int = 32
) -> dict:
    """Three rooms off a central horizontal corridor (T-shape).

    Layout (rooms 1–3 around a central corridor C):
        ┌─R1──┐    ┌──R2─┐
        │     │    │     │
        │     │    │     │
        └──┬──┘    └──┬──┘
        ───┴────CCCC───┴───
                  │
                ┌─┴───┐
                │  R3 │
                │     │
                └─────┘
    """
    corr_h = 224
    corr_y = (canvas_h - corr_h) // 2
    corridor = (0, corr_y, canvas_w, corr_h)

    room_h = corr_y  # rooms occupy everything above and below corridor
    r1_w = (canvas_w - wall * 3) // 3
    r1 = (0, 0, r1_w, room_h + wall)
    r2 = (canvas_w - r1_w, 0, r1_w, room_h + wall)
    # Room 3 below the corridor, centered
    r3_w = canvas_w // 2
    r3_x = (canvas_w - r3_w) // 2
    r3 = (r3_x, corr_y + corr_h - wall, r3_w, canvas_h - (corr_y + corr_h) + wall)

    door_w = 96
    doors = [
        # R1 → corridor (south wall of R1 / north wall of corridor)
        (r1[0] + (r1_w - door_w) // 2, corr_y, door_w, wall),
        # R2 → corridor
        (r2[0] + (r1_w - door_w) // 2, corr_y, door_w, wall),
        # Corridor → R3 (south wall of corridor / north wall of R3)
        (r3_x + (r3_w - door_w) // 2, corr_y + corr_h - wall, door_w, wall),
    ]
    return {
        "canvas": (canvas_w, canvas_h),
        "wall_thickness": wall,
        "rooms": [r1, r2, r3],
        "corridors": [corridor],
        "doors": doors,
        "light_count_per_room": 4,
        "light_count_per_corridor": 6,
    }


def _preset_tunnel_junction(
    canvas_w: int = 1536, canvas_h: int = 1536, wall: int = 32
) -> dict:
    """T-junction of three corridors meeting at a central hub.

        ┌──────CN──────┐
        │              │
        │     ┌──┐     │
        │     │  │     │
        ──CW──┤  ├──CE──
        │     │  │     │
        │     └──┘     │
        │              │
        │     CS not used here — T not X
        └──────────────┘
    """
    corr_w = 224
    cx = canvas_w // 2
    cy = canvas_h // 2
    # West corridor
    west = (0, cy - corr_w // 2, cx, corr_w)
    # East corridor
    east = (cx, cy - corr_w // 2, canvas_w - cx, corr_w)
    # North corridor
    north = (cx - corr_w // 2, 0, corr_w, cy)
    # Hub: small room at the junction
    hub_size = 320
    hub = (cx - hub_size // 2, cy - hub_size // 2, hub_size, hub_size)
    # Doorways from hub into each corridor
    door_w = 96
    doors = [
        # west wall of hub → east end of west corridor
        (hub[0], cy - door_w // 2, wall, door_w),
        # east wall of hub
        (hub[0] + hub_size - wall, cy - door_w // 2, wall, door_w),
        # north wall of hub
        (cx - door_w // 2, hub[1], door_w, wall),
    ]
    return {
        "canvas": (canvas_w, canvas_h),
        "wall_thickness": wall,
        "rooms": [hub],
        "corridors": [west, east, north],
        "doors": doors,
        "light_count_per_room": 4,
        "light_count_per_corridor": 6,
    }


def _preset_chapel_nave_with_apse(
    canvas_w: int = 1280, canvas_h: int = 1792, wall: int = 32
) -> dict:
    """Long chapel nave with a smaller apse at the north end.

       ┌──────A──────┐    apse (smaller, terminus)
       │             │
       │             │
       └──┐       ┌──┘
          │       │
       ┌──┘       └──┐
       │             │
       │      N      │    nave (long body of chapel)
       │             │
       │             │
       │             │
       └──────D──────┘    south doorway (entry)
    """
    apse_h = canvas_h // 4
    apse_w = canvas_w * 3 // 4
    apse_x = (canvas_w - apse_w) // 2
    apse = (apse_x, 0, apse_w, apse_h)

    nave_y = apse_h - wall  # share the wall band
    nave = (0, nave_y, canvas_w, canvas_h - nave_y)

    door_w = 128
    doors = [
        # apse → nave
        (apse_x + (apse_w - door_w) // 2, apse_h - wall, door_w, wall),
        # nave south entry (a cosmetic doorway out the bottom)
        ((canvas_w - door_w) // 2, canvas_h - wall, door_w, wall),
    ]
    return {
        "canvas": (canvas_w, canvas_h),
        "wall_thickness": wall,
        "rooms": [apse, nave],
        "corridors": [],
        "doors": doors,
        "light_count_per_room": 6,
    }


def _preset_industrial_bay(
    canvas_w: int = 2048, canvas_h: int = 1024, wall: int = 48
) -> dict:
    """Single large industrial bay with a small annex/control booth on one side."""
    bay = (0, 0, canvas_w * 3 // 4 + wall, canvas_h)
    booth_w = canvas_w - bay[2] + wall
    booth_h = canvas_h // 2
    booth = (bay[2] - wall, (canvas_h - booth_h) // 2, booth_w, booth_h)
    door_w = 128
    doors = [
        (bay[2] - wall, booth[1] + (booth_h - door_w) // 2, wall, door_w),
    ]
    return {
        "canvas": (canvas_w, canvas_h),
        "wall_thickness": wall,
        "rooms": [bay, booth],
        "corridors": [],
        "doors": doors,
        "light_count_per_room": 8,
    }


def _preset_archive_stacks_grid(
    canvas_w: int = 1792, canvas_h: int = 1280, wall: int = 24
) -> dict:
    """Grid of small archive vaults connected by a central spine corridor."""
    spine_h = 160
    spine_y = (canvas_h - spine_h) // 2
    spine = (0, spine_y, canvas_w, spine_h)

    vault_w = canvas_w // 4
    vault_h = (canvas_h - spine_h) // 2
    vaults = []
    doors = []
    door_w = 96
    for i in range(4):
        x = i * vault_w
        # top row
        v = (x, 0, vault_w + wall, vault_y_h := vault_h + wall)
        if i == 3:
            v = (x, 0, canvas_w - x, vault_y_h)
        vaults.append(v)
        # door from this top vault into spine
        doors.append((v[0] + (v[2] - door_w) // 2, spine_y, door_w, wall))
        # bottom row
        bv = (x, spine_y + spine_h - wall, v[2], canvas_h - (spine_y + spine_h) + wall)
        vaults.append(bv)
        doors.append((bv[0] + (bv[2] - door_w) // 2, spine_y + spine_h - wall, door_w, wall))
    return {
        "canvas": (canvas_w, canvas_h),
        "wall_thickness": wall,
        "rooms": vaults,
        "corridors": [spine],
        "doors": doors,
        "light_count_per_room": 4,
        "light_count_per_corridor": 8,
    }


# --- Spacecraft deck presets ---------------------------------------------
#
# Multi-deck ships need each deck to share the SAME outer hull footprint
# while having different deck-specific interior architecture. The presets
# below all use SHIP_HULL_W/H + SHIP_HULL_INSET so the outer hull is
# byte-for-byte identical across decks; only the interior changes. Render
# each deck via `spacecraft --layout <preset>.png --style ship-<deck>`
# to get pixel-aligned multi-deck stacks for Foundry.

SHIP_HULL_W = 1792
SHIP_HULL_H = 1024
SHIP_HULL_INSET = 96   # outer black border so the ship doesn't touch the canvas edge
SHIP_WALL = 36         # bulkhead thickness
SHIP_DOOR_W = 96       # standard interior door width


def _ship_hull_rect() -> tuple[int, int, int, int]:
    """The shared outer hull rectangle used by every ship-* preset."""
    x = SHIP_HULL_INSET
    y = SHIP_HULL_INSET
    w = SHIP_HULL_W - 2 * SHIP_HULL_INSET
    h = SHIP_HULL_H - 2 * SHIP_HULL_INSET
    return x, y, w, h


def _preset_ship_bridge() -> dict:
    """Bridge deck: hull + U-shaped console array forward + windscreen north."""
    hx, hy, hw, hh = _ship_hull_rect()
    hull = (hx, hy, hw, hh)

    # U-shaped console band along the forward (north) third of the deck.
    # Two side console banks + one cross-band, leaving a captain's gap mid.
    console_z = hy + SHIP_WALL + 80
    console_h = 80
    console_inset = SHIP_WALL + 80
    console_left = (hx + console_inset, console_z, hw // 4, console_h)
    console_right = (hx + hw - console_inset - hw // 4, console_z, hw // 4, console_h)
    # Cross-band at the very front, with a center gap for the captain's view.
    cross_y = hy + SHIP_WALL
    cross_w = hw - 2 * console_inset
    cross_h = 50
    half_cross = (cross_w - SHIP_DOOR_W) // 2
    cross_left = (hx + console_inset, cross_y, half_cross, cross_h)
    cross_right = (hx + console_inset + half_cross + SHIP_DOOR_W, cross_y, half_cross, cross_h)

    # Forward windscreen — long blue band along the north hull wall.
    # Painted as 'walls' tagged windscreen by overpainting later.
    return {
        "canvas": (SHIP_HULL_W, SHIP_HULL_H),
        "wall_thickness": SHIP_WALL,
        "rooms": [hull],
        "corridors": [],
        # Treat the console banks as additional 'rooms' so they get a
        # walled border + inner floor — reads as raised console surfaces.
        "extra_walls": [console_left, console_right, cross_left, cross_right],
        "doors": [],
        "windscreen": {
            "side": "north",
            "thickness": 28,
            "frac": 0.55,  # length as a fraction of hull width
        },
        "light_count_per_room": 6,
    }


def _preset_ship_engineering() -> dict:
    """Engineering deck: hull + central reactor well + side control panels + rear ramp."""
    hx, hy, hw, hh = _ship_hull_rect()
    hull = (hx, hy, hw, hh)

    # Reactor well — a square wall ring near the center.
    reactor_size = min(hw, hh) // 3
    reactor_x = hx + (hw - reactor_size) // 2
    reactor_y = hy + (hh - reactor_size) // 2
    reactor = (reactor_x, reactor_y, reactor_size, reactor_size)

    # Side control panel banks — two long thin walled rooms hugging the
    # east and west hull walls.
    panel_inset = SHIP_WALL + 40
    panel_h = hh - 2 * panel_inset
    panel_w = 100
    panel_west = (hx + panel_inset, hy + panel_inset, panel_w, panel_h)
    panel_east = (hx + hw - panel_inset - panel_w, hy + panel_inset, panel_w, panel_h)

    # Rear cargo ramp — extension breaking the south hull wall.
    ramp_w = hw // 4
    ramp_h = SHIP_HULL_INSET  # reach the canvas edge
    ramp = {
        "side": "south",
        "x_frac": 0.5,  # centered
        "width_frac": ramp_w / hw,
    }
    return {
        "canvas": (SHIP_HULL_W, SHIP_HULL_H),
        "wall_thickness": SHIP_WALL,
        "rooms": [hull, reactor, panel_west, panel_east],
        "corridors": [],
        "doors": [],
        "ramp": ramp,
        "light_count_per_room": 6,
    }


def _preset_ship_barracks() -> dict:
    """Barracks deck: hull + double rows of bunk-cell walls flanking center walkway."""
    hx, hy, hw, hh = _ship_hull_rect()
    hull = (hx, hy, hw, hh)

    # Bunk cells: two rows of small rectangles along the long axis.
    bunk_w = 110
    bunk_h = 180
    n_bunks = 8
    cells_per_side = n_bunks
    side_band_y_top = hy + SHIP_WALL + 60
    side_band_y_bot = hy + hh - SHIP_WALL - 60 - bunk_h
    spacing = (hw - 2 * (SHIP_WALL + 60) - cells_per_side * bunk_w) // max(1, cells_per_side - 1)
    bunks_top: list[tuple[int, int, int, int]] = []
    bunks_bot: list[tuple[int, int, int, int]] = []
    for i in range(cells_per_side):
        x = hx + SHIP_WALL + 60 + i * (bunk_w + spacing)
        bunks_top.append((x, side_band_y_top, bunk_w, bunk_h))
        bunks_bot.append((x, side_band_y_bot, bunk_w, bunk_h))
    # Bunks are sub-structures, not full rooms — go in extra_walls so the
    # painter doesn't decorate each bunk with its own perimeter lights.
    return {
        "canvas": (SHIP_HULL_W, SHIP_HULL_H),
        "wall_thickness": SHIP_WALL,
        "rooms": [hull],
        "corridors": [],
        "extra_walls": bunks_top + bunks_bot,
        "doors": [],
        "light_count_per_room": 8,
    }


def _preset_ship_cargo() -> dict:
    """Cargo hold: hull + container grid + center aisle + rear loading ramp."""
    hx, hy, hw, hh = _ship_hull_rect()
    hull = (hx, hy, hw, hh)

    # Container grid: rows of square wall blocks flanking a wide center aisle.
    container = 130
    spacing = 24
    cols = 9
    cargo_top_y = hy + SHIP_WALL + 60
    cargo_bot_y = hy + hh - SHIP_WALL - 60 - container
    side_block_w = cols * container + (cols - 1) * spacing
    block_x_start = hx + (hw - side_block_w) // 2
    containers: list[tuple[int, int, int, int]] = []
    for c in range(cols):
        x = block_x_start + c * (container + spacing)
        containers.append((x, cargo_top_y, container, container))
        containers.append((x, cargo_bot_y, container, container))
    # Rear loading ramp.
    ramp = {
        "side": "south",
        "x_frac": 0.5,
        "width_frac": 0.45,
    }
    # Containers are sub-structures: extra_walls (no per-block lights).
    return {
        "canvas": (SHIP_HULL_W, SHIP_HULL_H),
        "wall_thickness": SHIP_WALL,
        "rooms": [hull],
        "corridors": [],
        "extra_walls": containers,
        "doors": [],
        "ramp": ramp,
        "light_count_per_room": 8,
    }


FLOORPLAN_PRESETS: dict[str, "callable[[], dict]"] = {  # type: ignore[type-arg]
    "hab-2room": _preset_hab_2room,
    "hab-3room-corridor": _preset_hab_3room_corridor,
    "tunnel-junction": _preset_tunnel_junction,
    "chapel-nave-with-apse": _preset_chapel_nave_with_apse,
    "industrial-bay": _preset_industrial_bay,
    "archive-stacks-grid": _preset_archive_stacks_grid,
    "ship-bridge": _preset_ship_bridge,
    "ship-engineering": _preset_ship_engineering,
    "ship-barracks": _preset_ship_barracks,
    "ship-cargo": _preset_ship_cargo,
}


def _quantize_layout(
    src: Path,
    dest: Path,
    *,
    force_background_black: bool = False,
    far_threshold: int = 25,
) -> None:
    """Snap each pixel of `src` to the nearest canonical region color.

    Two-stage strategy:

    1. **Modal-background detection.** The most common color in the
       image (computed in 16-step bins to absorb anti-aliasing) is
       declared "background." Pixels close to that color (within a
       loose Chebyshev tolerance) are removed from the quantization
       step entirely and emitted as either pure black (when
       `force_background_black=True`) or unchanged.
    2. **Force-snap to canonical palette.** Every remaining pixel is
       snapped to the nearest canonical region color WITHOUT a
       distance cap. This handles hand-painted layouts where the
       painter approximated the canonical colors — a teal blob the
       painter intended as "windscreen" still snaps to the canonical
       windscreen color even if it drifted 60+ channels.

    `far_threshold` is now only used for the background-detection
    radius, not for the palette-snap cutoff.
    """
    import numpy as np
    from PIL import Image

    palette = list(SPACECRAFT_REGION_RGB.values())
    palette_arr = np.array(palette, dtype=np.int16)  # (R, 3)

    im = Image.open(src).convert("RGB")
    arr = np.array(im, dtype=np.int16)  # (H, W, 3)
    h, w, _ = arr.shape
    flat = arr.reshape(-1, 3)  # (N, 3)
    n_px = flat.shape[0]

    # Stage 1: find the modal color via 16-step binning. The bin with
    # the most pixels (regardless of palette membership) is background.
    binned = (flat // 16).astype(np.int32)
    keys = binned[:, 0] * 256 * 256 + binned[:, 1] * 256 + binned[:, 2]
    unique_keys, counts = np.unique(keys, return_counts=True)
    top_key = unique_keys[counts.argmax()]
    bg_bin = np.array(
        [(top_key >> 16) & 0xFF, (top_key >> 8) & 0xFF, top_key & 0xFF],
        dtype=np.int16,
    )
    bg_color = bg_bin * 16 + 8  # bin centroid

    # Background mask: pixels close to the modal color.
    dist_to_bg = np.abs(flat - bg_color[None, :]).max(axis=1)
    bg_mask = dist_to_bg <= far_threshold

    # Stage 2: every non-background pixel snaps to nearest canonical color.
    diffs = np.abs(flat[:, None, :] - palette_arr[None, :, :]).max(axis=2)  # (N, R)
    nearest = diffs.argmin(axis=1)
    snapped = palette_arr[nearest]  # (N, 3)

    # Compose output.
    if force_background_black:
        snapped[bg_mask] = (0, 0, 0)
    else:
        snapped[bg_mask] = flat[bg_mask]

    print(
        f"[quantize] modal-bg={tuple(int(c) for c in bg_color)} "
        f"covers {bg_mask.sum() / n_px * 100:.1f}% of pixels; "
        f"snapped {(~bg_mask).sum():,} px to canonical palette",
        file=sys.stderr,
    )
    out_arr = snapped.reshape(h, w, 3).astype(np.uint8)
    Image.fromarray(out_arr, mode="RGB").save(dest)


def _mask_render_by_layout(
    render_path: Path,
    *,
    layout_path: Path,
    target_rgb: tuple[int, int, int],
    tol: int = 40,
) -> Path:
    """Use the layout PNG as an alpha mask over the rendered PNG.

    Pixels in the layout that are within `tol` (Chebyshev distance) of
    `target_rgb` become opaque in the output; all other pixels become
    fully transparent. The layout is resampled to the render's
    dimensions if they differ.

    This produces a clean "<role>-only" layer — e.g. for walls it
    yields a transparent-background PNG with just the rendered walls
    visible, suitable for the Foundry foreground / overlay tile layer.
    """
    from PIL import Image  # heavy import path; lazy

    render = Image.open(render_path).convert("RGBA")
    layout = Image.open(layout_path).convert("RGB")
    if layout.size != render.size:
        layout = layout.resize(render.size, Image.NEAREST)
    rw, rh = render.size
    rpx = render.load()
    lpx = layout.load()
    tr, tg, tb = target_rgb
    kept = 0
    for y in range(rh):
        for x in range(rw):
            lr, lg, lb = lpx[x, y]
            if abs(lr - tr) <= tol and abs(lg - tg) <= tol and abs(lb - tb) <= tol:
                kept += 1
            else:
                r, g, b, _a = rpx[x, y]
                rpx[x, y] = (r, g, b, 0)
    out = render_path.with_name(render_path.stem + "_alpha.png")
    render.save(out)
    print(
        f"[mask] kept {kept:,}/{rw * rh:,} px ({100 * kept / (rw * rh):.1f}%) → {out.name}",
        file=sys.stderr,
    )
    return out


def _saved_images_from_history(record: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for node_out in (record.get("outputs") or {}).values():
        for img in node_out.get("images") or []:
            if img.get("type") == "output":
                out.append(img)
    return out


def _download_first(server: str, saved: list[dict[str, str]], prefix: str) -> Path:
    chosen = saved[0]
    blob = fetch_output_image(server, chosen["filename"], chosen.get("subfolder", ""))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / chosen["filename"]
    dest.write_bytes(blob)
    print(f"[ok] {dest} ({len(blob):,} bytes)", file=sys.stderr)
    return dest


# --- CLI -------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=DEFAULT_SERVER)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("interior", help="txt2img Chroma-Flux battlemap")
    pi.add_argument(
        "--style",
        choices=sorted(INTERIOR_STYLES) + ["default"],
        default="default",
        help="archetype prompt for typical campaign locations. 'default' is "
        "a generic empty grimdark sci-fi room. Each style produces a bare "
        "(no-prop) map suitable for stamp overlay.",
    )
    pi.add_argument(
        "--t5xxl",
        default=None,
        help="override t5xxl prompt; mutually-exclusive with --style",
    )
    pi.add_argument(
        "--clip-l",
        default=None,
        help="override clip_l prompt; mutually-exclusive with --style",
    )
    pi.add_argument("--width", type=int, default=1024)
    pi.add_argument("--height", type=int, default=1024)
    pi.add_argument("--seed", type=int, default=0)
    pi.add_argument("--prefix", default="map_interior")
    pi.add_argument(
        "--floor-only",
        action="store_true",
        help="render the floor texture only, with no walls — the canonical "
        "stackable base layer. Walls go on a separate foreground/walls-only "
        "pass (see `spacecraft --walls-only`) or are stamped/hand-drawn. "
        "When set with --style, uses INTERIOR_STYLE_FLOOR_TEXTURES.",
    )

    ps = sub.add_parser("spacecraft", help="img2img regional-conditioning battlemap")
    ps.add_argument("--layout", type=Path, required=True, help="path to color-coded layout PNG")
    ps.add_argument("--seed", type=int, default=0)
    ps.add_argument("--prefix", default="map_spacecraft")
    ps.add_argument(
        "--walls-only",
        action="store_true",
        help="alias for --keep-only wall.",
    )
    ps.add_argument(
        "--keep-only",
        choices=sorted(SPACECRAFT_REGION_RGB),
        default=None,
        help="render normally then alpha-mask the output to keep ONLY pixels "
        "whose layout color matches this role (wall, floor, ramp, etc.). "
        "Produces a transparent-bg layer suitable for Foundry foreground.",
    )
    ps.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="ROLE=TEXT",
        help="override a region's t5xxl prompt. Example: "
        "--override floor='metal catwalk grating, scaffold flooring'. "
        "Combine with --keep-only floor to produce a scaffolding overlay "
        "over a separately-rendered base map.",
    )
    ps.add_argument(
        "--style",
        choices=sorted(INTERIOR_STYLE_FLOOR_TEXTURES),
        default=None,
        help="apply an archetype's floor texture as a `floor` region override. "
        "Equivalent to `--override floor=<INTERIOR_STYLE_FLOOR_TEXTURES[style]>` "
        "but spelled as a single named flag. Use this to render a hab/chapel/"
        "industrial interior on a multi-room layout instead of the default "
        "ship deck plating. Explicit --override floor=... wins.",
    )
    ps.add_argument(
        "--render-furniture",
        nargs="*",
        default=[],
        choices=sorted(SPACECRAFT_NEUTRALIZED),
        help="opt-in: render selected furniture roles (chair/locker/console) "
        "as part of the base map. By DEFAULT all furniture roles are "
        "neutralized and rendered as empty floor — furniture belongs on "
        "the stamp/tile layer in Foundry, not in the architectural base.",
    )

    pp = sub.add_parser("pull", help="sync workflows/ from the ComfyUI server")
    pp.add_argument("--names", nargs="*", help="specific workflow filenames; default = all")

    pc = sub.add_parser("clone", help="clone a server workflow under a new name (e.g. V2)")
    pc.add_argument("source", help="existing workflow name on server, e.g. BattlemapSpacecraft.json")
    pc.add_argument("dest", help="new workflow name, e.g. BattlemapSpacecraftV2.json")

    pml = sub.add_parser(
        "mask-by-layout",
        help="apply a layout's region mask to an arbitrary rendered image, "
        "producing a transparent-bg layer where only the named role's "
        "pixels are kept. Use to overlay an independent texture (e.g. "
        "txt2img scaffold) onto a layout-driven base map without "
        "relying on the spacecraft workflow's regional conditioning.",
    )
    pml.add_argument("render", type=Path, help="rendered image (RGB or RGBA)")
    pml.add_argument("layout", type=Path, help="canonical-color layout PNG")
    pml.add_argument(
        "--role",
        choices=sorted(SPACECRAFT_REGION_RGB),
        required=True,
        help="region role to keep (others become transparent)",
    )
    pml.add_argument(
        "--output",
        type=Path,
        help="output path (default: <render-stem>_<role>_only.png)",
    )

    pco = sub.add_parser(
        "compose",
        help="alpha-overlay a transparent layer (e.g. walls-only) onto a base "
        "battlemap. Produces a single PNG showing what the stacked scene "
        "looks like before placing it in Foundry. Useful for previewing "
        "without spinning up Foundry to verify alignment.",
    )
    pco.add_argument("base", type=Path, help="opaque base map PNG")
    pco.add_argument("overlay", type=Path, help="transparent overlay PNG (e.g. *_alpha.png)")
    pco.add_argument(
        "--output",
        type=Path,
        help="output path (default: <base-stem>_composed.png in the same dir)",
    )

    pmr = sub.add_parser(
        "make-room",
        help="emit a canonical-color rectangular-room layout PNG. Useful as a "
        "starting template for new battlemap locations without hand-painting.",
    )
    pmr.add_argument("output", type=Path)
    pmr.add_argument("--width", type=int, default=1024, help="image width in px")
    pmr.add_argument("--height", type=int, default=1024, help="image height in px")
    pmr.add_argument(
        "--wall-thickness",
        type=int,
        default=32,
        help="thickness of the perimeter wall in px",
    )
    pmr.add_argument(
        "--ramp-side",
        choices=["none", "north", "south", "east", "west"],
        default="none",
        help="add a loading ramp protruding from one wall",
    )
    pmr.add_argument(
        "--lights",
        type=int,
        default=4,
        help="number of light fixtures around the perimeter (0 to disable)",
    )

    pmf = sub.add_parser(
        "make-floorplan",
        help="emit a canonical-color multi-room floor-plan layout PNG. "
        "Rooms + corridors + doorways at arbitrary aspect ratios. "
        "Output feeds the spacecraft workflow as a layout.",
    )
    pmf.add_argument("output", type=Path)
    pmf.add_argument(
        "--preset",
        choices=sorted(FLOORPLAN_PRESETS),
        required=True,
        help="named preset for the room arrangement",
    )
    pmf.add_argument("--canvas-w", type=int, default=None, help="override canvas width")
    pmf.add_argument("--canvas-h", type=int, default=None, help="override canvas height")
    pmf.add_argument("--wall-thickness", type=int, default=None, help="override wall thickness")

    pmc = sub.add_parser(
        "make-corridor",
        help="emit a canonical-color corridor layout PNG. Long thin shape with "
        "walls on both long sides; useful for tunnel locations.",
    )
    pmc.add_argument("output", type=Path)
    pmc.add_argument("--length", type=int, default=2048, help="corridor length (px)")
    pmc.add_argument("--width", type=int, default=512, help="corridor cross-section width (px)")
    pmc.add_argument("--wall-thickness", type=int, default=24)
    pmc.add_argument(
        "--orientation",
        choices=["horizontal", "vertical"],
        default="horizontal",
    )
    pmc.add_argument(
        "--lights",
        type=int,
        default=8,
        help="number of light fixtures evenly spaced along the corridor walls",
    )

    pq = sub.add_parser(
        "quantize-layout",
        help="snap a hand-painted layout PNG to the canonical region colors. "
        "Removes anti-aliased edges that ComfyUI's ImageColorToMask misses "
        "and that the walls-only alpha mask passes through as transparent.",
    )
    pq.add_argument("input", type=Path, help="path to the layout PNG to quantize")
    pq.add_argument(
        "--output",
        type=Path,
        help="path to write the quantized PNG; defaults to <stem>_quantized.png",
    )
    pq.add_argument(
        "--background",
        choices=["unchanged", "black"],
        default="unchanged",
        help="how to treat pixels far from any region color: keep them as-is "
        "(default) or force to black (the layout's natural negative space).",
    )

    args = ap.parse_args()

    if args.cmd == "interior":
        if args.style != "default" and (args.t5xxl is not None or args.clip_l is not None):
            print("--style and --t5xxl/--clip-l are mutually exclusive", file=sys.stderr)
            return 2
        if args.floor_only and args.style != "default" and args.style not in INTERIOR_STYLE_FLOOR_TEXTURES:
            print(f"--floor-only has no texture defined for style {args.style!r}", file=sys.stderr)
            return 2
        if args.style != "default":
            if args.floor_only:
                t5 = INTERIOR_FLOOR_PROMPT_TEMPLATE.format(
                    texture=INTERIOR_STYLE_FLOOR_TEXTURES[args.style]
                )
            else:
                t5 = INTERIOR_STYLES[args.style]
            clip = _clip_l_for_style(args.style)
        else:
            t5 = args.t5xxl if args.t5xxl is not None else INTERIOR_DEFAULT_T5
            clip = args.clip_l if args.clip_l is not None else INTERIOR_DEFAULT_CLIP_L
        run_interior(
            args.server,
            t5xxl=t5,
            clip_l=clip,
            width=args.width,
            height=args.height,
            seed=args.seed,
            prefix=args.prefix,
            floor_only=args.floor_only,
        )
    elif args.cmd == "spacecraft":
        if not args.layout.exists():
            print(f"layout not found: {args.layout}", file=sys.stderr)
            return 2
        keep_only = args.keep_only
        if args.walls_only:
            if keep_only and keep_only != "wall":
                print("--walls-only conflicts with --keep-only", file=sys.stderr)
                return 2
            keep_only = "wall"
        overrides: dict[str, str] = {}
        if args.style is not None:
            overrides["floor"] = INTERIOR_STYLE_FLOOR_TEXTURES[args.style]
        for spec in args.override:
            if "=" not in spec:
                print(f"--override expects ROLE=TEXT, got {spec!r}", file=sys.stderr)
                return 2
            role, _, text = spec.partition("=")
            role = role.strip()
            if role not in SPACECRAFT_REGION_NODE_FOR:
                print(f"unknown role for --override: {role!r}; known: {list(SPACECRAFT_REGION_NODE_FOR)}", file=sys.stderr)
                return 2
            overrides[role] = text
        run_spacecraft(
            args.server,
            layout_path=args.layout,
            seed=args.seed,
            prefix=args.prefix,
            keep_only_role=keep_only,
            prompt_overrides=overrides,
            render_furniture=tuple(args.render_furniture),
        )
    elif args.cmd == "pull":
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        names = args.names or list_server_workflows(args.server)
        for name in names:
            body = fetch_server_workflow(args.server, name)
            (WORKFLOWS_DIR / name).write_text(json.dumps(body, indent=2))
            print(f"[pull] {name}", file=sys.stderr)
    elif args.cmd == "mask-by-layout":
        if not args.render.exists() or not args.layout.exists():
            print(f"missing input: render={args.render.exists()} layout={args.layout.exists()}", file=sys.stderr)
            return 2
        out = args.output or args.render.with_name(args.render.stem + f"_{args.role}_only.png")
        # Mask returns dest path; reuse the existing helper.
        # `_mask_render_by_layout` wants the dest naming "<stem>_alpha.png"
        # by default — we override by running it then renaming.
        import shutil
        tmp = _mask_render_by_layout(
            args.render,
            layout_path=args.layout,
            target_rgb=SPACECRAFT_REGION_RGB[args.role],
        )
        shutil.move(str(tmp), str(out))
        print(f"[mask-by-layout] -> {out}", file=sys.stderr)
    elif args.cmd == "compose":
        if not args.base.exists() or not args.overlay.exists():
            print(f"missing input(s): base={args.base.exists()} overlay={args.overlay.exists()}", file=sys.stderr)
            return 2
        out = args.output or args.base.with_name(args.base.stem + "_composed.png")
        _compose_layers(args.base, args.overlay, out)
        print(f"[compose] -> {out}", file=sys.stderr)
    elif args.cmd == "make-room":
        _make_rectangular_room(
            args.output,
            width=args.width,
            height=args.height,
            wall_thickness=args.wall_thickness,
            ramp_side=args.ramp_side if args.ramp_side != "none" else None,
            light_count=args.lights,
        )
        print(f"[make-room] -> {args.output}", file=sys.stderr)
    elif args.cmd == "make-floorplan":
        builder = FLOORPLAN_PRESETS[args.preset]
        kwargs: dict = {}
        if args.canvas_w is not None:
            kwargs["canvas_w"] = args.canvas_w
        if args.canvas_h is not None:
            kwargs["canvas_h"] = args.canvas_h
        if args.wall_thickness is not None:
            kwargs["wall"] = args.wall_thickness
        spec = builder(**kwargs)
        _make_floorplan(args.output, spec=spec)
        print(f"[make-floorplan] -> {args.output} preset={args.preset} canvas={spec['canvas']}", file=sys.stderr)
    elif args.cmd == "make-corridor":
        _make_corridor(
            args.output,
            length=args.length,
            width=args.width,
            wall_thickness=args.wall_thickness,
            orientation=args.orientation,
            light_count=args.lights,
        )
        print(f"[make-corridor] -> {args.output}", file=sys.stderr)
    elif args.cmd == "quantize-layout":
        if not args.input.exists():
            print(f"layout not found: {args.input}", file=sys.stderr)
            return 2
        out = args.output or args.input.with_name(args.input.stem + "_quantized.png")
        _quantize_layout(args.input, out, force_background_black=(args.background == "black"))
        print(f"[quantize] {args.input.name} -> {out}", file=sys.stderr)
    elif args.cmd == "clone":
        body = fetch_server_workflow(args.server, args.source)
        existing = list_server_workflows(args.server)
        if args.dest in existing:
            print(f"refusing to overwrite existing server workflow: {args.dest}", file=sys.stderr)
            return 2
        write_server_workflow(args.server, args.dest, body)
        # Mirror locally so subsequent --workflow flags work without a re-pull.
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        (WORKFLOWS_DIR / args.dest).write_text(json.dumps(body, indent=2))
        print(f"[clone] {args.source} -> {args.dest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
