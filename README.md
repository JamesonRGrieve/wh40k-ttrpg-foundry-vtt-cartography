# Cartography asset pipeline

Stamps + battlemaps for the Solenne Dark Heresy 2e campaign,
deploying as a Foundry V14 module at
`/opt/foundry-vtt/data/Data/modules/dh-cartography/`.

## At a glance

| Goal | Tool | Output |
| --- | --- | --- |
| Slice a Gemini grid PNG into transparent stamps | `extract_stamps.py` | `stamps/<stem>_NN.png` |
| Generate per-stamp metadata sidecars | `make_sidecars.py` | `stamps/<stem>_NN.yaml` |
| Caption each stamp via Florence-2 PromptGen v2.0 | `classify_stamps.py` | populates `name`, `description`, `tags`, `orientation`, `state` |
| Cluster visually-similar variants via CLIP-ViT-H | `assign_groups.py` | populates `group_id` |
| Build the Mass Edit preset pack | `build_mass_edit_pack.py` | `dh-cartography/mass-edit-presets.json` |
| Hardlink stamps into the Foundry module dir | `stage_module.py` | `dh-cartography/stamps/*.png` |
| Render top-down battlemaps | `generate_battlemap.py` | `battlemaps/*.png` |
| Pipeline health snapshot | `pipeline_status.py` | console / `--json` |

`deploy.sh cartography` (in the parent vault directory) runs the
build steps and rsyncs the module to the Foundry server. NEVER run
without explicit user authorization.

## Stamp pipeline

```sh
# 1. Extract stamps from new grid PNGs (idempotent on re-run; gutter
#    artifacts auto-rejected via fill-ratio filter).
uv run extract_stamps.py *.png

# 2. Generate sidecars for newly-extracted stamps.
uv run make_sidecars.py

# 3. Classify (GPU; ~1 stamp/min on a 3090). Two-pass internal
#    retry handles small/transparent stamps that empty on the
#    default native-transparent payload.
uv run classify_stamps.py [--source <sheet-stem>]

# 4. Cluster variants by image embedding.
uv run assign_groups.py [--source <sheet-stem>]

# 5. Stage + build the preset pack (idempotent).
uv run stage_module.py
uv run build_mass_edit_pack.py
```

Don't run #3 and #4 concurrently with each other or with battlemap
renders — the 3090 is one queue.

## Battlemap pipeline

```sh
# Top-down empty room — no layout needed; pure txt2img.
uv run generate_battlemap.py interior --style hab --width 1024 --height 1024 \
    --seed 42 --prefix map_block_9_unit_14

# Regional layout (img2img). Two paths:
# (a) Programmatic — emits a canonical-color rectangle.
uv run generate_battlemap.py make-room layouts/proc16_atrium.png \
    --width 1024 --height 1024 --lights 8

# (b) Hand-painted — quantize to canonical colors before rendering.
uv run generate_battlemap.py quantize-layout layouts/my_painting.png \
    --background black

uv run generate_battlemap.py spacecraft --layout layouts/proc16_atrium.png \
    --seed 42 --prefix map_proc16_atrium

# Stackable foreground walls layer.
uv run generate_battlemap.py spacecraft --layout layouts/proc16_atrium.png \
    --seed 42 --prefix map_proc16_atrium_walls --walls-only

# Preview the layered stack.
uv run generate_battlemap.py compose battlemaps/map_proc16_atrium_*.png \
    battlemaps/map_proc16_atrium_walls_*_alpha.png
```

Available `--style` archetypes: `hab`, `tunnel`, `industrial`,
`chapel`, `bar`, `garrison`, `lair`, `medicae`, `archive`,
`mechanicus`. See `docs/campaign-locations.md` for the recommended
archetype per Solenne location.

## Foundry workflow

After `deploy.sh cartography` (run only on user authorization):

1. **Activate the module** in the world's Module Settings.
2. **Open Mass Edit's Preset Browser** (Macros → Preset Browser, or
   the toolbar button added by Baileywiki Mass Edit).
3. **Import the preset pack**: Browser → Import → select
   `modules/dh-cartography/mass-edit-presets.json`.
4. **Drag presets onto the scene** to place them as tiles. Filter
   by tag (e.g. `furniture-chair`, `prop-document`).
5. For runtime variant cycling (state changes via Active Tiles):
   reference `docs/battlemap-workflow.md` for the Image Cycle setup.

For battlemaps:

1. Place the base map as the **scene background image** in Foundry
   scene config.
2. Place the walls-only `*_alpha.png` as the **scene foreground
   image**.
3. Stamps populate the **tile layer** between them.

## Documentation

- `CLAUDE.md` — operator's guide for working in this directory.
  Includes the eleven hard-won gotchas about ComfyUI / Florence-2.
- `docs/battlemap-workflow.md` — running operator's notebook.
  Wins, fails, design rationale for each pipeline decision.
- `docs/campaign-locations.md` — every Solenne campaign location
  mapped to a recommended `generate_battlemap.py` invocation.

## External dependencies

- **ComfyUI** at `http://198.51.100.11:8188` (RTX 3090, V0.18.1)
  — Florence-2-large-PromptGen-v2.0, CLIP-ViT-H, IPAdapter,
  Chroma-unlocked-v35 (Flux derivative).
- **Foundry VTT** at `https://vtt.jamesonrgrieve.ca` (V14 Build 359,
  world `dark-heresy`, system `wh40k-rpg`).
- **Baileywiki Mass Edit** module (`multi-token-edit`) for the
  Preset Browser. **Monks Active Tiles** for runtime variant cycling.
