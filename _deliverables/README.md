# Cartography deliverables — review walkthrough

Open this directory in a file manager (Nautilus, Dolphin, etc.) or
view with `feh -F`/`xdg-open` for full-resolution review. Each
section below describes what to look at and what specific feedback
would help.

---

## 01_symbol_library/ — canonical 40K iconography

Eleven canonical symbols sourced from
<https://github.com/Certseeds/wh40k-icon> (CC-BY-NC-SA 4.0,
compatible with personal/non-commercial campaign use):

| File | Notes |
| --- | --- |
| `aquila.png` | Standard Imperial Aquila. The everyday version. |
| `palatine_aquila.png` | Elaborate downward-winged variant. Reserve for high-honor surfaces. |
| `inquisition_i.png` | Bare I-glyph (per-Inquisitor minimal sigil). |
| `inquisition_rosette.png` | Full rosette — Aquila wings + skull medallion + Ordo Malleus hammer. |
| `mechanicus_cog.png` | Half-cog half-skull Opus Machina. |
| `adeptus_arbites.png` | Skull + raised fist + scales of justice. |
| `adepta_sororitas.png` | Fleur-de-lys (Sisters of Battle). |
| `adeptus_custodes.png` | Aquila wings + central lightning medallion. |
| `astra_militarum.png` | Outstretched wings + central skull (Imperial Guard). |
| `adeptus_ministorum.png` | Ecclesiarchy I-pillar with skull medallion. |
| `adeptus_terra.png` | High Lords' grand sigil. |
| `_smoketest_compose.png` | Three-symbol composite test (Aquila + Rosette + Cog). |

**Feedback I need:**

- Are these the right symbols, or do you want others (Inquisitorial
  Ordo Hereticus / Xenos variants, Imperial Navy, Adeptus
  Astronomica, specific Space Marine chapter heraldry)?
- Are any rasterizations too coarse / aliased? They render at 512px
  and can be re-rasterized at any resolution from `source.svg`.
- Operator-supplied vs. fan-art vs. AI-generated for any specific
  slot? Right now all 11 come from the same fan-art repo.
- Pending slots: `cult_imperialis_flame` and `skull_laurel` have no
  source SVG yet (no direct match in this repo). Drop in a source
  or pick a substitute?

---

## 02_battlemap_floor_only/ — floor-only round 3

Five representative archetypes from the round 3 sweep (10/10
archetypes total render cleanly at seed 42). Pure floor textures
that fill the frame edge-to-edge — walls live on a separate
foreground/walls-only layer. These are the building blocks of
stackable Foundry scenes.

| File | What it is |
| --- | --- |
| `hab.png` | Stained ferrocrete with yellow lumen-pool stains |
| `industrial.png` | Steel plate floor with weld seams + rust patches |
| `lair.png` | Organic biomorphic substrate with green phosphor |
| `garrison.png` | Concrete tile with rust patches |
| `medicae.png` | White ceramic tile, faint stains |

**Feedback I need:**

- Texture density / color saturation right for stamp overlay use?
- Any archetype you'd like re-tuned?
- Missing archetypes? Currently 10 interior + 4 wide-scale.

---

## 03_battlemap_multi_room/ — multi-room hab POC

The pivot you called out ("all single rooms / all square") in
action. Walk these in order:

1. `01_layout.png` — generated layout PNG (1792×1024) from
   `make-floorplan --preset hab-3room-corridor`. Three rooms
   connected by a central horizontal corridor, three doorways.
2. `02_base.png` — Flux + regional conditioning rendered base map
   with hab archetype floor texture (v2 prompt iteration). The
   layout colors drive per-region prompts.
3. `03_walls_foreground.png` — walls-only render, transparent
   background, pixel-aligned with the base. Drop into a Foundry
   scene as the **foreground** tile.
4. `04_composed.png` — preview of base + walls overlaid. This is
   what the operator sees in Foundry once both tiles are placed.

**Feedback I need:**

- Floor texture punchy enough? Round 1 was almost gray-on-gray;
  round 2 (this one) shows visible rust mottling at room edges.
- Wall thickness reasonable? It's 32px on a 1792×1024 canvas.
- Any architectural variants you want for hab specifically (corner
  unit, end-of-row, multi-floor)?

---

## 04_stamp_variants/ — stamp gap-filling

Five files showing a single source stamp (radar console) in five
states — three rotational variants generated geometrically (pure
PIL, no GPU), one condition variant generated via Flux img2img.

| File | Method |
| --- | --- |
| `01_source_radar_console.png` | Original from the Gemini sheet |
| `02_rotated_south.png` | 180° geometric rotation |
| `03_rotated_east.png` | 270° geometric rotation |
| `04_rotated_west.png` | 90° geometric rotation |
| `05_condition_damaged.png` | Flux img2img, denoise=0.55 — same subject, rust streaks, cracked screen |

**Feedback I need:**

- Damaged variant compelling enough? Needs to read at the small
  scale Foundry tokens use (~64-128px on a typical scene).
- Test on a more complex stamp (chair, locker, banner) — different
  subject classes may need different denoise strengths.
- Generative (img2img) rotation deferred — geometric handles
  most cases; do you want me to push on the asymmetric case?

---

## 05_scene_pictures/ — scene picture POC (UPDATED 2026-05-07 v2)

Two-pass integrated render: txt2img scene → composite black silhouette
of canonical at anchor → img2img repaint at low denoise so the
silhouette becomes scene-integrated material per the declared
material hint.

| File | Notes |
| --- | --- |
| `district_4_chapel.png` | 1024×768. Aquila as `brass-relief` at apse_back, Adeptus Ministorum as `carved-stone` at lectern_front. Both integrated into chapel architecture, not glued on. |
| `_intermediate_guide.png` | The pass-1 + black-silhouette composite that fed pass 2. Shows what the integration started from. |

**Feedback I need:**

- Style direction. This is painterly oil-painting / FFG-era 40K RPG
  aesthetic. Want different (photographic-realistic, sketchy,
  cel-shaded)?
- Is the symbol composition placement working — Aquila position,
  size, integration with the lighting?
- Other Solenne locations to render: Hab District 4 establishing
  shot, Section 7 Maintenance Tunnels close-up, Astropathic Relay
  Station interior?

---

## 06_character_portraits/ — character portrait POC (UPDATED 2026-05-07 v2)

Same two-pass integrated path as scene pictures. Inquisitorial
rosette is now embossed-armor-inlay on the chest plate, integrated
into the painting, not pasted on top.

| File | Notes |
| --- | --- |
| `inquisitor_bust.png` | 768×1024 head/shoulders. Inquisitorial Rosette as `armor-inlay` on chest carapace. Rosette now reads as Aquila-wing heraldry on the armor. |
| `inquisitor_bust_token.png` | 512×512 1:1 token cropped from upper portion. Foundry actor-token convention. |
| `_intermediate_guide.png` | The pass-1 + composited black rosette silhouette that fed pass 2. |

**Feedback I need:**

- Style direction. Same painterly oil-painting as scenes; want
  divergent? (Per-class style options possible — Astropath could
  be ethereal, Hive-ganger could be grittier, etc.)
- Token crop framing — face centered? Currently using
  TOKEN_CY_FRAC=0.30 for bust portraits, which puts the face in
  the upper third.
- Symbol placement on the chest — visible but slightly small.
  Adjust default size_label from `medium` (1.0×) to `large` (1.5×)?
- Other classes I have profiles for ready to render: `acolyte`,
  `tech-priest`, `guardsman`, `preacher`, `astropath`,
  `hive-ganger`, `civilian`. Pick a few PCs to render?

---

## 07_layout_presets/ — floor-plan generator output

Five canonical-color layout PNGs from the `make-floorplan`
generator. These are NOT battlemaps — they're the source layouts
that feed the spacecraft regional-conditioning workflow to produce
multi-room battlemaps (see section 03 for one rendered through to
completion).

| File | Footprint |
| --- | --- |
| `hab_3room_corridor.png` | 1792×1024, 3 rooms + central corridor |
| `tunnel_junction.png` | 1536×1536, T-junction with central hub |
| `chapel_nave_with_apse.png` | 1280×1792, long nave + apse |
| `industrial_bay.png` | 2048×1024, large bay + control booth |
| `archive_stacks_grid.png` | 1792×1280, 4×2 vault grid + central spine |

**Feedback I need:**

- Aspect ratios working for your scenes?
- Architectural patterns missing? (Underground catacombs with
  multiple chambers, Mechanicus shrine with inner sanctum, hab
  block with stairwells, ship engineering deck with reactor pit…)
- Each one needs a parent template for symbol-anchor declarations
  (e.g. chapel_nave: `aquila` at apse_back, `adeptus_ministorum`
  at lectern_front). Want me to author these?

---

## 08_multi_deck/ — multi-deck UX helper output

Three files showing the multi-deck variant pattern: one base hull
layout, two deck-variant copies with different architectural
openings.

| File | Notes |
| --- | --- |
| `00_base_hull.png` | The original hand-painted spacecraft layout |
| `01_deck1_ramp_south.png` | Deck variant with rear-ramp opening |
| `02_deck2_windscreen_north.png` | Deck variant with dorsal windscreen |

The outer hull is preserved byte-for-byte across decks; only the
declared openings change. Multi-deck same-footprint stack via the
existing IoU-verified pattern.

**Feedback I need:**

- Is the openings pattern useful? Could add `--opening
  deck3=cargo_doors:east,west` for dual side openings, etc.
- Are there standard deck layouts I should hard-code as presets
  (engineering / bridge / barracks / hangar)?

---

## What's NOT here (still pending)

- Foundry V14 live-scene stackability test — needs operator at
  the Foundry UI. Assets are staged at
  `dh-cartography/battlemaps/hab_3room_*.png`.
- Cult Imperialis flame and skull-laurel canonicals — no source
  SVG located yet.
- ControlNet OpenPose for explicit portrait pose composition.
- IPAdapter face consistency across multiple portraits of the
  same character.
- LoRA training (only escalate if prompt+IPAdapter caps short).

---

## Sources / attribution

- Primary symbol source: <https://github.com/Certseeds/wh40k-icon>
  (CC-BY-NC-SA 4.0).
- Diffusion model: Chroma-Flux (`chroma-unlocked-v35`) on a local
  ComfyUI server at `198.51.100.11:8188`.
- All 40K names + iconography are Games Workshop IP — we operate
  under personal/non-commercial fair use.

---

## How to give feedback

Most efficient: per-section bullet points. "section 06: token crop
too low, want face higher" etc. I'll iterate per-section in the
next session.
