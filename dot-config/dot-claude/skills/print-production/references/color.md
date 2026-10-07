# print-production — color (reference)
Read when setting up colour, profiles, ink limits or rich black. Parent: `print-production` SKILL.md.

## 4. Color
`color-management` owns color: output conditions, ICC profiles and their TAC (its §2); RGB→CMYK conversion, 100K and rich black, ink-limit checks, spot and Pantone (its `references/print-cmyk-spot.md`). Use exactly the printer's condition (a FOGRA39 job is never converted with FOGRA51). Prepress specifics:
- Rich black stays under 270% on wrap films.
- Small reversed (white) text in rich black shows color fringes when plates misregister: use bolder/larger type, a 100K background, or ask whether the RIP chokes CMY around knockouts.
- TAC traps are hand-built CMYK: rich blacks, multiply/shadow stacks over dark colors, overprinting builds. Converted images obey the profile's TAC automatically.

Overprint, knockout, trapping:
- Everything knocks out except 100K small text/rules and technical spot layers (overprint).
- White or [Paper] objects set to overprint vanish in print: the classic missing-logo failure. Preview with View › Overprint Preview and Window › Separations Preview; Acrobat Output Preview "Simulate Overprinting"; Ghostscript `-dOverprint=/simulate` (§7).
- Trapping is done in the RIP in modern workflows; do not build manual traps unless asked (they double up). Exceptions: separations you output yourself (screen printing, some flexo) and abutting spot colors: spread the lighter color under the darker.
