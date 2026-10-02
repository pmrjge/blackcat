# print-production — color (reference)
Read when setting up colour, profiles, ink limits or rich black. Parent: `print-production` SKILL.md.

## 4. Color
Output conditions (TAC = maximum total area coverage, C+M+Y+K):

| Condition | ICC profile | Characterization | TAC |
|---|---|---|---|
| Offset, premium coated (EU, current) | PSO Coated v3 | FOGRA51 | 300% |
| Offset, coated (EU, still widely requested) | ISO Coated v2 (ECI) / ISO Coated v2 300% (ECI) | FOGRA39 | 330% / 300% |
| Offset, wood-free uncoated (EU) | PSO Uncoated v3 | FOGRA52 | 300% |
| Sheetfed coated (US) | GRACoL2013_CRPC6 | CGATS.21-2 CRPC6 | 320% |
| Web coated (US) | SWOP2013C3_CRPC5 | CGATS.21-2 CRPC5 | 300% |
| Newsprint | the paper's WAN-IFRA/ISO newspaper profile | ISO 12647-3 | much lower; ask |

- Use exactly the printer's condition: a FOGRA39 job must not be converted with FOGRA51. ECI profiles come from eci.org, GRACoL/SWOP from Idealliance or the ICC registry.
- Convert once, late, with the right profile. Either keep RGB images plus an output intent (PDF/X-4 allows it) or convert them (Photoshop Edit › Convert to Profile; in Illustrator set Edit › Color Settings working CMYK before changing Document Color Mode). On PDF export use Output › Convert to Destination (Preserve Numbers) so native CMYK stays untouched. Intent: relative colorimetric with black point compensation by default; perceptual for images with a lot of out-of-gamut color.
- Pure RGB black converts to four-color black (tested with Ghostscript defaults: about 72/67/67/88 = 294%). Set text, rules and barcodes to 100K explicitly. CMYK→CMYK re-conversion does the same to 100K text unless black is preserved; check the plates afterwards.

Black:
- 100K for body text, anything under 12 pt, thin rules and barcodes, set to overprint (many RIPs overprint 100K text automatically; don't rely on it).
- Rich black only for large solids, with the printer's recipe; a common one is C60 M40 Y40 K100 (240%); cooler C60 K100, neutral-warm C30 M30 Y30 K100. Keep it under the TAC (and under 270% on wrap films).
- Small reversed (white) text in rich black shows color fringes when plates misregister: use bolder/larger type, a 100K background, or ask whether the RIP chokes CMY around knockouts.
- TAC traps are hand-built CMYK: rich blacks, multiply/shadow stacks over dark colors, overprinting builds. Converted images obey the profile's TAC automatically.

Spot colors and Pantone:
- Pantone books in Illustrator need the Pantone Connect plugin (all books were removed by the October 2023 release; existing files keep their swatches).
- The suffix is the paper: C coated, U uncoated; the same number looks different. For CMYK builds use Pantone's CMYK guide values (Color Bridge), not the app's silent conversion, and tell the client it is an approximation.
- One swatch per ink with identical names in every placed file ("PANTONE 186 C" and "PANTONE 186 CP" make two plates). Check plates in Separations Preview; convert unintended spots to process. Brand colors as Global swatches.

Overprint, knockout, trapping:
- Everything knocks out except 100K small text/rules and technical spot layers (overprint).
- White or [Paper] objects set to overprint vanish in print: the classic missing-logo failure. Preview with View › Overprint Preview and Window › Separations Preview; Acrobat Output Preview "Simulate Overprinting"; Ghostscript `-dOverprint=/simulate` (§7).
- Trapping is done in the RIP in modern workflows; do not build manual traps unless asked (they double up). Exceptions: separations you output yourself (screen printing, some flexo) and abutting spot colors: spread the lighter color under the darker.
