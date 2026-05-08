# Architectural layouts — Stage 2 LoRA

Trigger: `dh_layout`. Stage 2 of the two-LoRA voidship pipeline. This
LoRA learns top-down architectural composition (rooms, corridors,
doorways) generalized over an arbitrary boundary. **It is NOT
ship-specific** — the same LoRA serves ship deck plans, hab
apartments, manufactorum bays, chapels, archives, and (with
appropriate boundaries) district maps.

## Architecture

At inference:
1. Hull LoRA renders an empty boundary (ship hull, hab outline,
   chapel cruciform, district mask, etc.) — see
   `../voidship-hulls/`.
2. The empty boundary is passed as image conditioning to the
   layout LoRA along with a layout description in zone grammar.
3. Output: the boundary with rooms / corridors / doorways drawn in.

Multi-deck stacking works because the boundary stays the same
across decks; only the layout caption changes.

## Zone grammar

Every layout is described as a mapping from named zones to room
descriptors. Zones are positioned with the boundary oriented so the
"main axis" runs LEFT to RIGHT:

```
┌──────────┬───────┬───────┬───────┬──────────┐
│ prow_p   │ fwd_p │ mid_p │ aft_p │ stern_p  │     ← port lane (top)
│ prow_c   │ fwd_c │ mid_c │ aft_c │ stern_c  │     ← centerline
│ prow_s   │ fwd_s │ mid_s │ aft_s │ stern_s  │     ← starboard lane (bottom)
└──────────┴───────┴───────┴───────┴──────────┘
  bow                                    stern
```

15 zone cells (5 lengthwise sections × 3 lateral lanes), plus
full-width shortcuts: `prow_full`, `forward_full`, `mid_full`,
`aft_full`, `stern_full` (= the entire section spans the full beam
as one room).

Zones carry NO semantic role by default. The prow on a bridge deck
might be the bridge; on an engineering deck, forward fuel handling;
on a cargo deck, secured ordnance lockers. Same for every other
zone. The zone is JUST a position.

For non-ship boundaries the same grid applies — the long axis of
the boundary is the prow→stern direction.

## Multi-deck pattern

To layer Deck 1 (bridge) and Deck 2 (engineering) on the same hull:

```yaml
- folder: map-frigate-escort
  archetypes:
    - id: deck_1_command
      name: "Deck 1 — Command Deck"
      zones:
        prow_center: "command bridge — sunken pit with five console stations..."
        # ... other zones
      egress: "rear personnel airlock at the stern centerline..."

    - id: deck_2_engineering
      name: "Deck 2 — Engineering Deck"
      zones:
        prow_center: "forward damage control center"
        # ... different room contents at the same zone coordinates
      egress: "no external egress on this deck — internal stairs to deck 1"
```

The hull is supplied at inference by the hull LoRA. Both decks
register on the same Foundry tile bbox.

## Caption format

```
dh_layout, <class_name>, <archetype.id> (<archetype.name>), zones: <zone_summary>, hull state: <state>, <lighting>, top-down architectural composition
```

The zone_summary is a compact one-line listing of which zones are
present (e.g., `"prow_center bridge | mid_port broadside | mid_starboard broadside | stern engineering"`).

## Hard rules

- **Lateral broadside guns, NOT forward pursuit.** Same rule as the
  hull LoRA — broadside batteries point outward from port and
  starboard hull flanks, never forward.
- **EXACTLY one egress per archetype.** No additional hatches,
  airlocks, observation ports, or external openings. The single
  egress is named and positioned in the `egress:` field.
- **Empty interior architecture only.** No furniture, no crates, no
  consoles, no bunks, no equipment, no debris, no NPCs. The empty
  rooms are filled later via Foundry's stamp/tile layer.
- **Append-only manifests.** Output filenames embed sequential
  variant indices. NEVER reorder; append to the END.
- **Zones carry no semantic role.** Don't call a zone "the bridge"
  outside of an archetype that puts a bridge there. The grid is
  spatial, not semantic.

## Status

- v1 manifest: prose blob archetypes (Stage 0). Generated 20-image
  corpus at $0.80. Retained as supplemental data.
- v2 manifest: zone-grammar archetypes (current). 17 archetypes
  across 6 ship classes. Smoke validated for class differentiation
  and broadside compliance.

## Files

```
voidship-layouts/
├── README.md             ← this file
├── manifest.yaml         ← zone grammar, archetype zone-maps
├── _references/          ← legacy style refs (not used in current pipeline)
├── _smoke_test/          ← v1 + v2 + v3 incremental validation samples
└── map-<class>/          ← per-class layout PNG + .txt caption pairs
    ├── map-freighter-small/
    ├── map-freighter-medium/
    ├── map-frigate-escort/
    ├── map-destroyer-light/
    ├── map-transport-bulk/
    └── map-yacht-roguetrader/
```
