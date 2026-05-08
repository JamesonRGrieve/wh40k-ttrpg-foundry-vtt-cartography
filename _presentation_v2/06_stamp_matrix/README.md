# 06_stamp_matrix — Cogitator Console matrix demo

Demonstrates the stamp matrix variation pattern (goal 7). Group
4325bfec-db34-5426-afd6-54e30220b3ad (Cogitator Console) had 3
members covering north orientation across {active, inactive,
destroyed}. Missing: damaged state and east/south/west orientations.

This pass added 4 supplemental variants:

| File | Source | Method | Orientation | State |
| --- | --- | --- | --- | --- |
| cogitator_console_north_active.png | (parent) | original Gemini grid extract | north | active |
| cogitator_console_north_inactive.png | (parent) | original Gemini grid extract | north | inactive |
| cogitator_console_destroyed.png | (parent) | original Gemini grid extract | (none) | destroyed |
| cogitator_console_north_damaged.png | _01.png | generative img2img, denoise=0.55, seed=42 | north | damaged |

**The pure 90/180/270° geometric rotation files (south/east/west) that
this folder originally contained have been deleted** per the new
"Hard rule" in `cartography/CLAUDE.md`: Foundry rotates tiles freely
at runtime, so storing 4× copies of identical pixels is 4× storage
for zero gameplay benefit. Only state changes (intact ↔ damaged ↔
destroyed) and activation changes (active ↔ inactive) remain as
persisted variants — those are real re-renders with different
pixel content.

All seven sidecars share the parent's group_id, so Foundry's Mass
Edit Preset Browser groups them as a coherent variant matrix.

## Operator decision needed

- Pattern correctness: does this matrix shape match how you intend
  to filter/cycle variants in Foundry?
- Scaling: 502 grouped stamps have similar matrix gaps. Generalizing
  this approach requires (a) extending make_sidecars.py NAME_RE to
  accept synthesized-variant suffixes, (b) running a gap-detection
  pass over the 502 groups, (c) generating + sidecaring at scale.
  Worth doing? Or scope to specific high-frequency groups
  (chairs, lockers, consoles, crates)?
