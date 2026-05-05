# ADR-001: Variant grouping & state association in Foundry

Status: Accepted (2026-05-05)

## Context

Each stamp has zero or more sibling stamps that depict the same in-fiction
object in a different orientation (north/south/east/west) or state
(intact / damaged / destroyed / active / inactive). The cartography
pipeline must surface these relationships in Foundry V14 so the GM can:

1. Browse and place a specific variant deliberately (a wooden bed,
   *damaged*, facing west).
2. Toggle a placed tile between variants at runtime — e.g. when a chair
   gets knocked over during play, swap to the *destroyed* texture
   without re-placing.

Available tools (already-installed or recommended):

- **Baileywiki Mass Edit** (recommended in CLAUDE.md). Tile presets are
  stored as a flat JSON array; each preset has `name`, `documentName:
  "Tile"`, `img`, `tags[]`, `gridSize`, and a `data[]` array of
  placeable-data entries. Multiple entries in `data[]` can be combined
  with `spawnRandom: true` to spawn one at random.
- **Monk's Active Tiles** (already installed). Supports an `Image Cycle`
  action: a placed tile can be configured with N image paths and a
  trigger (click, macro, hook) advances to the next.

## Decision

**Two complementary mechanisms, one for each use case above.**

### 1. Deliberate variant browsing → one preset per stamp

The Mass Edit preset pack contains **one preset per PNG**. Each preset's
`name` comes from the sidecar's canonical name suffixed with the
orientation/state ("Wooden Bed — intact, north"). `tags` flattens the
sidecar fields to:

- The `category` tags from sidecar (`furniture`, `container`, ...)
- An orientation tag (`facing-north`, `facing-south`, `top-down`, ...)
- A state tag (`state-intact`, `state-damaged`, ...)
- A group tag (`group:<group_id>` — joins variants of one object)

The Preset Browser's tag filter then lets the GM narrow to one group +
one orientation + one state with three clicks.

### 2. Runtime variant cycling → Monk's Active Tiles `Image Cycle`

For each placed tile that represents an object with at least one
state-variant sibling, the deploy step writes a Monk's Active Tiles
configuration onto the tile with:

- `images`: the asset paths of the orientation-matched variants in this
  group (i.e., one image per state, all sharing the same orientation as
  the placed tile).
- `trigger`: `click` (configurable in the world).

Click-to-cycle preserves the spatial intent of the placement (the chair
stays where it stands) while letting state advance during play.

### Why not use Mass Edit's `spawnRandom` for variants

`spawnRandom: true` picks ONE entry from `data[]` at spawn time. That
makes it useful for "place a random crate" prefab-style randomness, NOT
for deliberate variant selection or for runtime state cycling. We
intentionally do not use `spawnRandom` for orientation/state variants.

We DO use it for purely-aesthetic variation when the sidecar grouping
identifies stamps as interchangeable (e.g. four "rubble" stamps that
differ only in pixel arrangement). Those collapse into one preset with
`spawnRandom: true`. The deploy step makes this call based on a
sidecar field we'll add post-classification: `interchangeable: true|false`.

## Consequences

- The preset pack is large (one preset per stamp; ~600+ entries) but
  flat and JSON, so import is one click and load is fast.
- Deploy needs to know which variants share a `group_id` AND share an
  orientation to assemble the Active Tiles `images` list correctly.
  This is straightforward once classification fills `group_id`,
  `orientation`, and `state`.
- Mass Edit and Monk's Active Tiles are required at runtime; both are
  V14-loadable per the research in CLAUDE.md. Removing either degrades
  the experience but does not corrupt placed tiles (Mass Edit only
  affects the browser; Active Tiles configs sit in tile flags and are
  idempotent).
