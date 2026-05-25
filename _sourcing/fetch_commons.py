#!/usr/bin/env python3
"""Phase-A sourcing helper: resolve Wikimedia Commons File: titles to
licensed originals, verify license is in the clean set, download to
_sourcing/incoming/<goal>/, and append a provenance.tsv row per file.

Provenance row: <sha256>\t<dest-filename>\t<source-URL>\t<license>\t<UTC-date>
No row -> ineligible. License gate is strict; anything not clearly
PD/CC0/CC-BY(-SA) is skipped with a printed reason (never downloaded).
"""
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "solenne-cartography-corpus/1.0 (CC0/PD reference sourcing; contact: campaign steward)"

# Attribution-class / public-domain licenses we accept. Match is
# case-insensitive substring against extmetadata LicenseShortName.
ACCEPT = [
    "public domain", "pd-", "cc0", "no restrictions", "public domain mark",
    "cc by 4.0", "cc by-sa 4.0", "cc by 3.0", "cc by-sa 3.0",
    "cc by 2.0", "cc by-sa 2.0", "cc by 2.5", "cc by-sa 2.5",
    "cc by-sa 1.0", "cc by 1.0",
]
MIN_EDGE = 600  # pre-download gate; manifest threshold is 512, keep headroom


def _open(url, timeout):
    """GET with exponential backoff on HTTP 429/503."""
    delay = 5
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 5:
                print(f"  ...{e.code}; backoff {delay}s")
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            raise


def api_get(params):
    qs = urllib.parse.urlencode(params)
    with _open(f"{API}?{qs}", 30) as r:
        return json.load(r)


def safe_name(title, mime):
    stem = re.sub(r"^File:", "", title)
    stem = re.sub(r"\.(jpe?g|png|gif|svg|tiff?)$", "", stem, flags=re.I)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")[:90]
    ext = {"image/jpeg": ".jpg", "image/png": ".png",
            "image/gif": ".gif", "image/tiff": ".tif"}.get(mime, ".img")
    return stem + ext


def main(goal, titles_file):
    root = Path(__file__).resolve().parent
    dest_dir = root / "incoming" / goal
    dest_dir.mkdir(parents=True, exist_ok=True)
    prov = root / "provenance.tsv"
    titles = [t.strip() for t in Path(titles_file).read_text().splitlines()
              if t.strip() and not t.startswith("#")]

    have = set()
    if prov.exists():
        for ln in prov.read_text().splitlines()[1:]:
            c = ln.split("\t")
            if len(c) >= 2:
                have.add(c[1])

    ok = skip = 0
    rows = []
    for title in titles:
        if not title.startswith("File:"):
            title = "File:" + title
        try:
            d = api_get({"action": "query", "format": "json",
                         "prop": "imageinfo",
                         "iiprop": "url|size|mime|extmetadata",
                         "titles": title})
            page = list(d["query"]["pages"].values())[0]
            if "imageinfo" not in page:
                print(f"SKIP  no-such-file       {title}")
                skip += 1
                continue
            ii = page["imageinfo"][0]
            em = ii.get("extmetadata", {})
            lic = (em.get("LicenseShortName", {}).get("value")
                   or em.get("UsageTerms", {}).get("value") or "").strip()
            lic_l = lic.lower()
            w, h = ii.get("width", 0), ii.get("height", 0)
            mime = ii.get("mime", "")
            if not any(a in lic_l for a in ACCEPT):
                print(f"SKIP  license[{lic[:28]}] {title}")
                skip += 1
                continue
            if min(w, h) < MIN_EDGE:
                print(f"SKIP  small[{w}x{h}]        {title}")
                skip += 1
                continue
            if mime not in ("image/jpeg", "image/png"):
                print(f"SKIP  mime[{mime}]          {title}")
                skip += 1
                continue
            dest_name = safe_name(title, mime)
            if dest_name in have:
                print(f"SKIP  already-sourced     {dest_name}")
                skip += 1
                continue
            url = ii["url"].split("?")[0]
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            sha = hashlib.sha256(blob).hexdigest()
            (dest_dir / dest_name).write_bytes(blob)
            page_url = f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title)}"
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            rows.append(f"{sha}\t{dest_name}\t{page_url}\t{lic}\t{today}")
            print(f"OK    {w}x{h} {lic[:18]:18} -> {dest_name}")
            ok += 1
            time.sleep(1.0)  # throttle
        except Exception as e:
            print(f"ERR   {title}: {e}")
            skip += 1
    if rows:
        with prov.open("a") as f:
            f.write("\n".join(rows) + "\n")
    print(f"\n== {goal}: {ok} downloaded, {skip} skipped, "
          f"{len(rows)} provenance rows appended ==")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
