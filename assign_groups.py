#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "Pillow",
#   "torch",
# ]
# ///
"""
Assign `group_id` to each stamp's sidecar by joining variants of the
same in-fiction object (different rotations, damage states, etc.).

Two-phase algorithm:

  Phase 1 — caption-name clustering (#1)
    Normalize the sidecar `name` field (strip articles, parentheticals,
    state/orientation words, lowercase) and seed initial clusters by
    exact normalized-name match. Stamps without a classified name end
    up in singleton clusters keyed by file id.

  Phase 2 — CLIP-vision embedding refinement (#2)
    For each stamp, submit a ComfyUI workflow that produces an IPAdapter
    image embedding (CLIPVisionLoader → CLIPVisionEncode →
    IPAdapterEncoder → IPAdapterSaveEmbeds) and fetch the resulting
    safetensors file. Use cosine similarity to:
      - SPLIT  an initial cluster when intra-cluster pair similarity drops
        below SPLIT_THRESHOLD (the captions matched but the images don't).
      - MERGE  two initial clusters when their best cross-pair similarity
        exceeds MERGE_THRESHOLD (the captions diverged but the images
        clearly depict the same object).
    Embeddings are cached to `embeddings/<stamp>.safetensors` so
    re-runs are incremental.

Final group_id is `uuid5(NAMESPACE_DH_CARTOGRAPHY, canonical_name + ':' + sorted_member_hash)`,
deterministic across runs as long as the cluster membership is stable.

Usage:
    uv run assign_groups.py                     # incremental, full set
    uv run assign_groups.py --source <stem>     # one source-grid sheet only
    uv run assign_groups.py --skip-embeddings   # phase 1 only (caption clustering)
    uv run assign_groups.py --force-embeddings  # re-fetch embeddings even if cached
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from pathlib import Path

from io import BytesIO

import numpy as np
from PIL import Image


def square_png_bytes(png_path: Path) -> bytes:
    """Pad PNG to square canvas (transparent background). Mirrors classify_stamps."""
    with Image.open(png_path) as im:
        rgba = im.convert("RGBA")
        w, h = rgba.size
        if w == h:
            buf = BytesIO()
            rgba.save(buf, format="PNG")
            return buf.getvalue()
        side = max(w, h)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(rgba, ((side - w) // 2, (side - h) // 2), rgba)
        buf = BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()

DEFAULT_SERVER = "http://198.51.100.11:8188"
HERE = Path(__file__).resolve().parent
STAMPS_DIR = HERE / "stamps"
EMBED_CACHE = HERE / "embeddings"

CLIP_VISION_MODEL = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
IPADAPTER_MODEL = "ip-adapter-plus_sdxl_vit-h.safetensors"
SUBFOLDER = "dh_classify"  # ComfyUI input/ subfolder for our uploaded stamps
SAVE_PREFIX = "dh_embeds"  # ComfyUI output/ prefix for saved .safetensors

POLL_INTERVAL_S = 1.0
POLL_TIMEOUT_S = 180

SPLIT_THRESHOLD = 0.78  # below this, captioned-same images get split
# MERGE uses MEDIAN cross-pair similarity (was BEST). Best-pair chained
# unrelated clusters into superclusters of 100+ members because a
# single coincidentally-similar pair triggered a merge. Median forces
# the bulk of the clusters to be similar — if a 99-stamp candidate
# cluster only has 5 stamps similar to a target cluster, the median
# stays below threshold and the merge doesn't happen.
MERGE_THRESHOLD = 0.92

# Stable namespace for deterministic group_id generation. Any fixed UUID
# works; the value is opaque to consumers — they only need it to remain
# constant across runs so a given (canonical_name, member_set) always
# produces the same group_id.
GROUP_NAMESPACE = uuid.UUID("c0a70007-0000-4000-8000-000000000000")

# --- Sidecar IO (line-oriented, preserves comments) -----------------------------

YAML_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)(\s*#.*)?$")


def read_field(lines: list[str], key: str) -> str | None:
    for line in lines:
        m = YAML_LINE_RE.match(line.rstrip("\n"))
        if m and m.group(1) == key:
            v = m.group(2).strip()
            if v == "" or v.lower() == "null":
                return None
            return v.strip('"').strip("'")
    return None


def write_field(lines: list[str], key: str, value: str | None) -> list[str]:
    rendered = "null" if value is None else value
    if any(c in (rendered or "") for c in ":#'\"") or (rendered and rendered.strip() != rendered):
        rendered = '"' + (value or "").replace('\\', '\\\\').replace('"', '\\"') + '"'
    out: list[str] = []
    replaced = False
    for line in lines:
        m = YAML_LINE_RE.match(line.rstrip("\n"))
        if m and m.group(1) == key:
            comment = m.group(3) or ""
            eol = "\n" if line.endswith("\n") else ""
            out.append(f"{key}: {rendered}{comment}{eol}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}: {rendered}\n")
    return out


# --- Phase 1: caption-name normalization ----------------------------------------

# Strip these words/phrases from the canonical name.
STOPWORDS = {
    "intact", "damaged", "destroyed", "active", "inactive", "broken",
    "ruined", "cracked", "rusted", "shattered", "wreckage", "lit", "off",
    "powered", "powered-off", "open", "closed", "north", "south", "east",
    "west", "left", "right", "front", "back", "side", "top", "down",
    "topdown", "topdown-view", "isometric", "oblique", "the", "a", "an",
    "of", "with", "and",
}

ARTICLE_RE = re.compile(r"^(an?\s+|the\s+|some\s+|several\s+)", re.IGNORECASE)
PAREN_RE = re.compile(r"\(.*?\)|\[.*?\]")
DASH_SEP_RE = re.compile(r"\s*[—–]+\s*")
NON_WORD_RE = re.compile(r"[^a-z0-9 ]+")


def canonical_name(raw_name: str | None) -> str:
    if not raw_name:
        return ""
    s = raw_name.strip()
    s = PAREN_RE.sub("", s)
    s = DASH_SEP_RE.split(s, maxsplit=1)[0]  # drop variant suffix after em-dash
    s = ARTICLE_RE.sub("", s)
    s = NON_WORD_RE.sub(" ", s.lower())
    tokens = [t for t in s.split() if t and t not in STOPWORDS]
    return " ".join(tokens)


# --- ComfyUI HTTP helpers -------------------------------------------------------


def _request(server: str, path: str, *, data: bytes | None = None, headers: dict | None = None,
             method: str | None = None, timeout: float = 30) -> bytes:
    url = f"{server.rstrip('/')}{path}"
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} from {path}: {body[:600]}") from None


def upload_image(server: str, png_path: Path) -> str:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{png_path.name}\"\r\nContent-Type: image/png\r\n\r\n".encode()
    )
    parts.append(square_png_bytes(png_path))
    parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\n{SUBFOLDER}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode())
    parts.append(f"--{boundary}--\r\n".encode())
    raw = _request(server, "/upload/image", data=b"".join(parts),
                   headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                   method="POST", timeout=60)
    return json.loads(raw).get("name", png_path.name)


def submit_prompt(server: str, workflow: dict, client_id: str) -> str:
    payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode()
    raw = _request(server, "/prompt", data=payload,
                   headers={"Content-Type": "application/json"}, method="POST", timeout=30)
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
        entry = hist.get(prompt_id) if isinstance(hist, dict) else None
        if entry and entry.get("status", {}).get("completed"):
            return entry
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"prompt {prompt_id} did not complete in {timeout}s")


def fetch_output_file(server: str, filename: str, subfolder: str = "") -> bytes:
    qs = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
    return _request(server, f"/view?{qs}", timeout=30)


# --- Phase 2: ComfyUI embedding workflow ---------------------------------------


def build_embed_workflow(server_filename: str, prefix: str) -> dict:
    image_ref = f"{SUBFOLDER}/{server_filename}" if SUBFOLDER else server_filename
    return {
        "load_image": {
            "class_type": "LoadImage",
            "inputs": {"image": image_ref, "upload": "image"},
        },
        "clip_vision": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": CLIP_VISION_MODEL},
        },
        "clip_vision_encode": {
            "class_type": "CLIPVisionEncode",
            "inputs": {
                "clip_vision": ["clip_vision", 0],
                "image": ["load_image", 0],
                "crop": "center",
            },
        },
        "ipadapter_model": {
            "class_type": "IPAdapterModelLoader",
            "inputs": {"ipadapter_file": IPADAPTER_MODEL},
        },
        "ipadapter_encoder": {
            "class_type": "IPAdapterEncoder",
            "inputs": {
                "ipadapter": ["ipadapter_model", 0],
                "image": ["load_image", 0],
                "weight": 1.0,
                "clip_vision": ["clip_vision", 0],
            },
        },
        "save_embeds": {
            "class_type": "IPAdapterSaveEmbeds",
            "inputs": {
                "embeds": ["ipadapter_encoder", 0],  # pos_embed
                "filename_prefix": prefix,
            },
        },
    }


def fetch_embedding(server: str, png: Path, client_id: str, force: bool = False) -> np.ndarray:
    """Get a 1-D embedding vector for one stamp.

    On-disk cache layout (in `EMBED_CACHE/`):
        - <stem>.npy        — final 1-D float32 vector (cheap to load)
        - <stem>.ipadpt     — raw torch.save() blob from ComfyUI (kept for audit)

    Fast path: read .npy and return. Slow path: fetch .ipadpt from ComfyUI,
    convert via torch (CPU), mean-pool over the token axis, write .npy.
    `torch` is imported lazily so the import cost is only paid the first
    time a vector needs computing.
    """
    npy = EMBED_CACHE / f"{png.stem}.npy"
    if npy.exists() and not force:
        return np.load(npy)

    EMBED_CACHE.mkdir(parents=True, exist_ok=True)
    raw = EMBED_CACHE / f"{png.stem}.ipadpt"
    if not raw.exists() or force:
        server_filename = upload_image(server, png)
        prefix = f"{SAVE_PREFIX}_{png.stem}"
        wf = build_embed_workflow(server_filename, prefix)
        pid = submit_prompt(server, wf, client_id)
        # IPAdapterSaveEmbeds doesn't surface its filename via /history.outputs;
        # we just have to wait for completion and then fetch the predicted
        # filename. The counter is per-prefix and we use a unique prefix per
        # stamp, so it's always 00001 on first save.
        poll_history(server, pid, timeout=POLL_TIMEOUT_S)
        predicted = f"{prefix}_00001.ipadpt"
        blob = fetch_output_file(server, predicted, "")
        if not blob:
            raise RuntimeError(f"empty embed file fetched for {png.name} ({predicted})")
        raw.write_bytes(blob)

    vec = ipadpt_to_vector(raw)
    np.save(npy, vec)
    return vec


def ipadpt_to_vector(path: Path) -> np.ndarray:
    """Convert a saved IPAdapter .ipadpt (torch.save tensor) → 1-D float32 numpy.

    The IPAdapterSaveEmbeds output for a CLIP-ViT-H feed is a tensor of shape
    (1, 257, 1280) — 257 vision tokens × 1280 dims. Mean-pool over the token
    axis to get a single 1280-d image embedding suitable for cosine sim.
    """
    import torch  # heavy; keep lazy
    t = torch.load(path, map_location="cpu", weights_only=False)
    if hasattr(t, "detach"):
        t = t.detach()
    arr = np.asarray(t.float().cpu().numpy() if hasattr(t, "cpu") else t, dtype=np.float32)
    while arr.ndim > 2:
        arr = arr.mean(axis=0) if arr.shape[0] == 1 else arr.mean(axis=1)
    if arr.ndim == 2:
        arr = arr.mean(axis=0)
    return arr.astype(np.float32, copy=False)


# --- Clustering -----------------------------------------------------------------


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def refine_clusters(
    name_clusters: dict[str, list[int]],
    embeddings: dict[int, np.ndarray],
) -> list[set[int]]:
    """Take name-keyed clusters and refine via embedding similarity.

    Step A — split: within each name-cluster, build a graph where edge(i,j) exists
        iff cosine(emb_i, emb_j) >= SPLIT_THRESHOLD. Connected components become
        the within-name clusters.
    Step B — merge: across all post-split clusters, merge any two whose best
        cross-pair similarity exceeds MERGE_THRESHOLD.
    """
    all_indices: list[int] = sorted({i for members in name_clusters.values() for i in members})
    if not all_indices:
        return []

    # Step A — within-name split.
    post_split: list[set[int]] = []
    for members in name_clusters.values():
        members = [m for m in members if m in embeddings]
        if not members:
            continue
        if len(members) == 1:
            post_split.append({members[0]})
            continue
        idx_map = {m: k for k, m in enumerate(members)}
        uf = UnionFind(len(members))
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                sim = cosine(embeddings[members[i]], embeddings[members[j]])
                if sim >= SPLIT_THRESHOLD:
                    uf.union(i, j)
        groups: dict[int, set[int]] = defaultdict(set)
        for m in members:
            groups[uf.find(idx_map[m])].add(m)
        post_split.extend(groups.values())

    # Step B — cross-cluster merge using MEDIAN cross-pair similarity.
    # Best-pair similarity (the previous heuristic) chained unrelated
    # clusters: a single coincidentally-similar pair would trigger a
    # merge, snowballing into 100+ member superclusters. Median requires
    # the bulk of the cross-pair distribution to exceed the threshold,
    # not just one outlier.
    if len(post_split) < 2:
        return post_split
    n = len(post_split)
    uf = UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            sims: list[float] = []
            for a in post_split[i]:
                if a not in embeddings:
                    continue
                for b in post_split[j]:
                    if b not in embeddings:
                        continue
                    sims.append(cosine(embeddings[a], embeddings[b]))
            if not sims:
                continue
            sims.sort()
            median = sims[len(sims) // 2]
            if median >= MERGE_THRESHOLD:
                uf.union(i, j)
    final: dict[int, set[int]] = defaultdict(set)
    for i in range(n):
        final[uf.find(i)].update(post_split[i])
    return list(final.values())


# --- Driver ---------------------------------------------------------------------


def stamp_index(stamps: list[Path]) -> tuple[dict[int, Path], dict[Path, int]]:
    by_id: dict[int, Path] = {i: p for i, p in enumerate(stamps)}
    by_path: dict[Path, int] = {p: i for i, p in by_id.items()}
    return by_id, by_path


def cluster_id_for(canonical: str, members: list[Path]) -> str:
    member_hash = hashlib.sha1(
        ("|".join(sorted(p.name for p in members))).encode()
    ).hexdigest()[:16]
    return str(uuid.uuid5(GROUP_NAMESPACE, f"{canonical}:{member_hash}"))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default=DEFAULT_SERVER)
    p.add_argument("--source", default=None,
                   help="Limit to stamps whose source-grid stem starts with this string")
    p.add_argument("--skip-embeddings", action="store_true",
                   help="Skip phase 2; assign groups from caption-name only")
    p.add_argument("--force-embeddings", action="store_true",
                   help="Re-fetch embeddings even if cached locally")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    stamps_all = sorted(STAMPS_DIR.glob("*.png"))
    if args.source:
        stamps_all = [p for p in stamps_all if p.stem.startswith(args.source)]
    if not stamps_all:
        print(f"no stamps to process (filter: {args.source!r})", file=sys.stderr)
        return 1

    by_id, by_path = stamp_index(stamps_all)

    # Phase 1.
    name_clusters: dict[str, list[int]] = defaultdict(list)
    fallbacks: list[int] = []
    for idx, png in by_id.items():
        sidecar = png.with_suffix(".yaml")
        if not sidecar.exists():
            fallbacks.append(idx)
            continue
        lines = sidecar.read_text().splitlines(keepends=True)
        canon = canonical_name(read_field(lines, "name"))
        if canon:
            name_clusters[canon].append(idx)
        else:
            fallbacks.append(idx)
    for idx in fallbacks:
        # Each unclassified stamp gets its own keyed cluster so it doesn't
        # silently merge into another bucket.
        name_clusters[f"__unclassified:{by_id[idx].stem}"] = [idx]

    print(f"phase 1: {len(stamps_all)} stamps → {len(name_clusters)} name-clusters "
          f"({len(fallbacks)} unclassified)")

    embeddings: dict[int, np.ndarray] = {}
    if args.skip_embeddings:
        print("phase 2: skipped (--skip-embeddings)")
        # Each name-cluster becomes a final cluster as-is.
        clusters = [set(members) for members in name_clusters.values()]
    else:
        client_id = uuid.uuid4().hex
        EMBED_CACHE.mkdir(parents=True, exist_ok=True)
        for idx, png in by_id.items():
            try:
                emb = fetch_embedding(args.server, png, client_id, force=args.force_embeddings)
                embeddings[idx] = emb
                if args.verbose:
                    print(f"  emb[{idx+1}/{len(stamps_all)}] {png.name}: dim={emb.shape}")
                else:
                    print(f"  emb {idx+1}/{len(stamps_all)} {png.name}")
            except Exception as e:  # noqa: BLE001
                print(f"  emb FAILED {png.name}: {e}", file=sys.stderr)

        if not embeddings:
            print("no embeddings retrieved; falling back to phase-1 only", file=sys.stderr)
            clusters = [set(members) for members in name_clusters.values()]
        else:
            clusters = refine_clusters(name_clusters, embeddings)
            print(f"phase 2: refined to {len(clusters)} clusters")

    # Build canonical name per cluster (mode of member names) and assign UUIDs.
    cluster_assignments: dict[int, str] = {}
    for cluster in clusters:
        members = sorted([by_id[i] for i in cluster], key=lambda p: p.name)
        canons: dict[str, int] = defaultdict(int)
        for png in members:
            sidecar = png.with_suffix(".yaml")
            if sidecar.exists():
                canon = canonical_name(read_field(sidecar.read_text().splitlines(keepends=True), "name"))
                if canon:
                    canons[canon] += 1
        canonical = max(canons.items(), key=lambda kv: kv[1])[0] if canons else members[0].stem
        gid = cluster_id_for(canonical, members)
        for png in members:
            cluster_assignments[by_path[png]] = gid

    # Write group_id back to sidecars.
    written = 0
    for idx, gid in cluster_assignments.items():
        sidecar = by_id[idx].with_suffix(".yaml")
        if not sidecar.exists():
            continue
        lines = sidecar.read_text().splitlines(keepends=True)
        new_lines = write_field(lines, "group_id", gid)
        sidecar.write_text("".join(new_lines))
        written += 1

    print(f"wrote group_id to {written} sidecars across {len(clusters)} groups")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
