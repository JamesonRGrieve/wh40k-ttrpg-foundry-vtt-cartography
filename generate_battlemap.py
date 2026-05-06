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
WORKFLOWS_DIR = HERE / "workflows"
OUT_DIR = HERE / "battlemaps"
POLL_TIMEOUT_S = 600  # Chroma at 1024² is slow on the 3090; allow plenty.


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
        "polished stone floor with mosaic Aquila pattern, candle wax and grime accumulated at edges, "
        "tall stone walls with carved Imperial iconography and brass relief panels, "
        "stained-glass slit windows casting colored light, votive candles in alcoves, "
        "muted earth-tone palette with golden accent, oil painting style, "
        "tabletop RPG battle map, highly detailed mosaic floor and stonework wall textures, "
        "completely empty nave with no pews, no furniture, no characters"
    ),
    "bar": (
        "top-down overhead orthographic view of an empty grimy underground bar interior, "
        "warhammer 40000 aesthetic, sub-level hive watering hole, "
        "scuffed wood plank floor with stains and burn marks and old blood, "
        "low brick walls with peeling posters and dim hanging lights, "
        "amber lumen pendants over where tables would be, deep shadows in corners, "
        "muted brown and amber palette, oil painting style, "
        "tabletop RPG battle map, highly detailed floor and wall textures, "
        "completely empty room with no tables, no chairs, no bar counter, no props, no characters"
    ),
    "garrison": (
        "top-down overhead orthographic view of an empty Imperial Guard garrison barracks interior, "
        "warhammer 40000 aesthetic, regimental quarters, "
        "scuffed concrete floor with painted hazard markings and dirt drag patterns, "
        "spartan reinforced walls with regimental banners and weapon racks bare of weapons, "
        "harsh overhead fluorescent strip lighting, deep shadow gaps between fixtures, "
        "muted gray and military-green palette, oil painting style, "
        "tabletop RPG battle map, highly detailed floor and wall textures, "
        "completely empty barracks with no bunks, no furniture, no equipment, no characters"
    ),
}

INTERIOR_STYLE_TAGS: dict[str, str] = {
    "hab": "hab apartment, ferrocrete floor, hive sub-level",
    "tunnel": "maintenance tunnel, narrow corridor, cabled walls",
    "industrial": "industrial bay, ore processor, hazard stripes",
    "chapel": "Imperial chapel, mosaic floor, stone walls",
    "bar": "underground bar, wood floor, dim hanging lights",
    "garrison": "Imperial Guard barracks, military",
}


def _clip_l_for_style(style: str) -> str:
    return f"grimdark sci-fi, top-down battle map, empty room, {INTERIOR_STYLE_TAGS[style]}, tabletop rpg"


def run_interior(
    server: str,
    *,
    t5xxl: str,
    clip_l: str,
    width: int,
    height: int,
    seed: int,
    prefix: str,
) -> Path:
    wf = load_template("BattlemapInteriorV1")
    set_prompt(wf, "pos", t5xxl=t5xxl, clip_l=clip_l)
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
# ImageColorToMask nodes. The map is the source of truth for both the
# regional conditioning AND the post-render alpha-extraction layer
# pipeline below.
SPACECRAFT_REGION_RGB: dict[str, tuple[int, int, int]] = {
    "wall": (0x30, 0x30, 0x30),       # 3158064  — bulkhead walls
    "floor": (0x80, 0x80, 0x80),      # 8421504  — deck plating
    "ramp": (0xA0, 0xA0, 0xA0),       # 10526880 — loading ramp
    "windscreen": (0x1A, 0x27, 0x50), # 1716304  — cockpit viewport
    "chair": (0x8B, 0x5E, 0x2B),      # 9132587  — pilot chair
    "locker": (0x4A, 0x6F, 0x40),     # 4876928  — storage locker
    "console": (0x2A, 0x42, 0x50),    # 2771536  — instrument console
    "lighting": (0xD4, 0xB2, 0x60),   # 13934624 — lumen strip
}


def run_spacecraft(
    server: str,
    *,
    layout_path: Path,
    seed: int,
    prefix: str,
    keep_only_role: str | None = None,
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

    ps = sub.add_parser("spacecraft", help="img2img regional-conditioning battlemap")
    ps.add_argument("--layout", type=Path, required=True, help="path to color-coded layout PNG")
    ps.add_argument("--seed", type=int, default=0)
    ps.add_argument("--prefix", default="map_spacecraft")
    ps.add_argument(
        "--walls-only",
        action="store_true",
        help="render only the wall region; everything else becomes transparent. "
        "Output PNG has alpha; suitable for Foundry foreground/overlay layer.",
    )

    pp = sub.add_parser("pull", help="sync workflows/ from the ComfyUI server")
    pp.add_argument("--names", nargs="*", help="specific workflow filenames; default = all")

    pc = sub.add_parser("clone", help="clone a server workflow under a new name (e.g. V2)")
    pc.add_argument("source", help="existing workflow name on server, e.g. BattlemapSpacecraft.json")
    pc.add_argument("dest", help="new workflow name, e.g. BattlemapSpacecraftV2.json")

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
        if args.style != "default":
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
        )
    elif args.cmd == "spacecraft":
        if not args.layout.exists():
            print(f"layout not found: {args.layout}", file=sys.stderr)
            return 2
        run_spacecraft(
            args.server,
            layout_path=args.layout,
            seed=args.seed,
            prefix=args.prefix,
            keep_only_role="wall" if args.walls_only else None,
        )
    elif args.cmd == "pull":
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        names = args.names or list_server_workflows(args.server)
        for name in names:
            body = fetch_server_workflow(args.server, name)
            (WORKFLOWS_DIR / name).write_text(json.dumps(body, indent=2))
            print(f"[pull] {name}", file=sys.stderr)
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
