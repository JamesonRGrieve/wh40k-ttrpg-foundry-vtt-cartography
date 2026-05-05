# Cartography Asset Pipeline — Working Directives

This directory holds raw Gemini-generated stamp-grid images and the tooling
that turns them into individual transparent stamps for use in Foundry VTT
maps. It is a build directory: the inputs are PNG grids, the outputs live
in `stamps/`, and the surrounding repo (`/home/jameson/Documents/dh-campaign/.foundry/`)
is the `wh40k-rpg` Foundry V14 system.

## Pipeline targets

The end-to-end goal is a Foundry V14 cartography library for the Solenne
campaign where each stamp is:

1. Cleanly cut out of its source grid with a transparent background.
2. Tagged with a stable name, description, and category tags.
3. Linked to other stamps that represent the same object in different
   orientations or states (intact / damaged / activated / etc.).
4. Importable as a tile/asset palette inside a Foundry V14-compatible
   mapping plugin (plugin selection still pending — see TODO.md).

## Source image expectations

- Grids are NOT uniformly sized. Cell dimensions can vary within a single
  source image and definitely vary across images.
- Grid lines (gutters) are NOT always contiguous — a stamp can bleed into
  what would otherwise be a separator.
- Gutter color is image-dependent: most images use a near-white or cream
  background, but at least one set uses medium gray, and some dark-toned
  sets use a dark gutter where stamp content is similar in tone to the
  separator. The extraction tool samples the gutter color from the image
  border rather than assuming white.
- Therefore: any extractor that assumes a fixed grid (rows/cols) or a
  fixed gutter color will fail on part of the corpus. The current approach
  is connected-components on a "not-gutter" mask with 4-connectivity for
  stamp components and 8-connectivity for the background hole-detection
  pass. Small interior gutter-colored regions are filled to recover stamp
  pixels that happen to match the gutter color.

## Conventions

- Output files: `stamps/<source-stem>_NN.png`, RGBA, top-to-bottom
  left-to-right ordering with rows clustered by centroid Y. Numbering is
  zero-padded so the directory sorts visually.
- Do NOT rename source PNGs. The Gemini hash-style filenames are the
  canonical identifier; downstream metadata (TODO.md item) joins on
  source stem + index.
- Do NOT delete a source PNG even after it has been processed. Re-runs
  must be reproducible from inputs alone.

## External services in scope

- ComfyUI server: `198.51.100.11` — used (planned) for tagging stamps with
  orientation / damage / activation state via image-classification models.
- Foundry VTT server: see `../../VTT_WIKI.md` (V14 Build 359, system
  `wh40k-rpg`). Cartography assets ultimately deploy into this instance.
- Kanka wiki: see `../../VTT_WIKI.md`. Stamp metadata may eventually be
  cross-referenced from item / location entities in Kanka.

## Hard rules

- Never silently drop a stamp during extraction. If the algorithm cannot
  segment an image cleanly, log it and leave the source file untouched —
  do not "best-effort" produce a half-correct grid that downstream tagging
  will then anchor to.
- Never write image-specific overrides into `extract_stamps.py`. If a
  particular image needs different parameters, surface the tunable as a
  CLI flag or per-image YAML sidecar rather than branching by filename.
- Never deploy stamps into Foundry directly from this directory. The
  parent repo's deploy machinery is authoritative; this directory only
  produces inputs for it.

## Extension points (referenced from TODO.md)

- Per-stamp metadata sidecar (planned): `stamps/<source-stem>_NN.yaml`
  with `name`, `description`, `tags`, `orientation`, `state`, and a
  `group_id` linking variants of the same object.
- ComfyUI workflow JSON for classification will live alongside this file
  once authored, and be invoked from a `classify_stamps.py` driver.
- **Foundry plugin: Baileywiki Mass Edit (`multi-token-edit`).** Selected
  on the basis that it is the only V14-loadable module providing a
  preset/tile browser with folder + tag indexing, drag-to-scene placement,
  and prefab/variant grouping. Manifest declares
  `compatibility: { minimum: 13, verified: 13 }` with no `maximum`, so it
  loads cleanly on V14 Build 359; depends on `lib-wrapper` (already
  installed). Repo: <https://github.com/Aedif/multi-token-edit>.
  - Pair with the already-installed `monks-active-tiles` for state-machine
    texture swaps (Image Cycle action) — covers the orientation/state
    cycling without a custom module.
  - Stamps land inside the Foundry user-data dir under a directory chosen
    at deploy time; the Mass Edit Preset Browser then indexes that folder
    by sub-directory and frontmatter tags.
- ComfyUI workflow JSON for classification will live alongside this file
  once authored, and be invoked from a `classify_stamps.py` driver.
