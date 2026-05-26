# Campaign locations → battlemap recipe

Mapping each Solenne campaign location to a recommended
`generate_battlemap.py` invocation. This is a starting recipe per
location — adjust prompts, dimensions, and seeds to taste. The
location names match wiki links in `Campaign Home.md`.

## How to use

For most locations:

```sh
uv run generate_battlemap.py interior --style <archetype> \
    --width <px> --height <px> --seed <n> --prefix map_<location_slug>
```

For locations with regional structure (multiple distinct surfaces —
walls + floor + ramps + windscreen):

```sh
# Build a layout PNG via make-room (or paint one in Krita / GIMP).
uv run generate_battlemap.py make-room layouts/<slug>.png --width 1024 --height 1024
# Optional: quantize a hand-painted layout
uv run generate_battlemap.py quantize-layout layouts/<slug>.png --background black
# Render the full base map
uv run generate_battlemap.py spacecraft --layout layouts/<slug>.png --seed <n> --prefix map_<slug>
# Render the walls-only foreground layer
uv run generate_battlemap.py spacecraft --layout layouts/<slug>.png --seed <n> --prefix map_<slug>_walls --walls-only
```

Foundry V14 scene config:
- **Background image**: the full base map (`map_<slug>_*.png`).
- **Foreground image**: the walls-only output (`map_<slug>_walls_*_alpha.png`).

Then drop stamps from the Mass Edit Preset Browser onto the tile
layer in between.

## Solenne Minoris (moon — investigation site)

### Hab District 4

| Location | Archetype | Notes |
| --- | --- | --- |
| Hab-Transit Lodge (hostel) | `hab` | Small rooms; consider 768x1024 portrait orientation. |
| Block 9 Unit 14 (Edric residence) | `hab` | Slightly nicer than transit lodge — faded carpet stamp, more decor. |
| Administratum District Office | `garrison` | Closer to imperial bureaucracy — substitute regimental banners with Administratum seals via prompt override. |
| Hab District 4 Medicae Post | `medicae` | Sterile white-tile examination room. |
| District 4 Chapel (Garrick Varo's chapel) | `chapel` | Default chapel archetype is sized for hive ministorum chapels. |

### Hab District 9 (anomaly cluster)

| Location | Archetype | Notes |
| --- | --- | --- |
| Hab District 9 Scholam | `hab` (modified) | Add "rows of empty desks" via prompt or render bare and stamp desks. |
| Scholam Undertunnels | `tunnel` | Long aspect ratio recommended (1024x512 or 2048x768). |

### Ore Processing District

| Location | Archetype | Notes |
| --- | --- | --- |
| Ore Processor 12 | `industrial` | Large square rooms, 1536x1536 or larger. |
| Mechanicus Outpost | `mechanicus` | Brass piping, red ritual lumens, Mechanicus runes. |
| The Lair (genestealer site) | `lair` | Biomorphic organic chamber, phosphorescent bioluminescence. |

### PDF Garrison

| Location | Archetype | Notes |
| --- | --- | --- |
| PDF Garrison (Kael Edric's base) | `garrison` | Default fits well. |

### Transit Hub

| Location | Archetype | Notes |
| --- | --- | --- |
| Space Port (docking berths) | `industrial` | Large rectangular bays, 2048x1024. |
| Vigil Ledger (Osric's ship) | spacecraft workflow | Layout: paint cockpit + cargo hold + corridors with the canonical region colors. |
| The Errant Vector (acolyte transport) | spacecraft workflow | Same. |
| The Sump (bar) | `bar` | Default fits. |
| Keller's Provisions / Griffe Goods | `hab` (modified) | Add "shelving, merchandise bins" via prompt — but renders bare so user stamps the goods themselves. |
| Astropathic Relay Station | `industrial` (modified) | Add "psychic null cage, choir podiums, brass communication arrays". |

## Solenne Majoris (planet — hive world)

| Location | Archetype | Notes |
| --- | --- | --- |
| Lower Hive — Processional 16 | `hab` or `tunnel` | Wide open avenue between towering hab spires; long aspect ratio. |
| Sub-Sector Munitorum Archive | `archive` | Empty record-shelf alcoves, brass lumens, parchment palette. |
| Majoris Transit Authority | `industrial` | Wide concourse, 2048x1024. |

## Tips for the GM

1. **Match aspect ratio to spatial use.** Long corridors render
   better at 2:1 than at 1:1. The `interior` mode accepts
   `--width` and `--height` independently.
2. **Lock the seed for series renders.** When you generate
   variants of the same location, fix `--seed` so re-renders
   produce stylistically-similar output.
3. **Layer outputs in Foundry.** Use the walls-only layer as the
   foreground for "elevated walkway" or "second floor" effects;
   the base map as the background.
4. **Stamp population is separate.** These archetypes ALL render
   bare maps with no props; populate via Mass Edit's Preset
   Browser after placing the scene.
5. **For locations not in this table**, pick the closest archetype
   and override the t5xxl prompt directly with `--t5xxl`.

## Future archetypes

Implemented this session: `lair`, `medicae`, `archive`, `mechanicus`.
Still potentially useful but not yet implemented:

- `cabaret` — higher-class hive entertainment venue (smoky, plush
  fabric, low warm lighting).
- `voidship-bridge` — Imperial Navy capital ship command bridge
  (much grander than the current spacecraft workflow's interior).
- `xenos-tomb` — Necron tomb-world architecture (precision-cut
  geometric stone, green-glow phosphor).

Add these by extending `INTERIOR_STYLES` and `INTERIOR_STYLE_TAGS`
in `generate_battlemap.py`.
