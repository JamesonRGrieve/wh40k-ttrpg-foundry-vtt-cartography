# 02_battlemaps — 4 new SOLENNE_*.png interiors

Pipeline: `generate_battlemap.py interior --style <archetype>` (Chroma-Flux txt2img
through BattlemapInteriorV1 with anti-frame negative). 1024×1024.

| File | Style | Seed | Tied NPC | Tied location |
| --- | --- | --- | --- | --- |
| SOLENNE_the_sump.png | bar | 42 | Tasker (`01_portraits/Tasker_bust.png`) | `[[The Sump]]` |
| SOLENNE_district4_chapel.png | chapel | 13 | Garrick Varo (`01_portraits/Garrick_Varo_bust.png`) | `[[District 4 Chapel]]` |
| SOLENNE_hab4_medicae_post.png | medicae | 7 | — | `[[Hab District 4 Medicae Post]]` |
| SOLENNE_pdf_garrison.png | garrison | 19 | Kael Edric | `[[PDF Garrison]]` |

## Reference for comparison

`../07_reference/SOLENNE_section7_maintenance_tunnels.png` and
`../07_reference/SOLENNE_block9_unit14_edric_residence.png`. Both
deployed; both at 1024² or larger; both painterly.

## Operator decision needed

Style match check: each new map should read at the same painterly
oil tier as the two deployed references. Reject anything that reads
as schematic / flat / line-art.
