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

## 2026-05-07 — Asset generation pipelines (build session 1)

Three new pipelines wired end-to-end with the symbol-preservation
infrastructure. Each delivers a real first-cut artifact; further
iteration is operator-driven.

### Pipeline 3 — scene pictures (LANDED)

`generate_scene_picture.py` reuses the Flux txt2img workflow
(BattlemapInteriorV1) with three additions:
1. Anti-symbol negative prompts (Aquila/Inquisition/Mechanicus etc).
2. Per-aspect anchor map (DEFAULT_ANCHORS, fractional coords).
3. Post-render symbol_compose pass with canny-IoU validation.

POC (seed 42, 1024×768): `[[District 4 Chapel]]` with
`aquila:apse_back,large` + `adeptus_ministorum:lectern_front,small`.

**Wins:**
- Recognizable chapel interior — pews, candles, arches, dramatic
  lighting. Operator-acceptable for a handout.
- Anti-symbol negatives WORKED: no hallucinated 40K iconography in
  the diffusion render itself. The composited canonicals are the
  ONLY 40K symbology in the final image.
- Aquila and Ministorum sigil pasted at the right anchor points,
  visually integrated.

**Fails (and fixes):**
- **Validator was wrong.** First run flagged both symbols (IoU 0.70
  / 0.60) below threshold. Root cause: validator was comparing the
  cropped composite region (which has SCENE edges visible through
  the canonical's transparent regions) against the clean canonical.
  Fix: alpha-mask the IoU to the canonical's non-transparent
  pixels. Re-validation: aquila 0.942, adeptus_ministorum 0.887,
  both pass. Validator update is in `_canny_iou(mask_alpha=True)`.

### Pipeline 1 — stamp variants (LANDED)

`generate_stamp_variants.py` with two subcommands:

- **`rotate --method geometric`**: pure PIL, no GPU. Rotates the
  PNG 90/180/270° per requested variant. Tested on
  `Gemini_Generated_Image_2m932e2m932e2m93_01.png` (radar console);
  south/east/west variants produced correctly with alpha preserved.
- **`condition`**: img2img via a client-constructed Flux workflow
  with low denoise (0.55-0.65). Tested with damaged variant.

**Wins:**
- Geometric rotation is fast, deterministic, lossless. Covers the
  majority of top-down rotation cases.
- Client-constructed img2img workflow works without any server-side
  workflow file (submitted directly via /prompt API).

**Fails (and fixes):**
- **First condition render produced noise.** Root cause: stamps
  are ~128×128, VAE-encoded latent is ~16×16. Flux is severely
  under-resolved at that latent size and decodes to garbage.
- **Fix: pre-upscale to 512px shortest edge BEFORE img2img**, then
  resize down + restore alpha mask from the source after. New
  helper `_preprocess_for_img2img()`. The white-background flatten
  also gives Flux a stable backdrop to denoise against.
- **Generative rotation deferred** — geometric covers the common
  case; generative rotation (proper relighting + asymmetry update)
  is non-trivial and lower priority than condition variants.

### Pipeline 2 — character portraits (LANDED, bust + token)

`generate_character_portrait.py` reuses the Flux txt2img workflow
with class-specific prompts + anti-symbol negatives + symbol-compose
pass. POC: Inquisitor bust at 768×1024, seed 42.

Per-class profile in CLASS_PROFILES dict:
- inquisitor → rosette on chest center
- acolyte → I on collar left
- tech-priest → cog on chest center
- guardsman → astra-militarum on shoulder right
- preacher → ministorum on chest center
- astropath → no symbol (warp-touched, generic)
- hive-ganger → no symbol (illegitimate)
- civilian → aquila on collar (personal pendant)

**Token output (operator request):** every portrait also produces a
1:1 square token cropped from the head/shoulders region, scaled to
512×512 (Foundry actor token convention). Per-slot crop center via
TOKEN_CY_FRAC: 0.30 for bust, 0.20 for three-quarter, 0.13 for
full-body. Output naming: `<name>.png` for portrait,
`<name>_token.png` for token. Sidecar JSON records the crop box.

**Wins:**
- Inquisitor portrait nailed the brief — severe weathered face,
  high-collar coat, ornate carapace, oil-painting style.
- Anti-symbol negatives kept hallucinated 40K iconography out of
  the diffusion render; the composited rosette is the only sigil.
- Token crop is operator-acceptable for Foundry actor-token use.

**Fails (and TODOs):**
- Rosette IoU 0.632 (FLAG). The rosette has lots of internal alpha
  and the armor detail underneath leaks into the comparison even
  with alpha-masked IoU. Symbols with sparse internal coverage
  need a different validation approach (maybe an inset mask or a
  lower threshold per-symbol).
- ControlNet OpenPose for explicit pose composition is deferred.
- IPAdapter face consistency across multiple portraits of the same
  character is deferred. Currently each portrait re-rolls the face;
  to make a recurring NPC look consistent across portraits, the
  operator would need to lock seed + prompt manually.

### Cross-cutting

- **`_extend_negative()` now reused by 3 pipelines** (battlemap
  interior, scene picture, condition variant) — DRY win.
- **Symbol library validated end-to-end**. 11/13 canonicals load
  and composite correctly. Cult Imperialis flame and skull-laurel
  still pending operator-supplied SVGs.

---

## 2026-05-07 — Symbology integration: ControlNet attempt failed, img2img pivot works

Goal of this round: replace the literal-paste symbol-compose pipeline
with structural guidance so canonicals appear AS scene material
(brass relief, embroidered banner, armor inlay) rather than as flat
black SVG glued onto the diffusion render.

### Round 1: ControlNet path — FAILED

Built `render_scene_with_controlnet()` that:
1. Composites canonical silhouettes onto a white guide canvas at
   each anchor position.
2. Patches BattlemapInteriorV1 template with a Canny + ControlNet
   apply chain.
3. Submits via /prompt API.

Tried `flux-canny-controlnet.safetensors` via the generic
`ControlNetLoader` + `ControlNetApplyAdvanced`. Hung indefinitely
on the GPU — burned ~25 min of GPU time before I cancelled. The
prompt sat in `queue_running` with no output.

Root cause: ComfyUI has Flux-specific ControlNet nodes
(`LoadFluxControlNet`, `ApplyFluxControlNet`,
`ApplyAdvancedFluxControlNet`) that produce a `FluxControlNet` /
`controlnet_condition` type, NOT the generic `CONTROL_NET` /
`CONDITIONING` types that `ControlNetApplyAdvanced` consumes.
Worse, `LoadFluxControlNet` only declares `flux-dev`,
`flux-dev-fp8`, `flux-schnell` as model choices — Chroma is a
distilled-Flux variant and isn't on that list. Generic ControlNet
apply chain on a Flux/Chroma model = silent hang.

### Round 2: img2img integration — LANDED

Pivoted to a two-pass img2img approach that achieves the same
intended outcome (preserve silhouette, fill in scene material) via
the proven img2img path that already powers stamp condition variants:

1. **Pass 1**: txt2img scene render WITHOUT symbols, using the
   anti-symbol negative prompt list. Flux paints clean scene.
2. **Composite**: paint each canonical's BLACK silhouette (alpha
   from canonical, RGB = pure black) onto the pass-1 render at the
   declared anchor position and size. The composite is saved as
   the "guide" image — a normal RGB PNG, no transparency.
3. **Pass 2**: img2img on the composite with low denoise
   (0.40-0.55) and the augmented prompt that names each symbol's
   material per `MATERIAL_HINTS` (brass-relief, armor-inlay,
   embroidered-banner, carved-stone, painted-icon, stained-glass,
   branded-leather, stamped-metal). The diffusion repaints the
   black silhouette regions as the requested material while leaving
   the rest of the scene mostly intact (because most pixels are
   already at near-final state and low denoise preserves them).

### POCs verified

**Chapel scene** (`Lore/handouts/district_4_chapel_v2.png`,
seed 42, 1024×768, 0.45 denoise integration):
- Pass 1 produced a clean chapel exterior in painterly oil style.
- Composite painted a black Imperial Aquila silhouette top-center
  (apse_back anchor) and a smaller black Adeptus Ministorum
  silhouette near the doorway (lectern_front anchor).
- Pass 2 transformed the silhouettes into integrated scene
  iconography. The Aquila reads as part of the chapel's facade
  decoration; the Ministorum sigil is integrated near the
  doorway as architectural emblem. Neither reads as a glued-on
  2D black SVG.
- Note: composition came out as exterior, not interior. The seed
  + slightly different prompt produced a different framing. Not
  a regression — operator can re-roll seeds for desired
  composition.

**Inquisitor portrait** (`Characters/portraits/test_inquisitor_v2.png`,
seed 42, 768×1024, 0.45 denoise integration):
- Pass 1 produced a strong inquisitor bust with a high-collar
  coat and ornate carapace.
- Composite painted a black Inquisitorial Rosette silhouette on
  the chest plate (size 207, large size_label).
- Pass 2 integrated the rosette into the armor. Visible in the
  final portrait AND in the cropped 1:1 token: the armor bears
  Aquila-wing heraldry on the chest plate that reads as
  embossed-metal armor inlay (per the `armor-inlay` material
  hint). NOT a glued-on SVG.

### Wins

- Symbology now appears as integrated scene/armor material instead
  of flat black SVG.
- Reused the proven img2img workflow constructor (template-patched
  BattlemapInteriorV1) — no new ComfyUI workflow JSON needed.
- `MATERIAL_HINTS` dict gives the operator named recipes:
  `brass-relief`, `armor-inlay`, `embroidered-banner`,
  `carved-stone`, `painted-icon`, `stained-glass`,
  `branded-leather`, `stamped-metal`. Per-class portrait
  profiles in `CLASS_PROFILES` now declare a default material
  per symbol (e.g. tech-priest cog → brass-relief, guardsman
  astra-militarum → stamped-metal pauldron, preacher
  ministorum → embroidered banner, etc.).
- CLI: `--symbol-style integrated` (default for narrative
  scenes/portraits) vs `--symbol-style flat` (legacy paste-on-top,
  use for diagrammatic / sidebar-icon output).

### Fails (with mitigation)

- **ControlNet path is dead.** Documented above. Code removed.
- **Validator IoU is no longer meaningful in integrated mode.**
  Canny-IoU between the integrated render and the clean canonical
  drops to 0.10-0.45 because the integration legitimately
  transforms edges into scene material. The validator now logs
  IoU informationally on the integrated path; only the flat path
  uses IoU as a FLAG/OK gate. A proper integrated-mode validator
  would need template-matching at multiple scales/rotations or a
  CLIP-similarity check between the rendered region and the
  canonical class label — deferred.
- **Two-pass cost.** Each integrated render is now 2x compute
  (txt2img + img2img). Acceptable on the 3090 (~3-5 min total),
  but not free. The flat path remains as a quick option.
- **Silhouette size sensitivity.** When the silhouette is small
  (< ~150 px on the canvas), pass 2 sometimes "absorbs" it
  entirely into adjacent scene material and the symbol becomes
  invisible. The chapel ministorum at size 76 was visible but
  faint. For now, advise operators to use `large` or `xlarge`
  size labels when the symbol must read at distance.

## 2026-05-07 — Session checkpoint (descriptive)

End-of-session state. The next operator picks up here. Wins and
fails enumerated in detail; do not assume anything is "obviously
working" without re-running it.

### Where we are

Three asset-generation pipelines are wired end-to-end and produce
real artifacts on the ComfyUI server, but **the symbology approach
underneath them is architecturally wrong** and needs to be replaced
before any of the rendered output is shipped to players. Specifically,
the symbol-compose pipeline pastes flat black SVG canonicals on top
of the diffusion render (literal compositing), which is acceptable
for diagrammatic / quick-reference output but visually wrong for the
intended use case: the canonical is supposed to GUIDE the diffusion
to render iconography as scene-integrated material (brass relief on
stone, embroidered banner, painted insignia on armor). The fix is
ControlNet structural guidance — all required ComfyUI nodes are
installed on the server (`ControlNetLoader`, `CannyEdgePreprocessor`,
`LineArtPreprocessor`, `ControlNetApplyAdvanced`, `Canny`,
`InpaintModelConditioning`, `VAEEncodeForInpaint`,
`DifferentialDiffusion`, `SetLatentNoiseMask` — verified) but the
workflow JSON is not built and the driver's compose step is not
rewired. This is the single most important remaining task.

The multi-deck UX helper is also in a bad state: the input it expects
is a fully-detailed hand-painted ship layout (the operator's existing
`spacecraft_default_quantized_v2.png`), and the script adds openings
to it. The shipped deliverables under
`_deliverables/08_multi_deck/` are accordingly MS-Paint-quality
doodles (the operator's words, but accurate). The right design is
to start from a clean SHELL (outer wall + bare floor) and add
deck-specific architecture programmatically.

### Pipeline state, line by line

**Pipeline 0 — battlemap base layer (LANDED, deploy-ready).**
Floor-only mode (`interior --style <archetype> --floor-only`)
produces clean tileable floor textures across 10/10 archetypes at
seed 42. Round 3 + 4 of the iteration log above documents the
findings. The operator's "all single rooms / all square" critique
was answered by the multi-room floor-plan pivot: `make-floorplan`
generates layouts with multiple rooms + corridors + doorways at any
aspect ratio, and `spacecraft --style <archetype>` flows archetype
floor textures through the regional-conditioning workflow. POC
`hab-3room-corridor` rendered at 1792×1024 with three rooms,
central corridor, three doorways, and pixel-aligned walls-only
foreground. The multi-room POC is **the strongest deliverable in
this session** — open `_deliverables/03_battlemap_multi_room/` for
the layout → base → walls → composed walkthrough.

**Pipeline 1 — stamp variants (LANDED, two paths).**
- Geometric rotation (`rotate --method geometric`): pure PIL, no GPU.
  Tested on the 2m932e radar console for south/east/west. Pixel-
  perfect, deterministic, alpha preserved, bbox trimmed to match
  extractor tightness. Use this path for any top-down stamp.
- Condition variants (`condition --variants damaged …`): Flux img2img
  via a CLIENT-PATCHED template. Successfully produced a damaged
  radar console (rust streaks, cracked screen, same subject). Two
  failure modes burned along the way are documented below; the
  current code applies both fixes.

**Pipeline 2 — character portraits (LANDED, but symbol step BROKEN).**
The 8 class profiles (Inquisitor / Acolyte / Tech-priest / Guardsman
/ Preacher / Astropath / Hive-ganger / Civilian) each declare a
prompt template plus per-class symbol placements
(Inquisitor → rosette on chest, Tech-priest → cog, etc).
Per-slot dimensions render at 768×1024 / 768×1280 / 768×1536. The
**token output works** — every portrait emits a 1:1 512×512 crop
from the head/shoulders region using TOKEN_CY_FRAC = 0.30 / 0.20 /
0.13 for bust / three-quarter / full-body, naming convention
`<name>.png` + `<name>_token.png`, sidecar JSON records the crop
box.

**The Inquisitor POC portrait does NOT visibly show a rosette.**
The driver's compose step pasted the rosette canonical at the
declared chest anchor, but on the actual rendered image the result
is a small dark blot on the lower armor that does not read as an
Inquisitorial seal. Two things broke at once: (a) the symbol size
default is too small for a chest-centerpiece role (size_label
`medium` produces a 138-px rosette on a 768-wide canvas — probably
needs `large` or `xlarge`), and (b) the literal-paste approach
itself is wrong (the rosette should appear AS METAL ARMOR RELIEF or
EMBROIDERED ROBE EMBLEM with proper light/shadow integration, not
as a 2D black silhouette glued onto the painting). Fix (a) tunes
sizing; fix (b) is the ControlNet rebuild.

**Pipeline 3 — scene pictures (LANDED, same broken symbol step).**
The chapel POC (`_deliverables/05_scene_pictures/district_4_chapel.png`)
is recognizable as a 40K chapel — pews, candles, arches, dramatic
lighting, painterly oil-painting style. The diffusion render itself
is operator-acceptable. The compose step pasted a literal black-and-
white Aquila on the apse wall and a literal black-and-white
Adeptus Ministorum sigil on the lectern. They are flat SVGs, not
brass reliefs or banners. Same fix as portraits: ControlNet
structural guidance. Until that's done, the symbology path of this
pipeline is unfit for player-facing handouts.

**Pipeline X — multi-deck UX helper (LANDED, BAD DESIGN).**
`make_deck_variants.py` takes a layout PNG and emits N copies with
optional openings. The current script adds without removing, and
the only test input in the vault is the already-fully-detailed
`spacecraft_default_quantized_v2.png` (cockpit windscreen + ramp +
chair + viewport, all hand-painted). The "decks" therefore all
contain the source's interior architecture plus an extra colored
rectangle each. Outputs in `_deliverables/08_multi_deck/` are
accurately described as MS Paint doodles. The right design has
two changes:
1. A `strip-to-shell` mode that takes any layout PNG and outputs
   only the outer hull (wall + bare floor, all interior detail
   removed).
2. Deck-specific architectural builders (programmatic, like the
   `make-floorplan` presets but for ship hulls) — proposed names
   `ship-bridge`, `ship-engineering`, `ship-barracks`,
   `ship-cargo`. Each starts from the canonical shell, paints in
   its specific interior (reactor well, bunk rows, console
   horseshoe, container grid), and shares the outer wall pixel-
   perfect across decks.
3. Render each deck through `spacecraft --style <texture>` to
   produce actual rendered battlemaps, and ship THOSE as the
   deliverable — not the raw doodle inputs.

### Symbology — what's wrong and what's right

**Wrong (current):**
1. Driver renders the scene with anti-symbol negatives — Flux is
   forbidden from drawing Aquila / Inquisition / Mechanicus etc.
2. Driver pastes the canonical PNG onto the rendered image at the
   declared anchor with full alpha.
3. Validator runs canny-IoU between the cropped composite region
   and the canonical (now alpha-masked, so scene edges through the
   canonical's transparent regions don't pollute the score).

The output: a flat 2D black silhouette of the canonical sitting on
top of the diffusion render. Visually wrong: the Aquila on a chapel
apse should look like cast brass relief with light catching the
high points; the Inquisitorial rosette on armor should look like
forged metal inset into the carapace, not a sticker.

**Right (to build):**
1. Driver renders the scene with anti-symbol negatives (same as
   today).
2. For each declared symbol anchor, driver emits a GUIDE IMAGE: a
   black-on-white outline of the canonical at the anchor's
   bounding-box position on a transparent canvas matching the
   render's dimensions.
3. New ComfyUI workflow `ScenePictureControlNetV1.json` runs
   img2img on the rendered scene with the guide image fed through
   `CannyEdgePreprocessor` (or `LineArtPreprocessor` for cleaner
   outlines) → `ControlNetApplyAdvanced` to a Flux-compatible
   ControlNet model.
4. Per-anchor prompt augmentation: "brass relief sculpture of an
   Imperial Aquila on the chapel apse wall, weathered patina,
   candlelight catching the high points" — the prompt drives the
   MATERIAL, the ControlNet locks the SHAPE.
5. Re-validation: canny-IoU between the rendered region and the
   canonical (alpha-masked). Should be HIGHER than the literal-
   paste version because ControlNet preserves topology while the
   diffusion fills in proper material integration.

This needs (a) a new workflow JSON, (b) driver changes to emit
guide images per anchor, (c) replacement of `compose_symbols()` in
the symbol-rendering path of generate_scene_picture.py and
generate_character_portrait.py.

The raw paste path is still useful for diagrammatic output (sidebar
faction badges, journal entry icons, quick-reference handouts) and
should be kept as a separate `--symbol-style flat` mode. The
default for scenes/portraits should be `--symbol-style integrated`
(the new ControlNet path).

### Wins (concrete and verifiable)

1. **Floor-only canonical interior recipe shipped.** 10/10 archetypes
   render clean tileable floors at seed 42. Documented in
   `_deliverables/02_battlemap_floor_only/` with 5 representative
   samples; the full sweep is at `battlemaps/qa/round3_floor/`.
2. **Multi-room floor plans work end-to-end.** 6 presets
   (`hab-2room`, `hab-3room-corridor`, `tunnel-junction`,
   `chapel-nave-with-apse`, `industrial-bay`, `archive-stacks-grid`)
   all produce correct canonical-color layouts. POC hab rendered
   through spacecraft workflow with archetype floor texture and
   walls-only foreground; pixel-aligned for Foundry stack use.
   Open `_deliverables/03_battlemap_multi_room/` to see the
   layout → base → walls → composed walkthrough.
3. **Symbol library (11 canonicals) sourced + validated.** All 11
   load via `symbol_compose.load_symbol()`, rasterize correctly at
   512px, and pass the validate-all sanity check. End-to-end
   smoke test composited Aquila + Rosette + Mechanicus Cog with
   IoU 0.996 / 0.974 / 0.984. Source: Certseeds/wh40k-icon under
   CC-BY-NC-SA 4.0; bundled at
   `symbols/_source/wh40k-icon/LICENSE_CC_BY_NC_SA_V4_0.md`.
4. **State classifier.** CLIP-ViT-L-14 zero-shot with strict
   damage+activation gating lifted vault state coverage from 25%
   to 78.5% across 615 stamps. 326 new state values written, 157
   existing preserved, 132 left null on low confidence. Spot-check
   accuracy ~75-85% on the 4 samples reviewed.
5. **Stamp rotational variants — geometric path.** Pure PIL, no
   GPU. South / east / west of the radar console produced cleanly
   with alpha preservation and bbox trim.
6. **Stamp condition variant — img2img path.** Damaged radar
   console rendered correctly after two failed iterations (root
   causes documented in fails section).
7. **Token cropping for actor portraits.** Foundry actor-token
   convention working; 1:1 512×512 crop from head/shoulders region
   per-slot. Sidecar JSON records crop box for reproducibility.
8. **Anti-symbol negatives in diffusion prompts WORK.** Flux did
   NOT draw mangled Aquilae / cogs / fleur-de-lys in any of the
   chapel / inquisitor renders. The negative prompt list at
   `SCENE_NEG_T5` / `PORTRAIT_NEG_T5` is effective. This is a
   prerequisite for the ControlNet rebuild — the diffusion stays
   "blank" where we want to stamp/composite the canonical.

### Fails (concrete, with root cause)

1. **Symbology pasted instead of integrated.** This is THE failure
   of the session, called out explicitly by the operator. The
   chapel Aquila is a flat black SVG glued onto stained glass.
   The Inquisitor's rosette is a small dark blot on lower armor
   that doesn't read as an Inquisitorial seal. Root cause: I built
   the simplest thing (literal alpha-composite of canonical) when
   the spec required structural guidance to render iconography in
   scene material. Fix: ControlNet pipeline (described above).

2. **Multi-deck deliverables are MS Paint doodles.** The "decks"
   in `_deliverables/08_multi_deck/` are the same fully-detailed
   hand-painted spacecraft layout with one extra colored rectangle
   added per deck. Not real deck-specific architecture. The
   operator was direct about this, accurately. Root cause: the
   `make_deck_variants.py` script takes a layout PNG and adds
   openings; the only test input was a fully-detailed single-deck
   layout, and the script adds without removing. Fix: programmatic
   ship-deck presets (build to come) + run them through the
   spacecraft workflow before shipping. Tasks 23, 24 are queued
   for this work.

3. **Inquisitor portrait does not visibly show the rosette.** The
   compose step ran (sidecar JSON records the placement at
   x=315, y=565, size=138, IoU 0.632 FLAG), but on the actual
   image the rosette is a small dark blot on the lower armor — not
   visually a seal. Two interacting causes: (a) symbol size too
   small for a chest centerpiece role on a 768×1024 portrait, and
   (b) the literal-paste approach doesn't read as armor inlay even
   when the silhouette is correct.

4. **Symbol IoU validator over-flags symbols with sparse internal
   alpha.** Rosette and Adeptus Ministorum both have lots of
   negative space inside the symbol's outer outline. When
   composited over a busy scene, the underlying scene's edges leak
   through these negative-space regions and tank the IoU score.
   The chapel POC's first run flagged both at 0.70 / 0.60; after
   the alpha-mask fix to `_canny_iou()`, re-validation came back
   at 0.942 / 0.887. But for symbols with truly sparse internal
   alpha (the rosette case in the inquisitor portrait, IoU 0.632),
   the alpha-mask helps but doesn't fully solve it. Fix candidates:
   per-symbol threshold tuning, ERODED alpha mask (only score the
   "thick" parts of the canonical), or skip canny-IoU for these
   symbols and use template-matching instead.

5. **First img2img workflow built from scratch produced noise.**
   Two iterations of mosaic-noise output. Root cause stack:
   (a) initial cfg=1.0 was wrong for Chroma (vs the proven
   txt2img's cfg=3.5); (b) sampler/scheduler were wrong (used
   euler/simple instead of res_multistep/beta); (c) even with
   sampler config corrected, hand-built workflow still produced
   noise — there's something in the saved template (model_sampling
   node? Chroma-specific Flux quirks?) that the from-scratch JSON
   missed. **Fix that worked**: load the proven template, patch in
   LoadImage + VAEEncode, rewire `KSampler.latent_image`, drop
   `EmptyLatentImage`. Mirror of how `generate_battlemap.py`
   uses `load_template()` + `set_prompt()` patches.

6. **Stamps under ~512px short-edge under-resolve at Flux's latent
   scale.** Source stamps are ~128 px; VAE-encoded latent is
   ~16×16 channels, which is below Flux's effective resolution
   floor and decodes to garbage. Fix: pre-upscale to 512 px short-
   edge, white-flatten alpha, run img2img, resize back, restore
   source's alpha mask. Now the standard path in
   `_preprocess_for_img2img()`.

7. **Spacecraft floor texture subtler in regional conditioning
   than standalone.** The hab POC base (`02_base.png`) shows hab
   floor mottling but it's quieter than the standalone
   `interior --floor-only --style hab` render. Regional
   conditioning splits guidance budget across all 5 regions
   (wall + floor + ramp + windscreen + lighting), so the floor
   prompt has ~1/5 the effective weight. v2 prompt iteration
   (front-loaded distinctive nouns, "high contrast" hint) helped
   but didn't close the gap. Fix candidates: boost the floor
   conditioning node's strength in the workflow JSON, or accept
   the ceiling.

8. **Chapel `--floor-only` decorative-trim cosmetic.** Round 4
   polish reduced but did not eliminate a thin gilded border at
   top + bottom edges of the chapel floor. The chapel iconography
   prior is a strong Flux signal that resists prompt suppression.
   Operator-acceptable; logged as known minor artifact.

9. **No source SVG yet for `cult_imperialis_flame` and
   `skull_laurel`.** The 11 canonicals from wh40k-icon don't
   include these two. README documents game-icons.net flame.svg
   (CC-BY 3.0) as an interim option, or operator-supplied SVGs.
   Until then, validate-all reports them as MISSING.

10. **Foundry V14 live-scene stackability test still PENDING.**
    All assets staged at `dh-cartography/battlemaps/hab_3room_*.png`
    but the operator-UI confirmation hasn't happened. Need to drag
    base into Background, walls-alpha into Foreground, drop a
    token, confirm the foreground occludes the token at the right
    elevation.

### Outstanding work (priority order for next session)

1. **ControlNet symbology pipeline.** Replace the literal-paste
   path with structural guidance. New workflow file
   `ScenePictureControlNetV1.json`. Driver changes in
   `generate_scene_picture.py` and `generate_character_portrait.py`
   to emit guide images and feed them to the ControlNet apply
   chain. Re-render the chapel scene with brass-relief Aquila
   integrated into the apse stone, and the inquisitor portrait
   with the rosette as armor inlay. Task #25.

2. **Programmatic ship deck layout presets.** Add `ship-bridge`,
   `ship-engineering`, `ship-barracks`, `ship-cargo` to
   `FLOORPLAN_PRESETS` with shared outer hull dimensions and
   deck-specific interior architecture (reactor well, bunk rows,
   console horseshoe, container grid). Task #23.

3. **Render multi-deck through spacecraft workflow.** Each
   ship-* preset → `spacecraft --style <deck-texture>` → rendered
   battlemap. Replace `_deliverables/08_multi_deck/` with these
   rendered PNGs (move the doodles into `_intermediate/` if kept
   at all). Task #24.

4. **Re-render the 5 deliverable POCs** with the corrected
   symbology pipeline once it's built (chapel, inquisitor bust,
   anything else where symbols matter).

5. **Stamp variant accuracy spot-check on diverse subjects.**
   The radar console damaged variant works, but radar consoles
   are detail-rich. Test on softer subjects (chair, parchment
   document, soft fabric banner) — different denoise strengths
   may be needed per subject class.

6. **Symbol sources for `cult_imperialis_flame` and
   `skull_laurel`** — operator-supplied or game-icons.net fallback
   approved.

7. **Foundry V14 live-scene test** — assets are staged; needs
   ~5-min operator UI session.

8. **Symbol IoU validator for sparse-alpha symbols** — eroded
   mask or template-matching path. Low priority compared to the
   ControlNet rebuild, since the validator is metadata, not
   gating any actual rendering.

9. **Stamp generative rotation** (asymmetric subjects). Geometric
   covers most cases; deferred until needed.

10. **ControlNet OpenPose** for explicit portrait poses, and
    **IPAdapter face consistency** for recurring NPCs across
    multiple portraits. Both deferred; the current prompt-only
    path is operator-acceptable for one-off portraits.

11. **LoRA training** — operator's offered material not used yet.
    Reserve for after ControlNet path is built and we know what
    the residual style gap actually is.

### File pointers for the next operator

| Path | Purpose |
| --- | --- |
| `generate_battlemap.py` | Battlemap pipeline (floor-only, multi-room, spacecraft regional). |
| `generate_scene_picture.py` | Pipeline 3 — uses literal paste. Rebuild's symbol step. |
| `generate_character_portrait.py` | Pipeline 2 — uses literal paste. Rebuild's symbol step. |
| `generate_stamp_variants.py` | Pipeline 1. Rotation + condition variants both working. |
| `symbol_compose.py` | Library API + CLI for canonical symbol composite/validate. KEEP for diagrammatic uses; ADD a controlnet-guide-image emit function. |
| `symbols/<name>/canonical.png` | 11 canonicals validated end-to-end. |
| `make_deck_variants.py` | BAD DESIGN. Replace with strip-to-shell + ship-deck presets. |
| `qa_topdown.py` | Floor-only QA harness. Working. |
| `classify_state.py` | State classifier. Working. |
| `_deliverables/` | Current shipped artifacts. 08_multi_deck/ is misleading; delete or move to `_intermediate/` when rebuilding. |
| `workflows/BattlemapInteriorV1.json` | Proven Flux txt2img template. Patch this, don't author from scratch. |
| `workflows/BattlemapSpacecraft.json` | Proven Flux img2img regional-conditioning template. |
| `workflows/ScenePictureControlNetV1.json` | TO BUILD. Add Canny → ControlNet apply chain. |

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
