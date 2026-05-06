#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow"]
# ///
"""
Classify each extracted stamp against a remote ComfyUI server running
the Florence-2 captioner, then write the results back into the YAML
sidecar.

For each `stamps/<stem>_NN.png` whose sidecar's `classified_at` is null
(or `--force`):

  1. Upload the PNG to the ComfyUI server's input directory.
  2. Submit a workflow that runs Florence-2 with two tasks:
     - `more_detailed_caption` → free-text prose description
     - `prompt_gen_tags`        → comma-separated tag list
  3. Poll `/history/<prompt_id>` until the run completes.
  4. Parse the outputs into the sidecar fields:
     - `name`         — first noun-phrase from the caption
     - `description`  — the caption (cleaned)
     - `tags`         — normalized union of tag-list + caption-keyword tags
     - `orientation`  — keyword-mapped from caption (left/right/front/top/...)
     - `state`        — keyword-mapped from caption (broken/damaged/...)
     - `classified_at`, `classified_by`

Update is in-place via a small line-level YAML rewrite — preserves
any manual edits to fields we did NOT classify.

Stdlib-only on purpose so the script Just Works under `uv run`.

Usage:
    uv run classify_stamps.py             # incremental (skip already classified)
    uv run classify_stamps.py --force     # re-classify everything
    uv run classify_stamps.py --limit 5   # smoke-test on first N stamps
    uv run classify_stamps.py --server http://other:8188
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image

DEFAULT_SERVER = "http://198.51.100.11:8188"
# MiaoshouAI's PromptGen finetune is trained on diverse object/asset images and
# produces clean noun-phrase captions (vs. Florence-2-base, which hallucinates
# "a set of ..." or background-only descriptions for our cartography stamps).
# It also unlocks the prompt_gen_tags task (base returns region tokens for it).
MODEL_NAME = "MiaoshouAI/Florence-2-large-PromptGen-v2.0"
SUBFOLDER = "dh_classify"  # subdirectory under ComfyUI's input/ for our uploads
HERE = Path(__file__).resolve().parent
STAMPS_DIR = HERE / "stamps"

POLL_INTERVAL_S = 1.2
POLL_TIMEOUT_S = 300

# --- Vocabulary post-processing -------------------------------------------------

ORIENTATION_KEYWORDS: dict[str, str] = {
    "top down": "top-down",
    "top-down": "top-down",
    "bird's eye": "top-down",
    "overhead": "top-down",
    "from above": "top-down",
    "isometric": "isometric",
    "three-quarter": "isometric",
    "facing left": "west",
    "from the left": "west",
    "left side": "west",
    "facing right": "east",
    "from the right": "east",
    "right side": "east",
    "facing forward": "south",
    "front view": "south",
    "from the front": "south",
    "facing backward": "north",
    "back view": "north",
    "from behind": "north",
}

STATE_KEYWORDS: dict[str, str] = {
    # severity (most specific to least)
    "destroyed": "destroyed",
    "shattered": "destroyed",
    "wreckage": "destroyed",
    "ruined": "destroyed",
    "damaged": "damaged",
    "broken": "damaged",
    "cracked": "damaged",
    "rusted": "damaged",
    "rusty": "damaged",
    "dented": "damaged",
    "scuffed": "damaged",
    "scratched": "damaged",
    "scorched": "damaged",
    "stained": "damaged",
    "weathered": "damaged",
    "worn": "damaged",
    "aged": "damaged",
    "tattered": "damaged",
    "frayed": "damaged",
    # active/inactive — keep these specific so we don't false-positive
    # on common prepositions ("on top of", "on the left").
    "switched on": "active",
    "powered on": "active",
    "lit up": "active",
    "glowing": "active",
    "illuminated": "active",
    "switched off": "inactive",
    "powered off": "inactive",
    "turned off": "inactive",
    "unlit": "inactive",
    "darkened": "inactive",
    # intact / pristine
    "intact": "intact",
    "pristine": "intact",
    "polished": "intact",
    "brand new": "intact",
    "spotless": "intact",
}

# Lowercase-hyphenated transformer for raw Florence-2 tags
NORMALIZE_TAG_RE = re.compile(r"[^a-z0-9]+")


def normalize_tag(t: str) -> str:
    s = NORMALIZE_TAG_RE.sub("-", t.strip().lower()).strip("-")
    return s


# --- ComfyUI HTTP client --------------------------------------------------------


def _request(server: str, path: str, *, data: bytes | None = None, headers: dict | None = None, method: str | None = None, timeout: float = 30) -> bytes:
    url = f"{server.rstrip('/')}{path}"
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} from {path}: {body[:600]}") from None


CLASSIFIER_RETRY_SIDE = 768


def square_png_bytes(png_path: Path, *, retry: bool = False) -> bytes:
    """Build the classifier-input PNG.

    Two passes:

    * **Default pass** (retry=False): square-pad with transparent
      background, no upscale. This is what works for most stamps —
      Florence-2-large-PromptGen-v2.0 captions ~80% of cells correctly
      at native resolution (150-260px) with a transparent background.
    * **Retry pass** (retry=True): upscale the longer edge to
      CLASSIFIER_RETRY_SIDE (768), then square-pad and flatten on
      white. Use this when the default pass returns empty captions.
      Verified to recover stamps that the default misses (e.g. small
      parchment-with-seal artwork).

    Empirically the white-bg+upscale path BREAKS some stamps that the
    default works on (verified A/B on the bowls stamp _00.png), and
    the default BREAKS some stamps that white-bg+upscale works on
    (parchment stamp _02.png). They are complementary, not strictly
    better/worse — hence the two-pass retry strategy in
    `classify_one()`.

    The on-disk PNG is NEVER modified — both transforms only affect
    the bytes uploaded to ComfyUI. Stamps stay transparent on disk for
    compositing in Foundry.
    """
    with Image.open(png_path) as im:
        rgba = im.convert("RGBA")
        w, h = rgba.size
        if retry:
            scale = max(1.0, CLASSIFIER_RETRY_SIDE / max(w, h))
            if scale > 1.0:
                new_w, new_h = int(round(w * scale)), int(round(h * scale))
                rgba = rgba.resize((new_w, new_h), Image.LANCZOS)
                w, h = new_w, new_h
            bg = (255, 255, 255, 255)
        else:
            bg = (0, 0, 0, 0)
        side = max(w, h)
        canvas = Image.new("RGBA", (side, side), bg)
        canvas.paste(rgba, ((side - w) // 2, (side - h) // 2), rgba)
        buf = BytesIO()
        if retry:
            canvas.convert("RGB").save(buf, format="PNG")
        else:
            canvas.save(buf, format="PNG")
        return buf.getvalue()


def upload_image(server: str, png_path: Path, *, retry: bool = False) -> str:
    """Upload a square-padded PNG to ComfyUI's input directory.

    `retry=True` switches `square_png_bytes` to the upscale+white-bg
    fallback path. The server-side filename is suffixed with `__retry`
    so the retry payload doesn't share a content hash (or a LoadImage
    cache slot) with the default-pass upload.
    """
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    upload_name = png_path.name
    if retry:
        upload_name = png_path.stem + "__retry" + png_path.suffix
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{upload_name}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode()
    )
    parts.append(square_png_bytes(png_path, retry=retry))
    parts.append(b"\r\n")
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="subfolder"\r\n\r\n'
            f"{SUBFOLDER}\r\n"
        ).encode()
    )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
            f"true\r\n"
        ).encode()
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    raw = _request(
        server,
        "/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
        timeout=60,
    )
    info = json.loads(raw)
    return info.get("name") or png_path.name


def submit_prompt(server: str, workflow: dict, client_id: str) -> str:
    payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode()
    raw = _request(
        server, "/prompt", data=payload,
        headers={"Content-Type": "application/json"}, method="POST", timeout=30,
    )
    return json.loads(raw)["prompt_id"]


def poll_history(server: str, prompt_id: str, timeout: float = POLL_TIMEOUT_S) -> dict:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            raw = _request(server, f"/history/{prompt_id}", timeout=10)
        except (urllib.error.URLError, RuntimeError):
            time.sleep(POLL_INTERVAL_S)
            continue
        hist = json.loads(raw)
        # The /history endpoint returns ALL recent prompts. We want our
        # specific prompt_id, AND we want to wait until it has actually
        # finished — not just merely registered.
        entry = hist.get(prompt_id) if isinstance(hist, dict) else None
        if entry and entry.get("status", {}).get("completed"):
            return entry
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"prompt {prompt_id} did not complete in {timeout}s")


def build_workflow(server_filename: str) -> dict:
    image_ref = f"{SUBFOLDER}/{server_filename}" if SUBFOLDER else server_filename
    common_run_inputs: dict = {
        "florence2_model": ["loader", 0],
        "image": ["loader_image", 0],
        "text_input": "",
        "fill_mask": False,
        # 1024 tokens is the floor for our upscaled-to-768 inputs. At 256
        # tokens the model truncates mid-generation and PromptGen returns
        # empty text for some images (especially detailed scenes). Verified
        # by A/B test in CLAUDE.md gotcha #9.
        "keep_model_loaded": True,
        "max_new_tokens": 1024,
        "num_beams": 3,
        "do_sample": False,
        "output_mask_select": "",
        "seed": 1,
    }
    return {
        "loader_image": {
            "class_type": "LoadImage",
            "inputs": {"image": image_ref, "upload": "image"},
        },
        "loader": {
            "class_type": "DownloadAndLoadFlorence2Model",
            "inputs": {
                "model": MODEL_NAME,
                "precision": "fp16",
                "attention": "sdpa",
                "convert_to_safetensors": False,
            },
        },
        "caption": {
            "class_type": "Florence2Run",
            "inputs": {**common_run_inputs, "task": "more_detailed_caption"},
        },
        "tags": {
            "class_type": "Florence2Run",
            "inputs": {**common_run_inputs, "task": "prompt_gen_tags"},
        },
        # PreviewAny is an OUTPUT_NODE that captures any input into /history.
        # Florence2Run is not an output node on its own; without these wrappers
        # ComfyUI rejects the workflow as having no outputs.
        "save_caption": {
            "class_type": "PreviewAny",
            "inputs": {"source": ["caption", 2]},
        },
        "save_tags": {
            "class_type": "PreviewAny",
            "inputs": {"source": ["tags", 2]},
        },
    }


def _flatten_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_flatten_text(v) for v in value).strip()
    if isinstance(value, dict):
        # Pull common shapes used by PreviewAny / ShowText forks.
        for key in ("text", "string", "value", "result", "caption"):
            if key in value:
                return _flatten_text(value[key])
        return ""
    return str(value).strip()


def extract_strings(history: dict) -> tuple[str, str]:
    """Pull (caption, tag-string) from a /history payload.

    The workflow wraps each Florence2Run output with a `PreviewAny` node
    (`save_caption`, `save_tags`). PreviewAny puts its captured value
    into the node's `outputs[node_id]` payload under a `text` key (or
    similar shapes depending on ComfyUI version).
    """
    outputs = history.get("outputs", {}) or {}

    def text_for(node_id: str) -> str:
        out = outputs.get(node_id) or {}
        # Try every value in the dict — PreviewAny's payload key varies
        # ('text' / 'string' / a list of dicts) across versions.
        for v in out.values():
            t = _flatten_text(v)
            if t:
                return t
        return ""

    caption = text_for("save_caption") or text_for("caption")
    tags_raw = text_for("save_tags") or text_for("tags")
    return caption, tags_raw


# --- Caption → sidecar fields ---------------------------------------------------

ARTICLE_RE = re.compile(r"^(an?\s+|the\s+|a\s+|some\s+|several\s+)", re.IGNORECASE)
# Match a noun phrase: optionally adjectives followed by one or more nouns,
# terminated at a clause-boundary word or punctuation. The trailing
# words list catches "is/are/with/of/on/..." and similar relations.
NOUN_PHRASE_RE = re.compile(
    r"^("
    r"(?:[A-Za-z][A-Za-z0-9\-]*[, ]+){0,4}"  # 0-4 leading adjectives/commas
    r"[A-Za-z][A-Za-z0-9\-]*"  # head noun
    r"(?:\s+[A-Za-z][A-Za-z0-9\-]*){0,2}"  # 0-2 trailing modifier nouns
    r")"
    r"(?=\s+(?:is|are|that|which|who|with|on|in|at|near|featuring|made|of|"
    r"sitting|standing|placed|lying|hanging|covered|painted|surrounded|"
    r"arranged|tied|attached|positioned|facing|drawn|rendered|illustrated|"
    r"appears?|appearing|appear)\b|[.,;])",
    re.IGNORECASE,
)
# Names shorter than this look like extraction failures, not real names.
NAME_MIN_LEN = 3


# Words that describe the medium/format rather than the subject. Florence-2
# (especially the PromptGen finetune) prepends long chains of these:
#   "The image is a digital illustration of two empty ceramic bowls"
#   "A 3D rendering of a wooden bed"
#   "A set of four rectangular frames"
# Strip them iteratively until what remains starts with a noun phrase.
_PREAMBLE_PHRASES = [
    # Document/establishing clauses.
    r"this image\s+(?:is|shows|depicts|features|contains|displays)\s+",
    r"the image\s+(?:is|shows|depicts|features|contains|displays)\s+",
    r"this\s+(?:is|shows|depicts|features|contains|displays)\s+",
    r"it\s+(?:is|shows|depicts|features|contains|displays)\s+",
    r"there (?:is|are)\s+",
    # Medium / format words. These can chain (e.g. "a digital
    # illustration"), so we apply repeatedly.
    r"(?:an?\s+|the\s+)?(?:digital|stylized|simple|minimalist|colorful|"
    r"detailed|hand[- ]drawn|hand[- ]painted|cartoon|cartoon-style|"
    r"oil[- ]painted|watercolor|3d|two-dimensional|2d|monochrome|"
    r"black[- ]and[- ]white|grayscale|vintage|aged|weathered|rustic|"
    r"isometric|top[- ]down|overhead)\s+",
    r"(?:an?\s+|the\s+)?(?:drawings?|illustrations?|pictures?|images?|"
    r"paintings?|renders?|renderings?|sketches?|depictions?|portraits?|"
    r"photographs?|photos?|diagrams?|graphics?|models?|figures?|"
    r"icons?|emojis?)\s+(?:of\s+)?",
    # Multiplicity wrappers ("a set of four ...", "a collection of ...",
    # "a pair of ..."). These are NOT subject nouns even though they
    # parse as such — the real subject sits after the "of".
    r"(?:an?\s+|the\s+)?(?:set|collection|series|group|pair|stack|pile|"
    r"row|line|cluster|bunch|assortment|variety|selection|array)\s+"
    r"(?:of\s+(?:\w+\s+)?)?",
    # Vague enumerators ("four ...", "various ...", "different types of ...").
    r"(?:various|different|several|multiple|many|a few|a couple of)\s+"
    r"(?:types?\s+of\s+|kinds?\s+of\s+)?",
    r"(?:two|three|four|five|six|seven|eight|nine|ten)\s+",
    # Trailing "of" connector left dangling after the above strips.
    r"of\s+",
    # Articles before the actual subject noun.
    r"(?:an?\s+|the\s+)",
]
_PREAMBLE_RES = [re.compile("^" + p, re.IGNORECASE) for p in _PREAMBLE_PHRASES]


def _strip_preamble(s: str) -> str:
    """Iteratively peel medium/multiplicity/article words off the front.

    Each pass tries each pattern in order; if any matches, we eat it
    and restart from the top. This handles arbitrary chains like
    "The image is a stylized digital illustration of a set of four ..."
    without having to write one mega-regex.
    """
    prev = None
    while s and s != prev:
        prev = s
        for r in _PREAMBLE_RES:
            m = r.match(s)
            if m:
                s = s[m.end() :].lstrip()
                break
    return s


def derive_name_from_caption(caption: str) -> str | None:
    if not caption:
        return None
    s = caption.strip()
    s = _strip_preamble(s)
    m = NOUN_PHRASE_RE.match(s)
    if m:
        phrase = m.group(1).strip().rstrip(",")
    else:
        # Take the first chunk up to the first comma/period, capped at 6 words.
        phrase = re.split(r"[.,;]", s, maxsplit=1)[0].strip()
        if len(phrase) > 60:
            phrase = " ".join(phrase.split()[:6])
    if not phrase or len(phrase) < NAME_MIN_LEN:
        return None
    # Reject names that are mostly non-letter characters (underscores,
    # whitespace, punctuation). Florence-2 occasionally returns
    # ASCII-art lines for stamps it can't caption; those leak through
    # the regex chain as long strings of underscores.
    letter_count = sum(1 for c in phrase if c.isalpha())
    if letter_count < NAME_MIN_LEN or letter_count / len(phrase) < 0.5:
        return None
    # Title-case multi-word phrases for readability ("wooden bed" → "Wooden Bed").
    if " " in phrase and phrase.islower():
        phrase = phrase.title()
    else:
        phrase = phrase[:1].upper() + phrase[1:]
    return phrase


def derive_orientation(caption: str) -> str | None:
    low = caption.lower()
    for kw, val in ORIENTATION_KEYWORDS.items():
        if kw in low:
            return val
    return None


def derive_state(caption: str) -> str | None:
    low = caption.lower()
    matched: list[str] = []
    for kw, val in STATE_KEYWORDS.items():
        if kw in low:
            matched.append(val)
    if not matched:
        return None
    # Prefer the most-specific severity if multiple match.
    for prio in ("destroyed", "damaged", "active", "inactive", "intact"):
        if prio in matched:
            return prio
    return matched[0]


# Words to drop from caption-derived tags (English stopwords + filler).
CAPTION_STOPWORDS = {
    "a", "an", "the", "of", "with", "and", "or", "in", "on", "at", "to",
    "for", "by", "from", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "he", "she", "they",
    "them", "his", "her", "their", "drawing", "image", "picture", "shows",
    "showing", "view", "one", "two", "three", "some", "many", "small",
    "large", "big", "little", "tall", "short", "next", "another", "very",
    "lot", "lots", "looks", "look", "appears", "appear", "seems", "seem",
    "made", "kind", "type", "color", "colors", "colored", "coloured",
    "black", "white", "gray", "grey", "brown", "red", "blue", "green",
    "yellow", "orange", "purple", "pink", "tan", "metallic",
}


def derive_tags(_unused: str, existing: list[str], *, caption: str = "") -> list[str]:
    """Build a tag list by tokenizing the caption + adding category tags.

    Two layers:
    1. Content words from the caption (preserved for keyword search).
    2. Category tags emitted by `derive_category_tags()` for Foundry's
       Mass Edit Preset Browser to filter on (chairs, lamps, doors, etc.).
    """
    out: list[str] = list(existing)
    seen = set(out)
    if caption:
        tokens = re.findall(r"[A-Za-z][A-Za-z\-']{2,}", caption.lower())
        for tok in tokens:
            norm = normalize_tag(tok)
            if not norm or len(norm) < 3 or len(norm) > 32:
                continue
            if norm in CAPTION_STOPWORDS or norm in seen:
                continue
            out.append(norm)
            seen.add(norm)
            if len(out) >= 12:
                break
    # Categories are emitted AFTER the content-word cap so they always
    # land in the tag list even on long captions.
    for cat in derive_category_tags(caption):
        if cat not in seen:
            out.append(cat)
            seen.add(cat)
    return out


# Category dictionary: maps subject keywords (lowercase) found in
# captions to one or more category tags. The first match per category
# wins; multiple categories can fire on one stamp ("a metal chair near
# a desk" → furniture-chair AND furniture-table). Extend by adding new
# (regex-pattern, [tags]) entries; ordering is significant only for
# observability.
_CATEGORY_RULES: list[tuple[re.Pattern[str], list[str]]] = [
    # Seating
    (re.compile(r"\b(chair|stool|seat|bench|throne)s?\b"), ["furniture", "furniture-chair"]),
    (re.compile(r"\b(couch|sofa|settee)s?\b"), ["furniture", "furniture-couch"]),
    (re.compile(r"\b(bed|cot|bunk|hammock)s?\b"), ["furniture", "furniture-bed"]),
    # Surfaces
    (re.compile(r"\b(desk|table|workbench|counter|console|altar|pedestal)s?\b"), ["furniture", "furniture-table"]),
    (re.compile(r"\b(shelf|shelving|bookshelf|rack)s?\b"), ["furniture", "furniture-shelf"]),
    # Containers
    (re.compile(r"\b(locker|cabinet|wardrobe|cupboard|storage unit)s?\b"), ["container", "container-locker"]),
    (re.compile(r"\b(crate|chest|trunk|box|case|coffer)s?\b"), ["container", "container-crate"]),
    (re.compile(r"\b(barrel|drum|cask|keg)s?\b"), ["container", "container-barrel"]),
    (re.compile(r"\b(jar|bottle|flask|vial|canister|jug)s?\b"), ["container", "container-vessel"]),
    (re.compile(r"\b(bowl|cup|mug|tankard|chalice|goblet|plate|dish)s?\b"), ["container", "container-tableware"]),
    (re.compile(r"\b(luggage|suitcase|bag|backpack|pack|satchel)s?\b"), ["container", "container-bag"]),
    # Lighting
    (re.compile(r"\b(lamp|lantern|sconce|candle|torch|chandelier|lumen|light fixture)s?\b"), ["light", "light-fixture"]),
    # Doors / portals
    (re.compile(r"\b(door|hatch|gate|portal|airlock|bulkhead door)s?\b"), ["door"]),
    # Documents / props
    (re.compile(r"\b(parchment|scroll|paper|document|tome|book|ledger|dossier|file)s?\b"), ["prop", "prop-document"]),
    (re.compile(r"\b(quill|pen|stylus|pencil|brush)s?\b"), ["prop", "prop-writing"]),
    (re.compile(r"\b(inkwell|inkpot)s?\b"), ["prop", "prop-writing"]),
    (re.compile(r"\b(seal|wax seal|sigil|emblem)s?\b"), ["prop", "prop-document"]),
    # Tech / electronics
    (re.compile(r"\b(television|monitor|screen|display|hololith|cogitator|terminal|workstation)s?\b"), ["tech", "tech-screen"]),
    (re.compile(r"\b(handheld|smartphone|dataslate|tablet|auspex)s?\b"), ["tech", "tech-device"]),
    (re.compile(r"\b(valve|pipe|conduit|cable|duct)s?\b"), ["tech", "tech-utility"]),
    # Architecture
    (re.compile(r"\b(window|viewport|porthole|windscreen)s?\b"), ["architecture", "architecture-window"]),
    (re.compile(r"\b(stair|staircase|step|ladder|ramp)s?\b"), ["architecture", "architecture-step"]),
    (re.compile(r"\b(wall|bulkhead|partition)s?\b"), ["architecture", "architecture-wall"]),
    (re.compile(r"\b(ceiling tile|deck plate|floor panel|grating)s?\b"), ["architecture", "architecture-surface"]),
    # Weapons / tools (for setting authenticity, not for combat use here)
    (re.compile(r"\b(sword|knife|dagger|blade|axe)s?\b"), ["weapon", "weapon-melee"]),
    (re.compile(r"\b(gun|pistol|rifle|lasgun|bolter|firearm|weapon)s?\b"), ["weapon", "weapon-ranged"]),
    (re.compile(r"\b(hammer|wrench|spanner|tool|toolbox)s?\b"), ["tool"]),
    # Decor
    (re.compile(r"\b(banner|flag|tapestry|standard|pennant)s?\b"), ["decor", "decor-banner"]),
    (re.compile(r"\b(statue|bust|sculpture|relief|icon)s?\b"), ["decor", "decor-statue"]),
    (re.compile(r"\b(rug|carpet|mat)s?\b"), ["decor", "decor-floor"]),
]


def derive_category_tags(caption: str) -> list[str]:
    """Match `caption` against the category dictionary and return the
    union of matched category tags. Returns [] if nothing matches.
    """
    if not caption:
        return []
    haystack = caption.lower()
    out: list[str] = []
    seen: set[str] = set()
    for rx, tags in _CATEGORY_RULES:
        if rx.search(haystack):
            for t in tags:
                if t not in seen:
                    out.append(t)
                    seen.add(t)
    return out


# --- Sidecar update -------------------------------------------------------------

SCALAR_KEYS = {"name", "description", "orientation", "state", "classified_at", "classified_by"}


def yaml_quote(value: str) -> str:
    if value is None:
        return "null"
    needs = any(c in value for c in ":#'\"\n[]{},&*?|>!%@`") or value.lower() in {"null", "true", "false"} or value.strip() != value
    if not needs:
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_tag_list(values: list[str]) -> str:
    if not values:
        return "[]"
    quoted = [yaml_quote(v) for v in values]
    return "[" + ", ".join(quoted) + "]"


def update_sidecar(yaml_path: Path, fields: dict) -> None:
    """Rewrite values for known top-level scalar keys; replace 'tags:' line.

    Anything else is preserved byte-for-byte. Comments, blank lines, key
    ordering — all stay.
    """
    if not yaml_path.exists():
        return
    lines = yaml_path.read_text().splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)(\s*#.*)?$", line.rstrip("\n"))
        if not m:
            out.append(line)
            continue
        key = m.group(1)
        comment = m.group(3) or ""
        eol = "\n" if line.endswith("\n") else ""
        if key in SCALAR_KEYS and key in fields:
            value = fields[key]
            rendered = yaml_quote(value) if value is not None else "null"
            out.append(f"{key}: {rendered}{comment}{eol}")
        elif key == "tags" and "tags" in fields:
            out.append(f"{key}: {yaml_tag_list(fields['tags'])}{comment}{eol}")
        else:
            out.append(line)
    yaml_path.write_text("".join(out))


def read_classified_at(yaml_path: Path) -> str | None:
    """Cheap line-grep for `classified_at:` value to support incremental runs."""
    if not yaml_path.exists():
        return None
    for raw in yaml_path.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        m = re.match(r"^classified_at:\s*(.*)$", line)
        if m:
            v = m.group(1).strip().strip('"').strip("'")
            return None if v == "" or v.lower() == "null" else v
    return None


# --- Driver ---------------------------------------------------------------------


def classify_one(server: str, png: Path, yaml_path: Path, client_id: str) -> tuple[str, str]:
    # First pass: native-size, transparent background. Works for most stamps.
    server_filename = upload_image(server, png)
    workflow = build_workflow(server_filename)
    prompt_id = submit_prompt(server, workflow, client_id)
    history = poll_history(server, prompt_id)
    caption, tags_raw = extract_strings(history)

    # Retry pass: upscale to 768 + flatten on white. Recovers stamps where
    # Florence-2 returns empty on the default payload (small/intricate
    # subjects like parchment with wax seal). Complementary, not strictly
    # better — see `square_png_bytes` docstring.
    if not caption and not tags_raw:
        retry_filename = upload_image(server, png, retry=True)
        retry_workflow = build_workflow(retry_filename)
        retry_pid = submit_prompt(server, retry_workflow, client_id)
        retry_history = poll_history(server, retry_pid)
        caption, tags_raw = extract_strings(retry_history)

    if not caption and not tags_raw:
        raise RuntimeError(f"empty Florence-2 output for {png.name}")

    fields: dict = {}
    if caption:
        fields["description"] = caption
        nm = derive_name_from_caption(caption)
        if nm:
            fields["name"] = nm
        ori = derive_orientation(caption)
        if ori:
            fields["orientation"] = ori
        st = derive_state(caption)
        if st:
            fields["state"] = st
    if tags_raw or caption:
        # Prefer model-emitted tags from prompt_gen_tags (PromptGen finetune)
        # but enrich with content words from the caption so we don't lose
        # detail like adjectives ("rusted", "wooden", "broken").
        existing: list[str] = []
        if tags_raw:
            for raw in re.split(r"[,;\n]", tags_raw):
                norm = normalize_tag(raw)
                if norm and norm not in existing and len(norm) <= 32:
                    existing.append(norm)
        fields["tags"] = derive_tags("", existing, caption=caption)
    fields["classified_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    fields["classified_by"] = MODEL_NAME

    update_sidecar(yaml_path, fields)
    return caption, tags_raw


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default=DEFAULT_SERVER)
    p.add_argument("--force", action="store_true", help="re-classify even if classified_at is set")
    p.add_argument("--limit", type=int, default=0, help="only process the first N stamps (0 = all)")
    p.add_argument("--source", default=None,
                   help="Limit to stamps whose filename starts with this stem")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    client_id = uuid.uuid4().hex
    pngs = sorted(STAMPS_DIR.glob("*.png"))
    if args.source:
        pngs = [p for p in pngs if p.stem.startswith(args.source)]
    if args.limit:
        pngs = pngs[: args.limit]

    done = 0
    skipped = 0
    failed: list[tuple[Path, str]] = []
    for i, png in enumerate(pngs, start=1):
        yaml_path = png.with_suffix(".yaml")
        if not args.force and read_classified_at(yaml_path):
            skipped += 1
            continue
        try:
            caption, tags_raw = classify_one(args.server, png, yaml_path, client_id)
            done += 1
            if args.verbose:
                print(f"[{i}/{len(pngs)}] {png.name}")
                print(f"  caption: {caption[:120]}")
                print(f"  tags:    {tags_raw[:120]}")
            else:
                print(f"[{i}/{len(pngs)}] {png.name}: classified")
        except Exception as e:  # noqa: BLE001 — surface anything to log
            failed.append((png, str(e)))
            print(f"[{i}/{len(pngs)}] {png.name}: FAILED — {e}", file=sys.stderr)

    print(f"classify: done={done} skipped={skipped} failed={len(failed)}")
    if failed and args.verbose:
        for png, err in failed:
            print(f"  {png.name}: {err}", file=sys.stderr)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
