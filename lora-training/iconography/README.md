# 40K iconography LoRA — training data

Curated reference images for a 40K iconography LoRA. **Shape
vocabulary, not style.** When trained, this LoRA gets stacked at
inference with whatever style anchor the render needs (Solenne
painterly, Necromunda gritty, codex-clean line art, etc.) so the
canonical symbol shapes render correctly regardless of aesthetic.

Reusable across all 7 wh40k-rpg game systems (BC, DH1, DH2, DW, OW,
RT, IM) and any future 40K project — iconography is a 40K constant.
See `cartography/CLAUDE.md` "Tooling decisions" for the rationale.

## Folder structure (one folder per canonical symbol)

| Folder | Symbol | Trigger token (suggested) |
| --- | --- | --- |
| iconography-aquilla/ | Imperial Aquila | `sym_aquila` |
| iconography-rosette/ | Inquisitorial I/Rosette | `sym_inq_rosette` |
| iconography-mechanicus-cog/ | Mechanicus opus (half-cog half-skull) | `sym_mech_cog` |
| iconography-skull-winged/ | Astra Militarum winged skull | `sym_militarum_winged_skull` |
| iconography-fleur-de-lys/ | Adepta Sororitas fleur-de-lys | `sym_sororitas_lys` |
| iconography-ministorum-sigil/ | Adeptus Ministorum sigil | `sym_ministorum` |
| iconography-administratum-sigil/ | Adeptus Administratum sigil | `sym_administratum` |
| iconography-arbites-sigil/ | Adeptus Arbites scales-and-fist on I | `sym_arbites` |
| iconography-astropath-eye/ | Astra Telepathica / Astropath eye-on-I | `sym_telepathica_eye` |
| iconography-navy-sigil/ | Imperial Navy winged-cog-eagle | `sym_imperial_navy` |
| iconography-rogue-trader/ | Rogue Trader insignia | `sym_rogue_trader` |
| iconography-pariah/ | Pariah / Untouchable cross-and-eye-and-skull | `sym_pariah` |
| iconography-psyker/ | Psyker (Inquisitorial I + warp aura) | `sym_psyker` |
| iconography-mutant/ | Mutant DNA-helix-with-skull | `sym_mutant` |
| iconography-outcast/ | Outcast skull-and-broken-chains | `sym_outcast` |
| iconography-chaos-star/ | Chaos eight-pointed star | `sym_chaos_star` |

`iconography-aquilla` retains its original spelling because the
operator created the folder. The trigger token uses the canonical
spelling (`sym_aquila`).

## Per-image caption convention

Every `.png` should have a sibling `.txt` file with the same stem.
Flux LoRA trainers (ai-toolkit, sd-scripts) read the `.txt` content
as the image's caption. Format:

```
<trigger_token>, <symbol_name>, <shape_description>, <material/state/context>
```

Examples:
- `sym_aquila, Imperial Aquila, two-headed eagle with wings spread heraldic, brass relief on stone floor inlay`
- `sym_inq_rosette, Inquisitorial I, two-headed eagle perched on I-bar with skull at center, weathered brass`
- `sym_mech_cog, Mechanicus opus, half-cog half-skull, rusted brass`

**What to put in the caption (helps the LoRA bind shape):**
- Trigger token (so you can summon the symbol by name at inference)
- Symbol's canonical name
- Shape description (what makes the silhouette recognizable)
- Material / state when distinctive (brass relief, etched stone, embroidered, weathered)

**What NOT to put (would bind unwanted properties to the trigger):**
- Style descriptors (painterly, oil painting, grimdark) — those
  belong in the *style anchor* at inference time, not in the
  iconography LoRA.
- Scene context unless the symbol IS in a scene (chapel, barracks).
  Pure isolated plates should be captioned without scene context.

## How much training data per symbol

Diffusion LoRA convergence on a clean isolated symbol with neutral
backgrounds: typically **8-15 reference images per concept token**.
The current state of the folder (1-2 images per symbol) is
**proof-of-concept seed**, not training-ready volume. Suggested
expansion per symbol (in priority order):

1. The current isolated-on-neutral plate (kept).
2. 4-6 material variants: brass relief, etched steel, stamped
   pewter, embroidered gold thread, carved wood, engraved silver,
   stone inlay, gilt parchment.
3. 2-4 state variants: clean / weathered / damaged / moss-covered.
4. 2-3 context variants: on a banner, on a chest plate, on a
   wall plaque (these teach scale and placement).

Total: ~10-15 images per symbol × 16 symbols = ~150-240 images for
a fully-trained unified iconography LoRA.

## Trainer recipe (sketch)

For Flux LoRA on the 3090 (24GB):

- **ai-toolkit** (`ostris/ai-toolkit`) — recommended for Flux. Run
  on the same ComfyUI server. YAML config, single GPU, ~6-12h on
  this dataset size.
- Alternative: **sd-scripts** with `sdxl_train_network.py` adapted
  for Flux (`flux_train_network.py` exists in newer forks).

Base model: Chroma's Flux-derivative checkpoint already on the
ComfyUI server.

LoRA params (starter values, tune from there):
- `rank: 16` (small enough to converge fast on small dataset)
- `learning_rate: 1e-4`
- `network_alpha: 16`
- `train_batch_size: 1`
- `num_repeats: 10` per image
- `epochs: 10-20`
- `resolution: 768` (matches our portrait latent)

After training, drop the resulting `.safetensors` into ComfyUI's
`models/loras/` and trigger via prompt:
```
<lora:wh40k_iconography:0.8>, sym_aquila on the chapel apse,
warhammer 40000 grimdark, painterly oil painting, ...
```
