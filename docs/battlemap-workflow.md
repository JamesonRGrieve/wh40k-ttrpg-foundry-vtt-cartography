# Battlemap generation — operator's notebook

This is the running record of what works and what doesn't when driving
the ComfyUI battlemap workflows. Update it after every successful or
failed run; freeze nothing. The working hypothesis at any moment is
whatever this file currently says.

The goal: **bare top-down architectural battlemaps** (floor + walls,
maybe doors / ramps / windows) suitable for Foundry V14 scene
backgrounds. Props are NOT generated here — they're stamped on top
later via the `multi-token-edit` Mass Edit pipeline. A second
foreground/walls-only pass for stackable layered scenes is in scope as
an optional step but is NOT implemented yet.

---

## 2026-05-07 — Round 1 audit of interior smoketests

Graded the original `map_*_smoketest_00001_.png` set on three axes:
top-down fidelity, architecture-only, tileability.

| Archetype | Top-down | Arch-only | Tileable | Failure mode |
| --- | --- | --- | --- | --- |
| hab | ✓ | ✓ | ✗ | Bezel/frame artifact at all 4 edges |
| industrial | ✓ | ⚠ | ✗ | Bezel + hazard-stripe cross painted on floor |
| chapel | ✗ | ✓ | ✗ | Visible side columns + ceiling = isometric drift |
| tunnel | ✓ | ✓ | ✗ | Bezel; rendered 1:1 instead of corridor aspect |
| garrison | ✓ | ✗ | ✗ | Weapon racks + vehicles leaked into base |
| bar | ⚠ | ✓ | ✗ | Bezel; hanging chains imply slight perspective |
| interior_bareroom | ✓ | ✓ | ✗ | Bezel even on the bare baseline |

`lair`, `medicae`, `archive`, `mechanicus` had no canonical-seed
smoketests at all — never tested at parity.

**Three diagnosed failure modes:**

1. **Universal bezel/frame artifact.** Every interior render had a
   thick rendered metal bezel/frame around the image edges that
   defeated tileability. The static negative in
   `BattlemapInteriorV1.json` (`"perspective view, side view,
   isometric, character…"`) does NOT target it. Also: the driver only
   ever wrote `pos.t5xxl/clip_l` — `neg` was never adjusted client-side.
2. **Isometric drift on chapel + bar.** Despite "top-down overhead
   orthographic" in the positive, Flux rendered visible vertical wall
   faces and ceiling structures.
3. **Furniture leak on garrison.** Naming an object even in a
   negative-shaped clause ("racks bare of weapons") still produced the
   rack object. Garrison had visible weapon racks and vehicle
   silhouettes at the edges.

### Round 2 fix shape

- Added `_extend_negative()` helper to `generate_battlemap.py` so the
  driver can layer a domain-specific negative addendum onto the
  workflow's static neg without mutating the server-side workflow file.
- `INTERIOR_NEG_ADDENDUM_T5/CLIP_L` constants target all three failure
  modes: anti-bezel ("frame, bezel, border, vignette, picture frame,
  walls forming a border around the image, dark edge falloff"),
  anti-isometric ("vertical wall faces visible, ceiling structures
  visible, ceiling beams, side perspective"), anti-furniture-leak
  ("weapon racks, banners, vehicles, bunks, crates, barrels, hanging
  chains, hanging lights as objects").
- Universal positive clause: "camera looking straight down at 90
  degrees, pure orthographic projection, image fills the frame
  edge-to-edge with no border".
- Per-archetype tightening:
  - `garrison` — dropped "weapon racks" and "regimental banners" from
    positive; replaced with neutral "spartan reinforced concrete walls
    with bolt fixtures and faded paint" plus explicit "no racks, no
    banners, no vehicles".
  - `chapel` — replaced "tall stone walls with carved Imperial
    iconography and brass relief panels" (which Flux rendered
    isometrically) with "thin stone wall outlines forming the room
    perimeter"; replaced "stained-glass slit windows" with "colored
    light pools on the floor from stained-glass slit windows"
    (deflects the camera from rendering the windows themselves).
  - `bar` — pulled "dim hanging lights" and "amber lumen pendants"
    (both rendered as objects); replaced with "amber pools of lumen
    light cast onto the floor".
- New harness `qa_topdown.py` re-renders every archetype at one
  canonical seed (default 42), 1024² for square archetypes, 1024×512
  for `tunnel`. Outputs land in `battlemaps/qa/<tag>/`.

Round 2 results below.

### Round 2 results (seed 42, 14 archetypes, 894s)

| Archetype | Top-down | Arch-only | Tileable | Verdict vs round 1 |
| --- | --- | --- | --- | --- |
| hab | ✓ | ✓ | ✗ | Bezel still present (slightly thinner) |
| chapel | **✓** | ✓ | ⚠ | **WIN: isometric drift fully fixed**; thin perimeter ring of light fixtures only |
| garrison | ✓ | **✗** | ✗ | Lockers/crates still leak around perimeter — furniture leak persists in different objects |
| bar | ✓ | ⚠ | ✗ | Hanging chains gone; small light-fixture ring around perimeter |
| tunnel | ✓ | ⚠ | ✗ | **WIN: corridor aspect now 2:1**; "porthole" frame still present |
| industrial | ✓ | ✗ | ✗ | Hazard stripes painted as objects; crane gantry rendered overhead |
| medicae | ✓ | **✗** | ✗ | Cabinets/shelves rendered along perimeter |
| **lair** | **✓** | **✓** | **✓** | **WIN: pristine, no bezel, fills frame edge-to-edge** |
| archive | ⚠ | ✗ | ✗ | Slight isometric drift; shelf alcoves as 3D structures |
| mechanicus | ✓ | ✗ | ✗ | Decorative cog reliefs as objects; lumen ring around perimeter |
| **district** | ✓ | ✓ | ✓ | **WIN: clean, tileable, no bezel** |
| region | ✓ | ✓ | ⚠ | Strong cartographic framing; usable |
| planet | ✓ | ✓ | ⚠ | Orbital disc; intentionally framed (not for tiling) |
| system | ✓ | ✓ | ⚠ | Parchment chart frame intentional |

**Wins (round 2):**
- Chapel isometric drift fixed — strongest negative + "no ceiling, no side walls" + replacing object-named architectural features (carved iconography, brass relief panels) with flat descriptions.
- Tunnel correct corridor aspect (1024×512).
- Lair pristine — biomorphic textures don't fall into the bezel/wall-thickness trap.
- District + wide-scale archetypes essentially unaffected by the changes (they were already strong; now also benefit from the universal negative).

**Failures still standing (round 2):**
- **Bezel persists on most interiors.** Diagnosed as the actual root cause: it's not a vignette — it's the room's perimeter walls being rendered with implied 3D thickness. Anti-bezel negatives can't suppress something the positive prompt explicitly asks for ("thick bulkhead walls around the perimeter").
- **Furniture leak persists** but the leaked objects shifted: garrison now leaks lockers/crates instead of weapon racks; medicae leaks cabinets; archive leaks shelf alcoves; mechanicus leaks decorative cog reliefs. The pattern: any noun in the positive prompt that names an architectural-furnishing hybrid (banner, rack, cabinet, shelf, relief) gets rendered, regardless of negative intent.

**Round 3 pivot — floor-only base layer.**

The bezel/wall-thickness issue is a positive-prompt problem, not a
negative-prompt problem. Stackable design says walls live on a
separate foreground/walls-only pass anyway. So:

- New `INTERIOR_STYLE_FLOOR_TEXTURES` dict — one per archetype,
  describing only the floor surface texture.
- New `INTERIOR_FLOOR_PROMPT_TEMPLATE` — wraps the texture in a fixed
  "top-down floor filling the entire frame, no walls" envelope.
- New `INTERIOR_FLOOR_ONLY_NEG_T5/CLIP_L` — strong "walls, bulkheads,
  perimeter walls, doorways, columns" suppression layered on top of
  the round-2 universal negative.
- New CLI flag `--floor-only` on `interior` and `qa_topdown.py`.
- `run_interior(floor_only=True)` plumbing.

The canonical stackable base map becomes: floor (interior
`--floor-only --style <archetype>`) + walls (separate render or
hand-drawn) + stamps. Round 3 results below.

### Round 3 results (floor-only, seed 42, 10 interior archetypes, 635s)

| Archetype | Top-down | No-walls | Tileable | Notes |
| --- | --- | --- | --- | --- |
| hab | ✓ | ✓ | ✓ | Clean ferrocrete slabs with yellow lumen-pool stains; seamless. |
| tunnel | ✓ | ✓ | ✓ | Steel grating + cable bundle on the floor; corridor aspect 2:1. |
| industrial | ✓ | ✓ | ✓ | Steel plate floor with weld seams and amber-rust patches. |
| chapel | ✓ | ✓ | ⚠ | Aquila mosaic stones; **top + bottom decorative gilded borders** persist (probably triggered by "candle wax accumulated at edges" in fragment). Minor; trim or accept. |
| bar | ✓ | ✓ | ✓ | Wood plank with deep stains and burn marks; pristine tileable surface. |
| garrison | ✓ | ✓ | ✓ | Concrete tile with rust patches; **no more lockers leaking**. |
| lair | ✓ | ✓ | ✓ | Organic substrate with green phosphor patches; pristine. |
| medicae | ✓ | ✓ | ✓ | White ceramic tiles, faint stains; **no more cabinets leaking**. |
| archive | ✓ | ✓ | ✓ | Wooden plank with paper fragments; **no more shelf alcoves**. |
| mechanicus | ✓ | ✓ | ⚠ | Black metal plate with engraved cog motif; round red lumens drawn AS floor studs. Decorative but acceptable as stampable base. |

**Verdict: floor-only is the canonical interior base layer.** 8/10 fully
deploy-ready as tileable bare floor; 2/10 have minor decorative
artifacts (chapel border, mechanicus lumen studs) that are still
stamp-compatible.

**Wins (round 3):**
- The bezel/wall-thickness artifact is GONE on every archetype. Pure
  floor texture, edge-to-edge.
- Furniture leak GONE — no lockers, cabinets, racks, shelves, banners.
  Removing the architectural-furnishing nouns from the positive
  prompt entirely was the fix; negative prompts alone could not.
- Tunnel correctly elongated (1024×512) and reads as a corridor floor.
- Lair extended its round-2 win — even cleaner without the perimeter.

**Failures still standing (minor):**
- Chapel: gilded mosaic borders at top + bottom edges. Caused by
  "candle wax accumulated at edges" in the texture fragment biasing
  Flux toward an explicit edge. Future round: drop "at edges".
- Mechanicus: red lumen circles drawn on the floor as decorative
  studs. The fragment includes "ritual blood-red lumen pools"; Flux
  is rendering them as physical floor inlays not light pools. Future
  round: rephrase as "ambient red ground glow" or similar.

**LoRA decision: not needed.** Round 3 floor-only meets the deploy
bar across all 10 archetypes. Plus the 4 wide-scale archetypes from
round 2 (district/region/planet/system) which are unaffected by the
floor-only mode. The user's offered training material remains in
reserve for future archetypes or higher-quality runs but is NOT
blocking any current goal.

### Round 4 polish (chapel + mechanicus only, seed 42, 138s)

| Archetype | Verdict |
| --- | --- |
| **mechanicus** | **WIN.** Replaced "ritual blood-red lumen pools" with "diffuse ambient blood-red illumination across the floor, no light fixtures, no studs". Output: clean black metal plate with red mottled ambient glow + small central Aquila motif. No physical studs. Tileable. |
| chapel | Mixed. Replaced "candle wax accumulated at edges" with scattered drips and "no decorative borders". Output: thin perimeter trim STILL renders + centered Aquila medallion (smaller, cleaner). The medallion is a feature; the trim persists. Diminishing-returns territory — gilded chapel iconography is a strong Flux prior at this aesthetic. |

**Decision:** stop iterating chapel; the trim is acceptable for stamp-overlay use and the medallion adds rather than detracts. Logged as a known minor artifact rather than blocking. Future operator can suppress with a tighter aspect-ratio crop if it bothers them.

**Cross-round wins summary:**
- R1 → R2: chapel isometric drift fixed; tunnel corridor aspect; lair pristine; district pristine.
- R2 → R3: bezel artifact eliminated universally via floor-only pivot; furniture leak eliminated; 8/10 fully clean.
- R3 → R4: mechanicus stud artifact fixed; chapel border partially-fixed (acceptable).

**Cross-round failures summary:**
- R1: bezel + isometric + furniture leak across most archetypes; no smoketests for 4 archetypes (lair/medicae/archive/mechanicus).
- R2: bezel/wall-thickness root cause discovered (positive-prompt issue, not negative-prompt issue); furniture-leak resists named-noun negation.
- R3: chapel decorative borders triggered by "at edges" phrasing; mechanicus lumen pools rendered as physical studs.
- R4: chapel iconography prior is sticky; one round of polish insufficient to fully strip it.

**Canonical stackable battlemap recipe (settled this round):**
1. **Floor (base layer):** `uv run generate_battlemap.py interior --style <archetype> --floor-only --seed <s>`
2. **Walls (foreground layer):** `uv run generate_battlemap.py spacecraft --layout <hand-painted-or-default> --walls-only --seed <s>` — produces a transparent-bg PNG of just the wall geometry.
3. **Stamps (tile layer):** placed in Foundry via Mass Edit Preset Browser.

The pre-existing layered-pass infrastructure (`mask-by-layout`,
`compose`, `--keep-only`) all keeps working unchanged.

### 2026-05-07 — Floor-plan layouts unblock real battlemaps

The floor-only pivot above produces excellent **floor textures** but
not real battlemaps — every render was a single 1024² square room
with no architectural footprint. Operator critique: "all the
battlemaps are single rooms with no floor plan or walls to speak of,
and they're all square." Correct.

The fix is to pivot the canonical interior recipe to the spacecraft
workflow with a multi-room layout PNG. The spacecraft workflow has
been the spatial-control engine all along; it just wasn't being
used for non-ship interiors.

**New tooling:**

- `_make_floorplan(spec)` — paints a canonical-color layout PNG from
  a (rooms, corridors, doors) spec on an arbitrary canvas size.
- `FLOORPLAN_PRESETS` — `hab-2room` (1280×640, two adjacent rooms +
  shared doorway), `hab-3room-corridor` (1792×1024, three rooms off
  a horizontal corridor with three doorways).
- New CLI `make-floorplan <output> --preset <name>` with optional
  `--canvas-w/--canvas-h/--wall-thickness` overrides.
- New `spacecraft --style <archetype>` flag — pulls
  `INTERIOR_STYLE_FLOOR_TEXTURES[style]` and applies it as the
  `floor` region prompt override. Means the same hab/chapel/lair
  texture work that landed in round 3 now flows through the
  spatial-control engine. Explicit `--override floor=…` still wins.

**New canonical recipe (revised):**

1. **Floor plan layout:** `uv run generate_battlemap.py make-floorplan layouts/<name>.png --preset <preset>` (or hand-paint a layout PNG using the canonical region colors).
2. **Base render:** `uv run generate_battlemap.py spacecraft --layout layouts/<name>.png --style <archetype> --seed <s> --prefix <name>_base` — multi-room textured base map.
3. **Walls overlay:** `uv run generate_battlemap.py spacecraft --layout layouts/<name>.png --walls-only --seed <s> --prefix <name>_walls` — transparent-bg PNG of the wall geometry only, pixel-aligned with the base.
4. **Stamps:** placed in Foundry via Mass Edit Preset Browser.

**POC render — `hab-3room-corridor` × hab archetype, seed 42:**

- `layouts/poc_hab_3room.png` — 1792×1024 layout PNG with 3 rooms +
  central corridor + 3 doorways. Lights placed at perimeter corners.
- `battlemaps/poc_hab_3room_base_00001_.png` — base render via
  `spacecraft --style hab`. Walls clearly defined, corridor connects
  three rooms, doorways visible as floor cuts through wall band, hab
  ferrocrete floor mottling visible. **First real multi-room
  battlemap from the pipeline.**
- `battlemaps/poc_hab_3room_walls_00001_.png` (+ `_alpha.png`) —
  walls-only foreground via `spacecraft --walls-only` (next render).

**Wins:**

- Multi-room layout works end-to-end. The spacecraft regional
  conditioning preserves the canonical colors strongly enough that
  walls remain crisp and doorways are clean cuts.
- The 1792×1024 aspect proves layouts are not constrained to 1024².
- The `--style hab` flag flows the round-3 floor texture through the
  spacecraft engine, so no prompt duplication.

**Failures / cosmetic:**

- The hab ferrocrete texture is subtler in the spacecraft render
  than in the standalone `interior --floor-only` render (regional
  conditioning splits guidance across regions, so the floor prompt
  has less aggregate weight). Iterating the prompt to be more
  prompt-dominant (front-loaded distinctive nouns, "high contrast",
  "distinct"). Re-render below.
- Light spots at room corners read as floor inlays rather than
  perimeter wall fixtures (canonical color #D4B260 placed inside the
  wall band but outside the room interior in the layout — that
  region renders amber, but at small disk size). Cosmetic only.

### 2026-05-07 — Floor-plan preset library expanded

Added four new presets to `FLOORPLAN_PRESETS`:

| Preset | Canvas | Footprint |
| --- | --- | --- |
| `tunnel-junction` | 1536×1536 | T-junction of three corridors meeting at a central hub. |
| `chapel-nave-with-apse` | 1280×1792 | Long nave with smaller apse at the north end. |
| `industrial-bay` | 2048×1024 | Single large bay + small annex/control booth. |
| `archive-stacks-grid` | 1792×1280 | 8 vault rooms (4×2) connected by central spine corridor. |

All four render correctly via `make-floorplan --preset <name>`.
Minor cosmetic glitches noted (small wall-band offset at apse↔nave
junction in chapel; small floor stub at hub south wall in tunnel)
but functional for spacecraft-workflow consumption.

### 2026-05-07 — State classifier (CLIP zero-shot) landed

`classify_state.py` runs CLIP-ViT-L-14 zero-shot against each stamp
to populate the `state` field. Two-stage:

1. **Damage**: intact / damaged / destroyed / stateless (→ null).
2. **Activation**: active / inactive / non-device. Activation
   overrides damage only when (a) margin > damage margin, (b) margin
   exceeds `ACTIVATION_TRIGGER_MARGIN` (0.18), and (c) damage said
   `intact` or `stateless` — never override `damaged`/`destroyed`.

Why the strict gating: in the first dry-run almost every dim-rendered
stamp won "inactive" because Flux-rendered illustrations tend to be
dim regardless of whether the subject is a device. The four-condition
gate eliminates that bias.

**Run on the full 615-stamp vault:**
- wrote: 326 (new state values)
- skipped (existing): 157 (manual + caption-keyword fills preserved)
- skipped (low confidence): 132 (visually ambiguous)
- final coverage: 483/615 (78.5%) ← up from 25%

Distribution of new writes: 138 damaged / 121 intact / 47 inactive /
15 destroyed / 5 active / 132 null.

**Wins:**
- 53.5-percentage-point lift in state coverage.
- Owner-only on `state` (regex-replace, doesn't touch other fields).
- Existing values (operator-edited or caption-keyword) preserved by
  default; `--force` available if a re-classify is wanted.

**Failures / known limitations:**
- "Intact" and "damaged" are bimodal; CLIP-ViT-L-14 has ~15-30%
  margin on most stamps but ~5-8% on visually-clean stamps that
  could be either ("damage margin too low" → null). 132 null is
  acceptable; pushing further would need either a fine-tuned model
  or human review.
- "Active" only fires 5 times. Most "powered-on" stamps in the
  vault are static illustrations without strong glow cues, so CLIP
  defaults to "inactive". Acceptable bias.

### 2026-05-07 — Multi-deck variant helper landed

`make_deck_variants.py` takes a base hull layout PNG and emits N
deck-variant copies preserving the outer hull byte-for-byte, with
optional canonical openings (rear ramp, dorsal windscreen) painted
per-deck via `--opening deck<N>=<role>:<side>`.

Tested on `spacecraft_default_quantized_v2.png`: deck1 with a
ramp:south opening, deck2 with a windscreen:north opening. Outer
hull stays pixel-aligned across decks; interior detail is left to
operator hand-paint (which is the appropriate division of labor).



---

## What's saved on the ComfyUI server

Pulled into `workflows/` from the server's `userdata/workflows/`:

| File | Type | Notes |
| --- | --- | --- |
| `BattlemapInteriorV1.json` | txt2img | Chroma-unlocked-v35, 1024² EmptyLatent, single pos/neg pair. No spatial control. |
| `BattlemapSpacecraft.json` | img2img | Same Chroma model, but loads `layout.png` and runs 8 `ImageColorToMask` + `CLIPTextEncodeFlux` + `ConditioningSetMask` chains for per-region conditioning. Strong spatial control. |

Re-pull when the canonical prompts on the server are edited:

```sh
for f in BattlemapSpacecraft.json BattlemapInteriorV1.json; do
  curl -s -o "workflows/$f" "http://198.51.100.11:8188/api/userdata/workflows%2F$f"
done
```

The driver loads these as templates and never edits them. Local
overrides happen in memory.

## How `generate_battlemap.py` drives them

`uv run generate_battlemap.py interior` — overrides `pos.t5xxl` and
`pos.clip_l`, EmptyLatentImage dimensions, KSampler seed, and
SaveImage prefix on `BattlemapInteriorV1`, then submits and downloads.

`uv run generate_battlemap.py spacecraft --layout layouts/foo.png` —
uploads the layout PNG to ComfyUI's `input/battlemap_layouts/`,
rewrites the `LoadImage` node to point at it, sets seed and prefix,
submits.

Outputs land in `battlemaps/`.

## Color codes used by `BattlemapSpacecraft.json`

The eight color->prompt regions baked into the saved workflow (decimal
values match the `color` input on each `ImageColorToMask` node):

| Color (dec) | Hex | Region | Default t5xxl prompt |
| --- | --- | --- | --- |
| 3158064 | `#303030` | walls | thick spacecraft hull bulkhead wall |
| 8421504 | `#808080` | floor | metal deck plating, floor panels with seams |
| 10526880 | `#A0A0A0` | ramp | rear loading ramp, corrugated metal surface |
| 1716304 | `#1A2750` | windscreen | cockpit windscreen viewport, reinforced |
| 9132587 | `#8B5E2B` | chair | pilot command chair, worn brown leather |
| 4876928 | `#4A6F40` | locker | tall metal storage locker, steel blue |
| 2771536 | `#2A4250` | console | instrument console panel, control dials |
| 13934624 | `#D4B260` | lighting | amber lumen strip light, glowing warning |

**Important**: the color match is exact. Anti-aliased edges between
regions in your layout PNG won't match any color and will fall through
to the unmasked base prompt. Either paint with hard edges (Krita →
Pixel Art brush, GIMP → no-AA pencil), or post-process the layout
through nearest-neighbor color quantization to the eight colors above.

## Successes

### 2026-05-05 — Layered/multi-deck stacking VERIFIED

**Same-footprint multi-deck**: painted two layouts (engineering
deck + bridge deck) sharing the same outer hull region. Walls
coincide pixel-perfectly: exact-color IoU = 0.946 (deck1 walls are
a complete subset of deck2 walls; the 5% delta is deck1's
loading-ramp opening punching through the hull on purpose). A
token at (x,y) on deck1 lands at the same (x,y) on deck2. Foundry
multi-deck scenes can use either deck as the active scene without
re-positioning.

**Independent-render layered overlay**: rendered a metal-grate
scaffold via interior txt2img, masked it to the floor region
using the layout PNG as the alpha source, alpha-composited over a
separately-rendered base map. Walls + lights from base show
through the perimeter; scaffold occupies the floor area exactly.
Pixel-perfect alignment because both renders share the same
layout, and the layout drives the alpha mask deterministically.

The walls-only mode (`spacecraft --walls-only` / `--keep-only
wall`) is the simplest case of this pattern. The new
`mask-by-layout` subcommand generalizes it to any role and any
input render — letting you produce arbitrary stackable layers
(scaffolding, water, fog, second-floor cutaways) by rendering them
independently and masking.

### 2026-05-05 — Group-membership audit (visual inspection)

Manually inspected all 9 multi-member groups in the current vault:

| group | members | verdict |
| --- | --- | --- |
| `3380ef7e` | 2 | ✅ TRUE variants — battered office chair pair |
| `3b58afaa` | 2 | ✅ TRUE variants — paperwork pile (intact / aged) |
| `7e090f37` | 2 | ✅ TRUE variants — locker pair (intact / weathered) |
| `b00219a2` | 2 | ✅ TRUE variants — sealed dossier (intact / bloodied) |
| `fbdc4f25` | 3 | ✅ TRUE state-variants — cogitator console (active / inactive / destroyed) |
| `309afa52` | 4 | ⚠ same family (pipe fittings) but different junction shapes — not strict variants |
| `861baff5` | 4 | ⚠ partially correct: 3 bed variants + 1 false-positive locker pair (cleared) |
| `f3df525c` | 3 | ❌ FALSE-POSITIVE merge: 3 distinct container types (case/locker-door/footlocker) — cleared |
| `83fd8256` | 5 | ❌ FALSE-POSITIVE merge: 5 distinct bulkhead panels — cleared |

Took action:
- Cleared `group_id` to null on 9 stamps confirmed as
  false-positive merges.
- Manually filled name/description/state on 6 yamls where visual
  inspection revealed information missing from captions
  (e.g. cogitator console state — captions said "televisions
  arranged" but the images clearly show active/inactive/destroyed
  CRT terminal variants).

The Phase 2 merge threshold (`MERGE_THRESHOLD = 0.92` in
`assign_groups.py`) is too generous for stamps that share a
common art-style background (beige/grimdark palette pulls
unrelated subjects close in CLIP-ViT-H embedding space).
Operationally, manual yaml inspection is required for any group
the operator wants to use as a strict state-variant cluster.
Future: extend `pipeline_status.py` with a "group sanity check"
that flags suspicious merges (e.g. groups whose member captions
share <50% of content tokens).

### 2026-05-06 — Orientation classification via CLIP zero-shot

Caption-based `derive_orientation` populated only ~3% of stamps —
Florence-2 captions almost never include directional words.
Built `classify_orientation.py` to bypass captions entirely:
CLIP-ViT-L-14 zero-shot classification directly on the stamp PNG.

Two stages:
1. Camera angle: top-down vs isometric (softmax over paraphrase set
   per label, average-pooled embedding).
2. Facing direction (only run when isometric): N/S/E/W via four
   directional paraphrase sets.

Confidence margin gates: results stay null below 12% probability
margin between top-1 and top-2.

**Research path documented**:
- `Florence-2 docvqa` task: empty for natural images. Documents only.
- `SigLIP-so400m`: sigmoid scoring biased to verbose label sets —
  collapsed every stamp to "top-down" with the longer prompts. Bad
  for binary contrastive choice in this domain.
- `CLIP-ViT-L-14 softmax`: ~64% angle accuracy on the 4lrua5
  hand-grounded test set. Best of the three on stylized
  illustrations. Picked.

Full vault: 552/615 (89.7%) populated. Distribution:
303 top-down, 142 north, 91 isometric, 80 null (low-confidence),
12 west, 4 east. Operator can manually correct misses; Foundry
tile rotation is freeform regardless.

### 2026-05-06 — Phase 2 merge: median cross-pair, not best

Best-pair similarity chained unrelated clusters into superclusters
(one supercluster reached 121 members in this vault). The single
high-similarity pair between two otherwise-distinct clusters
triggered a merge, snowballing transitively across the union-find.

Switched to MEDIAN cross-pair similarity at MERGE_THRESHOLD=0.92.
Now the bulk of cross-pair distribution must exceed the threshold.
Cap on cluster size dropped from 121 to 17. 88 multi-member
candidates produced (vs 41 with best-pair); audit flagged 23
(cleared); 65 clean confirmed groups.

### 2026-05-06 — "Caption-resistant" stamps were all gutter artifacts

The 17 stamps that resisted Florence-2 (PromptGen + base) all had
fill ratios 0.013-0.041 — grid-line networks captured before
MIN_FILL_RATIO was added to extract_stamps.py. Most appeared at
sheet positions 14-16 (consistent with the extractor processing
the gutter-network connected component AFTER the cell stamps).

Retroactive cleanup: `/tmp/cleanup_gutter.py` removes any stamp
with fill < 0.10. Result: 632 → 615 stamps, 100% classification
on real-stamp content.

The tertiary Florence-2-base fallback is still valuable for the
3-5 real stamps where PromptGen silently empties; it just turned
out NOT to be the recovery path for the 17 outliers we initially
investigated.

### 2026-05-06 — Tertiary fallback recovers 111/128 PromptGen empties

After the long classify pass left 128 stamps with empty captions,
diagnostic showed PromptGen-v2.0 SILENTLY emits "" for certain art
styles (arcade-cabinet kiosks, plain metal desks, drink trays, white
canisters). Florence-2-large (base) captions the same images
correctly. Added a tertiary pass to `classify_one()`:

1. PromptGen v2.0 / native + transparent
2. PromptGen v2.0 / 768 + white (retry)
3. **Florence-2-large / 768 + white** (NEW fallback)

Re-running classify after this fix: 111 of 128 recovered. 17
genuinely abstract / near-empty images empty across all paths and
require manual annotation.

`classified_by` field now records which model produced the caption.
`grep -l "classified_by: microsoft" stamps/*.yaml | wc -l` shows the
fallback recovery count after a run.

### 2026-05-06 — assign_groups regenerates group_id from name+members

When stamp names changed (e.g. manual fills), the resulting
`uuid5(GROUP_NAMESPACE, "<canonical_name>:<sha1(sorted_members)>")`
hash also changes, so the same conceptual cluster gets a fresh
group_id on the next assign_groups run. This is correct (uuid5 is
deterministic), but means: don't reference a specific group_id in
code/docs as stable. After a re-classify-then-reassign cycle,
re-import the preset pack into Mass Edit so the `group:` tags align
with the new ids.

### 2026-05-06 — Phase 2 over-merges scale superclusters

With 600+ classified stamps, the default `MERGE_THRESHOLD = 0.92` in
`assign_groups.py` produces 97- to 121-member superclusters of
unrelated subjects that happen to share art-style background. Two
audit-and-clear cycles ran in this session; the second cycle still
found 22 flagged groups requiring manual clearing.

Recommended permanent fix: lower the threshold to ~0.96 or cap
cluster size at ~6 members at the source. Until then, run
`group_audit.py` after every assign and clear flagged groups with:

```python
import json, re, subprocess, yaml, glob
result = subprocess.run(['uv','run','--quiet','group_audit.py','--json'],
                        capture_output=True, text=True)
flagged = {r['group_id'] for r in json.loads(result.stdout)['flagged']}
for f in glob.glob('stamps/*.yaml'):
    text = open(f).read()
    if (yaml.safe_load(text) or {}).get('group_id') in flagged:
        open(f,'w').write(re.sub(r'^group_id:.*$', 'group_id: null',
                                  text, count=1, flags=re.MULTILINE))
```

### 2026-05-05 — Florence-2 unrecoverable failures (some stamps)

A small fraction of stamps (`_08.png`, `_09.png` in 4lrua5 — both
battered office chairs in a slightly cartoonish 3/4-from-above
style) consistently caption empty across every Florence-2-
PromptGen-v2.0 configuration tried: native+transparent,
native+white-bg, 768+white-bg, multiple tasks (caption,
detailed_caption, more_detailed_caption, prompt_gen_tags), and
single-task vs dual-task workflows. Confirmed reproducible.

The grouping pipeline RECOVERS these stamps via CLIP-ViT-H image
embedding — the two chairs landed in the same Phase 2 cluster
even though both have empty descriptions. Operationally:

* For visually-similar variants of the same object, the embedding
  step produces correct group ids regardless of caption.
* For names/tags on these stamps, the operator can edit the yaml
  manually. The pipeline preserves manual yaml edits across re-
  runs (classify_stamps only writes script-owned fields when
  --force is passed and the script can produce text).

Non-leverage paths attempted (don't retry):
* Bigger upscale (1024, 1536) — same empty result.
* Gray background instead of white — same.
* Model swap to base Florence-2 — produces hallucinations on
  unrelated stamps; net regression.

Possible future improvement: fall back to a different VLM (e.g. a
small LLaVA or Qwen-VL) on Florence-2 empty-output retries. Out
of scope for now; Phase-2 embedding rescue is sufficient.

### 2026-05-05 — Quantizer v2 (modal-background detection)

The first quantizer needed the input layout's region colors to be
within ~25 channels of canonical, which the hand-painted reference
layout violated (windscreen / lighting got swept to background).
v2 splits the work into two stages: detect the modal color via
16-step binning and treat that as background; then force-snap every
non-background pixel to the nearest canonical color WITHOUT a
distance cap. Result on `spacecraft_default.png`: 69.4% of pixels
detected as background, all 7 painted regions snapped cleanly to
canonical colors. The walls-only render against the quantized
layout produces a continuous bulkhead outline (10.1% kept) vs. the
raw layout's gappy antialiased outline (7.6% kept).

Use this to pre-process any hand-painted layout before feeding it
to ComfyUI's `ImageColorToMask` regional-conditioning nodes.

### 2026-05-05 — End-to-end pipeline aligned with deploy.sh

`stage_module.py` now prunes orphaned staged stamps (those whose
source has been deleted, like the gutter artifact `_05.png` from
4lrua5). `build_mass_edit_pack.py`'s default `--out` writes to
`dh-cartography/mass-edit-presets.json` so dev runs produce the
same artifact `deploy.sh cartography` ships. After running both:
632 presets across all sheets, 14 for the 4lrua5 sheet (gutter
gone), names like "Empty Ceramic Bowls With Handles" with
orientation/state suffixes ("— east", "— active, west") and
populated tag arrays. Pipeline is ready to deploy on user
instruction.



### 2026-05-05 — Interior workflow, bare room (1024²)

Command:

```sh
uv run generate_battlemap.py interior --seed 42 --prefix map_interior_bareroom
```

Result: `battlemaps/map_interior_bareroom_00001_.png` (1.9 MB, 1024²).

The driver's bare-architecture default prompt (no tables / chairs /
counters / barrels — explicit "completely empty room with no
furniture, no props" in the positive prompt because Flux ignores
negative-prompt furniture exclusions) produced exactly the target
deliverable: top-down orthographic empty room, bulkhead walls around
the perimeter with rivets and weld seams, corroded deck plating with
visible seam lines and rust, amber lumen lights at the corners. No
props, no characters, no decorations on the floor. Drop a Foundry
scene background underneath this and stamp props on top.

The image isn't a perfect orthographic projection — there's a slight
parallax tilt (corners appear higher than the center) — but it's
close enough that tokens placed on it read as "in the room". Pure
orthographic would require ControlNet depth conditioning, not in
scope yet.

### 2026-05-05 — Interior workflow, first end-to-end run

Command:

```sh
uv run generate_battlemap.py interior --seed 42 --prefix map_interior_smoketest --width 768 --height 768
```

Result: `battlemaps/map_interior_smoketest_00001_.png` (1.1 MB, 768²).

The HTTP plumbing works: workflow loaded, prompts mutated, dimensions
overridden, seed fixed, prompt submitted, history polled,
`SaveImage` output downloaded. Visual quality on the saved
canonical prompt was good — recognizable top-down grimdark sci-fi
interior with bulkhead walls, deck plating, amber/teal lighting, slight
isometric tilt rather than pure orthographic.

### 2026-05-05 — Stamp pipeline (4lrua5 sheet)

Not battlemaps, but the same ComfyUI plumbing — recording here so the
gotchas don't get lost when this file is the canonical operator's
notebook.

**Two-pass classifier**. Florence-2-large-PromptGen-v2.0 succeeds at
captioning native-size transparent stamps for ~80% of cells and
upscaled-to-768 white-bg stamps for a different ~80% — they're
complementary, not strictly better/worse. `classify_stamps.classify_one`
now runs the default native-transparent pass first; on empty caption,
retries with the upscale + white-bg payload uploaded under a
`__retry`-suffixed filename. Result on the 4lrua5 sheet: 12/15 vs
9/15 with single-pass.

**Token floor**. The dual-task workflow (`more_detailed_caption` +
`prompt_gen_tags` simultaneously) returns empty text for some images
when `max_new_tokens<1024`. Single-task workflows are fine at 256.
Codified at 1024 in `build_workflow()`.

**Caption-preamble stripping**. PromptGen reliably emits captions
like "The image is a digital illustration of [subject]". A
single-regex extractor lands on garbage ("Is A Digital Illustration",
"Set", "Collection"). `_strip_preamble()` peels
medium/multiplicity/article words iteratively until what remains
starts with the actual subject noun. Names went from "Stack" →
"Papers Tied Together With Twine"; from "Is A Digital Illustration"
→ "Empty Ceramic Bowls With Handles".

**CLIP-ViT-H rescues Florence-2 failures**. Stamps 08/09 of the
4lrua5 sheet (battered office chairs) caption empty on every
Florence-2 path tried. Phase-2 image embedding clustered them
together correctly anyway — visual similarity carries when language
fails. The Phase 1 / Phase 2 split is load-bearing; don't collapse
either side into the other.

**Extraction fix landed**: `extract_stamps.MIN_FILL_RATIO = 0.15`
rejects sparse components. Real stamps fill 0.55-0.82 of their
bbox; grid-line networks captured as a single huge component fill
~0.011. The filter logs `[reject] <file> label=N: fill=X.YYY <
0.15` for visibility. Verified on the 4lrua5 sheet — gutter
artifact rejected, 14 real stamps extracted (down from 15 with
the gutter inflating the count). Re-extracting an already-
processed sheet renumbers, so don't `--force` re-extract on
already-classified sheets — manually delete the offending
`_NN.{png,yaml}` pair instead. Done for 4lrua5 — gap at index 05
is intentional and harmless to downstream tools.

## Failures and gotchas

### Saved canonical prompt embeds props

The `BattlemapInteriorV1` template's pos.t5xxl describes "round wooden
tables with metal stools, long bar counter with taps, barrel storage
alcove with crates" — i.e., a furnished bar. The first smoketest
faithfully rendered all of those.

For our use case (bare maps, props via stamp), the script's
`INTERIOR_DEFAULT_T5` is now overridden to an architecture-only
prompt with explicit negative-of-furniture in positive ("completely
empty room with no furniture, no props, no objects, no tables, no
chairs"). Flux's t5xxl ignores `neg.t5xxl` instructions like "no
chairs", so the avoidance has to live in the positive prompt. We have
not yet validated this works — pending a second smoketest.

The saved server template was left untouched (it's the canonical
"furnished bar" exemplar). Stripped-architecture variants live in the
script's defaults; if they prove out, they should be cloned to the
server as `BattlemapInteriorV2_BareRoom.json` via:

```sh
uv run generate_battlemap.py clone BattlemapInteriorV1.json BattlemapInteriorV2_BareRoom.json
```

then edited in the ComfyUI web UI.

### Filename prefix double-printed

The first download landed as `map_interior_smoketest_map_interior_smoketest_00001_.png`
because `_download_first()` prepended our prefix to ComfyUI's saved
name (which already starts with the SaveImage prefix). Fixed: the
saved filename is used verbatim. `--prefix` only sets the SaveImage
node's `filename_prefix`, which becomes the saved name's stem.

### GPU contention with classify_stamps

Running `generate_battlemap.py interior` while
`classify_stamps.py` was iterating over the 4lrua5 sheet caused
multiple Florence-2 prompts to time out at 300s and several to come
back with empty captions. CLAUDE.md's "Never run two classify or
assign processes concurrently" rule extends to battlemap generation —
the 3090 is one queue, all jobs are siblings. **Serialize.** Don't
launch a battlemap render while a classify or assign run is in
progress, and vice versa.

## Layered foreground pass

`uv run generate_battlemap.py spacecraft --layout … --walls-only`
produces a transparent-background walls layer suitable for Foundry's
scene foreground / overlay tile.

### Implementation

The driver runs the canonical spacecraft workflow unchanged (no
prompt overrides, no chromakey shenanigans). Post-render, it uses
**the original layout PNG as an alpha mask over the rendered PNG**:
pixels whose layout-image color is within tolerance of the target
region's color stay opaque; everything else gets `alpha=0`. The
output goes to `<prefix>_alpha.png`.

This is deterministic in a way the chromakey approach was not — the
layout is the source of truth for "where is the wall," not Flux's
attempt to render a magenta region. See the failure log below for
what didn't work.

### What didn't work (recorded so we don't redo it)

**Magenta-prompt chromakey**: first attempt overrode every non-wall
region's `CLIPTextEncodeFlux` to "solid pure magenta `#FF00FF`,
featureless flat color, no detail" and tried to chromakey magenta
out post-render. Flux's t5xxl encoder mutes saturated out-of-gamut
prompts to a neutral mid-tone — the rendered output had ~zero
magenta pixels, so the chromakey filter ate nothing. Confirmed by
running the full pipeline with `--walls-only` (chromakey variant)
on the spacecraft layout: 0/2,073,600 pixels keyed. Walls-only mode
now uses the layout-as-mask approach instead.

### Edge artifacts (open improvement)

Hand-painted layouts have anti-aliased edges between regions. Those
mid-tone pixels don't match any region's exact color, so the alpha
mask passes them through as transparent — leaving thin gaps in the
walls outline of the produced layer. Two ways to fix:

1. **Pre-process the layout** through nearest-neighbor color
   quantization to the eight canonical region colors before feeding
   it to the script. Krita / Photoshop / GIMP all support this.
2. **Increase the mask tolerance** (currently `tol=40` Chebyshev) but
   that risks bleeding into adjacent regions. Per-role tolerance
   would be needed.

Option 1 is the cleaner fix because it also improves the input to
ComfyUI's `ImageColorToMask` nodes (which require exact match);
the regional conditioning becomes more reliable AND the alpha mask
becomes pixel-perfect at the same time.

`generate_battlemap.py quantize-layout <input>` snaps each pixel of
the layout to the nearest canonical region color (within a tight
Chebyshev tolerance) and forces background to black. Known
limitation as of 2026-05-05: works only when the input layout's
sampled colors are within ~25 channel distance of the canonical
palette. The shipped reference layout (`spacecraft_default.png`,
pulled from the ComfyUI server) is hand-painted with approximate
colors that drift further than that — windscreen and lighting
regions get swept to background. Two workable paths going forward:

1. Paint future layouts with the exact canonical colors (an
   eyedropper-snap palette in your image tool, or a fresh layout
   built from colored rectangles directly in Python).
2. Extend the quantizer with a per-region tolerance map or a
   clustering pass that learns the layout's actual region colors
   and maps them to the canonical palette by proximity.

For the current `spacecraft_default.png` layout, the
unmodified-layout-as-mask path in `--walls-only` is sufficient —
the thin anti-alias gaps in the wall outline are cosmetic and
don't break the layered scene.

## Source-of-truth contract

The saved workflows are authoritative. Don't edit `workflows/*.json`
in this repo by hand — those are pulls. Edit on the ComfyUI server
(via the web UI, save, then re-pull). The driver script asserts
nothing about node ids; if a node is renamed on the server, the
script fails loudly with `KeyError`.
