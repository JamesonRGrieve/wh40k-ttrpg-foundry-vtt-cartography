#!/usr/bin/env python3
"""Stage curated game-icons SVGs into _sourcing/incoming/strategic-icons/.
Provenance row per file FIRST (mandatory), then Phase-B md5 novelty:
md5 match in /tmp/corpus_known_md5.txt -> move to rejected-duplicate/
with a sidecar quoting the matched path. Survivors stay staged for
Phase C visual audit.
"""
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SRC = Path("/tmp/game-icons-src")
ROOT = Path(__file__).resolve().parent
INC = ROOT / "incoming" / "strategic-icons"
DUP = ROOT / "rejected-duplicate"
PROV = ROOT / "provenance.tsv"
KNOWN = Path("/tmp/corpus_known_md5.txt")
RAW = "https://raw.githubusercontent.com/game-icons/icons/master/"

INC.mkdir(parents=True, exist_ok=True)
DUP.mkdir(parents=True, exist_ok=True)

known = {}
for ln in KNOWN.read_text().splitlines():
    h, _, p = ln.partition("  ")
    if h:
        known.setdefault(h, p)

have = set()
if PROV.exists():
    for ln in PROV.read_text().splitlines()[1:]:
        c = ln.split("\t")
        if len(c) >= 2:
            have.add(c[1])

sel = [s.strip() for s in Path(sys.argv[1]).read_text().splitlines()
       if s.strip() and not s.startswith("#")]

today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
rows, staged, dup, miss = [], 0, 0, 0
for rel in sel:
    sp = SRC / rel
    if not sp.exists():
        print(f"MISS  {rel}")
        miss += 1
        continue
    dest_name = rel.replace("/", "__")
    if dest_name in have:
        print(f"SKIP  already-sourced {dest_name}")
        continue
    blob = sp.read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    md5 = hashlib.md5(blob).hexdigest()
    # provenance FIRST (every sourced file gets a row)
    rows.append(f"{sha}\t{dest_name}\t{RAW}{rel}\tCC-BY-3.0\t{today}")
    if md5 in known:
        (DUP / dest_name).write_bytes(blob)
        (DUP / (dest_name + ".txt")).write_text(
            "verdict: reject\nreason: duplicate\n"
            f"subject: game-icons {rel}\n"
            f"why: md5 {md5} identical to existing corpus file\n"
            f"matched: {known[md5]}\n"
            "disposition: garbage\n"
            f"reviewed: claude-opus-4-7, {today}\n")
        print(f"DUP   {dest_name}  == {known[md5]}")
        dup += 1
    else:
        (INC / dest_name).write_bytes(blob)
        print(f"STAGE {dest_name}")
        staged += 1

if rows:
    with PROV.open("a") as f:
        f.write("\n".join(rows) + "\n")
print(f"\n== strategic-icons: staged {staged}, md5-dup {dup}, "
      f"missing {miss}, provenance rows {len(rows)} ==")
