# Scene generation LoRA

Trigger: `dh_scene`. Project end-goal #9 — narrative scene art for
chapels, sanctums, war rooms, audience halls, scriptoria,
manufactorum bays, archives, refectories, etc.

## Architecture — iconography stacks at inference

This LoRA learns scene-type composition + dressing + lighting +
material palette + camera angle. **It does NOT learn iconography.**
Imperial / Inquisitorial symbols come from the trained iconography
LoRA, stacked at inference:

```
<lora:dh_scene:0.7> <lora:wh40k_iconography:0.6>
dh_scene, chapel nave, candlelit chiaroscuro, eye-level,
sym_aquila brass relief on the apse wall
```

Captions in the corpus exclude any reference to aquilas / rosettes
/ cogs and the prompt explicitly tells Gemini to leave space for
iconography (banners, walls, surfaces stay appropriate but bare of
named symbols). This is the same axis-discipline rule that applies
to all four other LoRAs — each one binds one axis only.

## Why this LoRA matters

The 2026-05-08 review post-mortem (in `../../docs/battlemap-workflow.md`,
"2026-05-07 — Review post-mortem") flagged that local Chroma-Flux
cannot do high-fidelity 40K iconography integration on its own;
Gemini-via-iconography-LoRA can. This scene LoRA is the
counterpart: it learns the architectural / atmospheric / tonal
vocabulary of 40K interiors so the iconography LoRA has a
canonical surface to be stamped onto.

## Matrix axes

| Axis        | Pool size | Purpose |
|-------------|-----------|---------|
| scene_type  | 10        | Anchor — what the room IS (chapel nave, sanctum, etc.) |
| dressing    | 8         | How the room is appointed (sparse / lavish / utilitarian / ...) |
| material    | 6         | Surface palette (stone+iron / marble+wood / ferrocrete+steel / ...) |
| lighting    | 6         | Illumination character (candlelit / sodium / blue-white / red emergency / ...) |
| angle       | 5         | Camera POV (eye-level / elevated / ground-up / centered / off-axis) |
| treatment   | per-scene | Specific composition refinements (e.g. "central altar, side chapels in shadow") |

Round-robin sampling — every (treatment) gets a unique
(dressing × material × lighting × angle) tuple.

## Cost

10 scene types × ~6–7 treatments each ≈ 65 variants × $0.04 ≈ $2.60.

Smoke (one per scene type, $0.40) first, then full corpus on
operator approval.

## Status

- Manifest + handler scaffolded.
- Corpus NOT generated — paused on Gemini API prepayment depletion
  (see most recent `## YYYY-MM-DD` heading in
  `../../docs/battlemap-workflow.md`).
- When budget returns:
  ```
  uv run corpus_generator.py --lora scenes --dry-run
  uv run corpus_generator.py --lora scenes --limit 10  # smoke
  uv run corpus_generator.py --lora scenes             # full
  ```

## Files

```
scenes/
├── README.md                ← this file
├── manifest.yaml            ← scene-type catalogue + matrix axes
└── scene-<type>/            ← per-scene-type PNG + .txt caption pairs
    ├── scene-chapel-nave/
    ├── scene-chapel-apse/
    ├── scene-sanctum/
    ├── scene-audience-hall/
    ├── scene-war-room/
    ├── scene-scriptorium/
    ├── scene-manufactorum-bay/
    ├── scene-archive-stacks/
    ├── scene-refectory/
    └── scene-dormitorium/
```
