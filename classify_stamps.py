#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
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
from pathlib import Path

DEFAULT_SERVER = "http://198.51.100.11:8188"
MODEL_NAME = "microsoft/Florence-2-base"
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
    "destroyed": "destroyed",
    "shattered": "destroyed",
    "wreckage": "destroyed",
    "ruined": "destroyed",
    "damaged": "damaged",
    "broken": "damaged",
    "cracked": "damaged",
    "rusted": "damaged",
    "dented": "damaged",
    "active": "active",
    "lit": "active",
    "glowing": "active",
    "powered": "active",
    "switched on": "active",
    "open": "active",
    "inactive": "inactive",
    "off": "inactive",
    "powered off": "inactive",
    "closed": "inactive",
    "intact": "intact",
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


def upload_image(server: str, png_path: Path) -> str:
    """Upload a PNG to ComfyUI's input directory. Return the saved filename."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{png_path.name}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode()
    )
    parts.append(png_path.read_bytes())
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
        "keep_model_loaded": True,
        "max_new_tokens": 256,
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
        # PreviewAny is an OUTPUT_NODE that captures any input into the
        # /history payload — Florence2Run is not an output node on its own,
        # so without these wrappers ComfyUI rejects the workflow as having
        # no outputs.
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
NOUN_PHRASE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9\- ]{1,40}?)(?:\s+(?:is|are|that|with|on|in|at|near|featuring|made|of|sitting|standing|placed|lying|hanging|covered|painted|surrounded)\b|[.,;])", re.IGNORECASE)


def derive_name_from_caption(caption: str) -> str | None:
    if not caption:
        return None
    s = ARTICLE_RE.sub("", caption.strip())
    m = NOUN_PHRASE_RE.match(s)
    if m:
        phrase = m.group(1).strip().rstrip(",")
    else:
        # Take the first chunk up to the first comma/period.
        phrase = re.split(r"[.,;]", s, maxsplit=1)[0].strip()
        if len(phrase) > 60:
            phrase = " ".join(phrase.split()[:6])
    if not phrase:
        return None
    return phrase[:1].upper() + phrase[1:]


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


def derive_tags(tag_string: str, existing: list[str]) -> list[str]:
    raw = re.split(r"[,;\n]", tag_string or "")
    norm = [normalize_tag(t) for t in raw]
    out: list[str] = list(existing)
    for t in norm:
        if t and t not in out and len(t) <= 32:
            out.append(t)
    return out[:30]


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
    server_filename = upload_image(server, png)
    workflow = build_workflow(server_filename)
    prompt_id = submit_prompt(server, workflow, client_id)
    history = poll_history(server, prompt_id)
    caption, tags_raw = extract_strings(history)
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
    if tags_raw:
        fields["tags"] = derive_tags(tags_raw, [])
    fields["classified_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    fields["classified_by"] = MODEL_NAME

    update_sidecar(yaml_path, fields)
    return caption, tags_raw


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default=DEFAULT_SERVER)
    p.add_argument("--force", action="store_true", help="re-classify even if classified_at is set")
    p.add_argument("--limit", type=int, default=0, help="only process the first N stamps (0 = all)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    client_id = uuid.uuid4().hex
    pngs = sorted(STAMPS_DIR.glob("*.png"))
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
