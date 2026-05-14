#!/usr/bin/env python3
"""Generate LoRA caption .txt sidecars for every image moved into a
`from-james/` subdir of lora-training/. Idempotent: skips any image
that already has a sidecar.

Caption format matches the existing stamps/iconography convention:
    <trigger>, <Title Case Description>, <view>, <state>, <tag>, <tag>, ...

Trigger + view + tag conventions are per-corpus, derived from the
corpus dir name + the image's relative path + filename heuristics.

Run from cartography/:  uv run caption_from_james.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent / "lora-training"
IMG_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".psd", ".webp", ".gif", ".bmp"}

# Filename keyword → (trigger, faction tag) for iconography
IMPERIAL_TRIGGER_MAP = [
    (r"aquila|aquil", "sym_aquila", "imperial aquila"),
    (r"inquis|rosette", "sym_inq_rosette", "inquisitorial rosette"),
    (r"mechan|mechanic|cog|opus", "sym_mech_cog", "mechanicus opus"),
    (r"militarum|astra-mil|astra_mil|guard", "sym_militarum_winged_skull", "astra militarum winged skull"),
    (r"sororita|sister|battle-sister|battle_sister", "sym_sororitas_lys", "adepta sororitas fleur-de-lys"),
    (r"ministor", "sym_ministorum", "adeptus ministorum"),
    (r"administrat", "sym_administratum", "adeptus administratum"),
    (r"arbite", "sym_arbites", "adeptus arbites"),
    (r"telepath|astropath", "sym_telepathica_eye", "adeptus astra telepathica"),
    (r"navy|naval", "sym_imperial_navy", "imperial navy anchor"),
    (r"rogue|trader", "sym_rogue_trader", "rogue trader warrant"),
    (r"deathwatch", "sym_deathwatch", "deathwatch chapter badge"),
    (r"astartes|space.?marine|chapter", "sym_astartes", "adeptus astartes chapter badge"),
    (r"custode", "sym_custodes", "adeptus custodes"),
    (r"silence|null", "sym_sisters_of_silence", "sisters of silence"),
    (r"assassin|officio", "sym_officio_assassinorum", "officio assassinorum"),
    (r"knight|imperial.?knight", "sym_imperial_knights", "imperial knights"),
    (r"terra", "sym_adeptus_terra", "adeptus terra"),
    (r"legion-of-the-damned|damned", "sym_legion_damned", "legion of the damned"),
    (r"raptor", "sym_raptor_imperialis", "raptor imperialis"),
    (r"talon", "sym_talons_emperor", "talons of the emperor"),
    (r"skull|human_imperium", "sym_imperial_skull", "imperial human skull"),
    (r"forge.?world", "sym_forge_world", "mechanicus forge world"),
    (r"solar.?auxil", "sym_solar_auxilia", "solar auxilia"),
]

CHAOS_TRIGGER_MAP = [
    (r"nurgle|plague", "sym_nurgle", "nurgle"),
    (r"khorne", "sym_khorne", "khorne"),
    (r"tzeentch", "sym_tzeentch", "tzeentch"),
    (r"slaanesh", "sym_slaanesh", "slaanesh"),
    (r"chaos.?star|eight.?point", "sym_chaos_star", "eight-pointed chaos star"),
    (r"renegade", "sym_renegade", "renegade chaos warband"),
    (r"traitor", "sym_traitor", "traitor legion"),
    (r"daemon|demon", "sym_daemon", "daemonic icon"),
    (r"corsair", "sym_corsair", "chaos corsair"),
    (r"alpha|word.?bearer|night.?lord|iron.?warrior|world.?eater|emperor.?children|thousand.?son|death.?guard|black.?legion", "sym_chaos_legion", "chaos legion heraldry"),
]

XENOS_TRIGGER_MAP = [
    (r"tyranid|hive.?fleet", "sym_tyranid", "tyranid hive fleet"),
    (r"genestealer|cult", "sym_genestealer", "genestealer cult"),
    (r"eldar|asuryan|craftworld", "sym_eldar", "craftworld eldar"),
    (r"harlequin", "sym_harlequin", "harlequin"),
    (r"drukhari|dark.?eldar", "sym_drukhari", "drukhari dark eldar"),
    (r"tau|t'au|t_au", "sym_tau", "t'au empire"),
    (r"necron", "sym_necron", "necron dynastic"),
    (r"ork", "sym_ork", "ork waaagh"),
    (r"votann|leagues", "sym_votann", "leagues of votann"),
    (r"jokaero", "sym_jokaero", "jokaero"),
    (r"hrud", "sym_hrud", "hrud"),
    (r"blackstone", "sym_blackstone_fortress", "blackstone fortress"),
    (r"ambull", "sym_ambull", "ambull"),
]

SHIP_TRIGGER_MAP = [
    (r"battleship", "ship_battleship", "imperial battleship class"),
    (r"battle.?cruiser", "ship_battle_cruiser", "battle cruiser class"),
    (r"grand.?cruiser", "ship_grand_cruiser", "grand cruiser class"),
    (r"cruiser", "ship_cruiser", "cruiser class"),
    (r"light.?cruiser|escort|frigate", "ship_frigate", "frigate class"),
    (r"destroyer", "ship_destroyer", "destroyer class"),
    (r"raider", "ship_raider", "raider class"),
    (r"transport|carrier", "ship_transport", "transport class"),
    (r"star.?fortress|starfortress|starstation|station|orbital", "ship_station", "void station"),
    (r"clipper", "ship_clipper", "clipper class"),
    (r"bommer|jet|attack.?craft", "ship_attack_craft", "attack craft"),
    (r"basha|karrier|crusha|brusia", "ship_ork_vessel", "ork vessel"),
    (r"gladius", "ship_gladius", "gladius-class frigate"),
    (r"emperor|apocalypse|retribution|victory|oberon", "ship_imperial_capital", "imperial capital ship"),
]

PLANET_TRIGGER_MAP = [
    (r"agri", "planet_agri", "agri-world surface"),
    (r"hive", "planet_hive", "hive world surface"),
    (r"daemon", "planet_daemon", "daemon world surface"),
    (r"forge", "planet_forge", "forge world surface"),
    (r"death", "planet_death", "death world surface"),
    (r"feral", "planet_feral", "feral world surface"),
    (r"feudal", "planet_feudal", "feudal world surface"),
    (r"frontier", "planet_frontier", "frontier world surface"),
    (r"shrine", "planet_shrine", "shrine world surface"),
    (r"penal", "planet_penal", "penal world surface"),
    (r"mining", "planet_mining", "mining world surface"),
    (r"capital", "planet_capital", "capital world surface"),
    (r"ice|frozen", "planet_ice", "ice world surface"),
    (r"rocky|barren", "planet_rocky", "rocky barren world surface"),
    (r"gas.?giant", "planet_gas_giant", "gas giant"),
    (r"moon", "planet_moon", "airless moon surface"),
    (r"unclassified|sample", "planet_unclassified", "unclassified world surface"),
]


def title_case(s: str) -> str:
    return " ".join(w.capitalize() if not w.isupper() else w for w in s.split())


def derive_description(name: str) -> str:
    stem = re.sub(r"\.(png|jpg|jpeg|svg|psd|webp|gif|bmp)$", "", name, flags=re.I)
    # Strip leading "N - " or "NN_" classifier-rank prefixes
    stem = re.sub(r"^\d+\s*[-_.]\s*", "", stem)
    # Strip trailing _NN or _v2 indices
    stem = re.sub(r"[_-]\d{1,3}$", "", stem)
    stem = re.sub(r"[_-]v\d+$", "", stem)
    # Convert separators to spaces
    stem = re.sub(r"[_-]+", " ", stem)
    # Collapse whitespace
    stem = re.sub(r"\s+", " ", stem).strip()
    return title_case(stem)


def match_trigger(filename: str, table) -> tuple[str | None, str | None]:
    lower = filename.lower()
    for pattern, trigger, tag in table:
        if re.search(pattern, lower):
            return trigger, tag
    return None, None


def caption_for(corpus_name: str, rel: Path, fname: str) -> str:
    """Compose caption for a corpus image. Returns the caption string."""
    desc = derive_description(fname)
    parts: list[str] = []
    rel_str = str(rel).lower()

    if corpus_name == "iconography":
        trigger, fac_tag = match_trigger(fname, IMPERIAL_TRIGGER_MAP)
        if not trigger:
            # fall back to folder-based hints
            trigger, fac_tag = match_trigger(rel_str, IMPERIAL_TRIGGER_MAP)
        trigger = trigger or "sym_imperial"
        fac_tag = fac_tag or "imperial heraldry"
        parts = [trigger, desc, "isolated faction heraldry", "vector logo", fac_tag, "white background", "canonical"]
    elif corpus_name == "chaos-iconography":
        trigger, fac_tag = match_trigger(fname, CHAOS_TRIGGER_MAP)
        if not trigger:
            trigger, fac_tag = match_trigger(rel_str, CHAOS_TRIGGER_MAP)
        trigger = trigger or "sym_chaos"
        fac_tag = fac_tag or "chaos heraldry"
        parts = [trigger, desc, "isolated faction heraldry", "vector logo", fac_tag, "ruinous powers"]
    elif corpus_name == "xenos-iconography":
        trigger, fac_tag = match_trigger(fname, XENOS_TRIGGER_MAP)
        if not trigger:
            trigger, fac_tag = match_trigger(rel_str, XENOS_TRIGGER_MAP)
        trigger = trigger or "sym_xenos"
        fac_tag = fac_tag or "xenos heraldry"
        parts = [trigger, desc, "isolated faction heraldry", "vector logo", fac_tag, "xenos"]
    elif corpus_name == "voidship-hulls":
        trigger, ship_tag = match_trigger(fname, SHIP_TRIGGER_MAP)
        trigger = trigger or "ship_vessel"
        ship_tag = ship_tag or "void vessel"
        faction_hint = ""
        if "chaos" in rel_str or "renegade" in rel_str or "traitor" in rel_str:
            faction_hint = "chaos faction"
        elif "ork" in rel_str:
            faction_hint = "ork faction"
        else:
            faction_hint = "imperial faction"
        parts = [trigger, desc, "top-down view", "intact", ship_tag, faction_hint, "void vessel hull", "isolated on dark background"]
    elif corpus_name == "planet-textures":
        trigger, ptag = match_trigger(fname, PLANET_TRIGGER_MAP)
        if not trigger:
            trigger, ptag = match_trigger(rel_str, PLANET_TRIGGER_MAP)
        trigger = trigger or "planet_world"
        ptag = ptag or "planetary surface"
        parts = [trigger, desc, "orbital view", "intact", ptag, "spherical body", "imperial cartography"]
    elif corpus_name == "hive-city":
        view = "cross section" if "spire" in fname.lower() or "section" in fname.lower() else "overhead view"
        parts = ["hive_city", desc, view, "intact", "warhammer 40k hive city", "vertical mega-block", "stacked architecture"]
    elif corpus_name == "scenes":
        scene_tag = "facility interior"
        if "underhive" in rel_str:
            scene_tag = "underhive interior"
            trigger = "scene_underhive"
        elif "darktide" in rel_str:
            scene_tag = "imperial industrial interior"
            trigger = "scene_darktide_ref"
        else:
            trigger = "scene_facility"
        parts = [trigger, desc, "top-down view", "intact", scene_tag, "warhammer 40k", "battlemap reference"]
    elif corpus_name == "stamps":
        category = "prop"
        for cat in ["wall", "stair", "trench", "barrel", "box", "cargo", "door", "crate", "container", "machinery", "console", "furniture", "fixture", "ordnance", "document"]:
            if cat in rel_str or cat in fname.lower():
                category = cat
                break
        parts = ["dh_stamp", desc, "top-down view", "intact", category, "grid-aligned tile", "isolated on transparent background"]
    elif corpus_name == "sector-maps":
        parts = ["sector_map", desc, "starfield view", "imperial sector chart", "void cartography", "named sector"]
    elif corpus_name == "terrain-references":
        terrain_tag = "mountain heightmap" if "mountain" in rel_str or "heigh" in rel_str else "terrain surface"
        parts = ["terrain_ref", desc, "top-down view", terrain_tag, "battlemap terrain", "natural feature"]
    elif corpus_name == "strategic-icons":
        parts = ["icon_strategic", desc, "isolated symbol", "vector strategic map icon", "wargame iconography"]
    else:
        parts = ["dh_asset", desc, "warhammer 40k", "asset reference"]

    # Deduplicate adjacent identical parts and join
    seen = set()
    out = []
    for p in parts:
        if not p:
            continue
        key = p.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return ", ".join(out)


def main():
    if not ROOT.exists():
        print(f"missing {ROOT}", file=sys.stderr)
        return 1
    written = skipped = 0
    for corpus_dir in sorted(ROOT.iterdir()):
        if not corpus_dir.is_dir():
            continue
        fj = corpus_dir / "from-james"
        if not fj.exists():
            continue
        corpus_name = corpus_dir.name
        for img in fj.rglob("*"):
            if not img.is_file():
                continue
            if img.suffix.lower() not in IMG_EXTS:
                continue
            sidecar = img.with_suffix(".txt")
            if sidecar.exists():
                skipped += 1
                continue
            rel = img.relative_to(fj)
            caption = caption_for(corpus_name, rel, img.name)
            sidecar.write_text(caption + "\n", encoding="utf-8")
            written += 1
        print(f"  {corpus_name}: {len(list(fj.rglob('*.txt')))} captions present")
    print(f"\nwrote {written} new sidecars, skipped {skipped} existing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
