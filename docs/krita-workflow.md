# Krita generative-editing workflow (tooling goal T1)

Operator's notebook for the interactive Krita ↔ ComfyUI round-trip.
Status: **setup notebook — not yet stood up.** This file is the plan
and the running record; update it with wins/fails the same way
`battlemap-workflow.md` is maintained. Nothing below is a claim that
the integration is live.

## Why this exists

The scripted pipeline (`generate_battlemap.py`,
`generate_character_portrait.py`, the SAM2-point → inpaint and
localized-inpainting levers) produces assets in *batch*, blind. Many
of the hard-rule fidelity fixes in `CLAUDE.md` are inherently
*interactive*: repaint an Aquila to canonical shape, lift portrait
detail in one region, cut a damaged/destroyed variant of a stamp,
hand-tune a layout. Goal **T1** makes those hand-guided by wiring
Krita to the same generative backend the batch pipeline already uses.

## Architecture

```
Krita  ──(krita-ai-diffusion plugin)──►  ComfyUI backend
 .kra layer stack                        http://198.51.100.11:8188
 (masks, live-paint, refine)             RTX 3090, ComfyUI V0.18.1
        ▲                                Chroma-unlocked-v35 (Flux deriv.)
        │                                Florence-2, CLIP-ViT-H, IPAdapter
        └── export flattened PNG ──►  tracked, deployed deliverable
```

The backend, models, and canonical Foundry origin are the ones
documented in the top-level `README.md` and `CLAUDE.md`. Krita becomes
a second *client* of that backend — it does not stand up its own.

## Setup plan (verify each step on first run)

1. **Install `krita-ai-diffusion`** (Acly) into Krita's plugin dir;
   enable the docker.
2. **Point it at the existing ComfyUI server**, not a bundled local
   one: configure the plugin's server mode as *Custom / remote* with
   URL `http://198.51.100.11:8188`. **Verify the plugin can reach the
   remote server** (connection status green) before anything else —
   this is the most likely failure point.
3. **Confirm the base model is selectable.** The batch pipeline renders
   on `Chroma-unlocked-v35` (a Flux derivative). Confirm the plugin's
   Flux workflow can drive it, or select the nearest compatible
   checkpoint the server exposes. Record what actually worked.
4. **LoRA selection** (once goal #1 lands): trained campaign
   `.safetensors` live in the server's `models/loras/`. Confirm they
   appear in the plugin's LoRA picker so edits can stack
   `<lora:wh40k_*:…>` at the same strengths the batch pipeline uses.

## File convention (decided 2026-07-24)

- **Master:** `<Name>.kra` **beside** its exported PNG
  (`Maps/FinalChapel.kra` ↔ `Maps/FinalChapel.png`;
  `Characters/<Name>.kra` ↔ `Characters/<Name>.png`).
- **Tracked deliverable:** the exported **PNG** only. The `.kra` is
  **gitignored** (`*.kra` in the vault `.gitignore`) — a large,
  binary, local-only master; back it up out-of-band.
- **Never tracked:** autosaves / backups (`*-autosave.kra`, `*~`).
- Export = flatten the `.kra` to the PNG that Foundry/Kanka serve; the
  generative layers stay in the `.kra` for future edits.

## Round-trip (once live)

1. Open the deployed PNG (or a fresh canvas) as a `.kra` beside it.
2. Mask the region to change; run inpaint/refine through the plugin
   against the backend. Iterate on layers — the `.kra` keeps history.
3. Judge against the Solenne-grade bar (open a deployed `SOLENNE_*.png`
   or `Characters/` reference alongside). The edit must read as painted
   material, not a pasted overlay.
4. Export the flattened PNG over the deliverable; commit the PNG.

## Use cases mapped to deliverable goals

- **#9 scenes / iconography** — repaint an Aquila or Rosette to
  canonical shape as brass relief / embroidery (the recurring
  hard-rule failure the batch path keeps missing).
- **#8 portraits** — localized detail lift on face / fabric / armour
  seams toward the deployed Edric-family / Pell-Osric bar.
- **#7 stamps** — inpaint intact → damaged → destroyed variants that
  share a subject (real re-renders, grouped by `group_id`).
- **#1 / #10 battlemaps** — hand-paint or fix a layout before feeding
  the region-conditioning / ControlNet render path.

## Open questions for the operator

- Remote-access shape: does the plugin talk to the bare ComfyUI at
  `198.51.100.11:8188` directly, or does it need a reachable-origin /
  CORS allowance the way Foundry does? Resolve on first connect.
- Sequencing vs goal #1: prove T1 on stock Chroma-Flux first, or wait
  until the first campaign LoRA is trained so edits carry campaign
  style from day one?
- Queue discipline: the 3090 is one queue (per `README.md`) — Krita
  interactive jobs and batch renders / classification contend. Agree a
  convention (don't run classification or battlemap batches while
  hand-editing).
