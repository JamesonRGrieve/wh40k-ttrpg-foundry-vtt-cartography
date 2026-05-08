# 01_portraits — 7 NPC bust + token pairs

Pipeline: `generate_character_portrait.py` two-pass txt2img → img2img
integration. Pass 1 = BattlemapInteriorV1 Chroma-Flux txt2img with
class profile prompt + anti-symbol negative. Pass 2 = composite
class-symbol silhouette over the render, then img2img repaint at
denoise=0.45 with material-hint prompt augmentation.

Token = 512×512 1:1 crop centered on per-slot face fraction
(bust: cy=0.30) and resampled with PIL LANCZOS.

| File | Subject | Class | Symbol target | Seed | Notes |
| --- | --- | --- | --- | --- | --- |
| Denn_Varo_bust.png | Lay preacher (M, late 50s) | preacher | adeptus_ministorum on robe | 42 | Ministorum sigil rendered as embroidered detail |
| Keller_bust.png | Shopkeeper (M, late 50s) | civilian | aquila collar pendant | 42 | Pendant rendered small (medium symbol scale) |
| The_Handler_bust.png | Lord Inquisitor | inquisitor | inquisition_rosette on chest | 7 | Rosette rendered as embossed armor inlay |
| Veyra_Sildt_bust.png | Astropath (F, early 40s) | astropath | none | 42 | Skull-faced sealed-eyes astropath |
| Mira_Dross_bust.png | Scholam admin (F, late 40s) | civilian (--gender female --age "late 40s") | aquila collar pendant | 11 | Rendered after gender flag added — first attempt was masculine. |
| Tasker_bust.png | Dock loader / smuggler | hive-ganger | none | 23 | Stitched leather/salvage armor |
| Bram_Stroker_bust.png | Spaceport night supervisor | civilian | aquila collar pendant | 5 | IoU 0.650 on the pendant — symbol survived strongly |

## Reference for comparison

`../07_reference/_deployed_inquisitor.png` — already-deployed
test_inquisitor_v2.png, generated through the same pipeline. The
embossed rosette on the chest carapace is the integrated-iconography
target for the inquisitor class.

`../07_reference/_deployed_corvin_edric.png` — Corvin Edric ("the
father") portrait. The subtle gold thread embroidery on his robe is
the integrated-iconography target for civilian/preacher classes.

## Operator decision needed

For each portrait: **accept** (move into `Characters/portraits/`
Final), **regenerate** (different seed / class / symbol), or
**reject** (drop entirely).
