---
name: color-management
description: Load before choosing, converting or checking colors for a deliverable — ICC profiles, CMYK, Pantone/spot, ΔE2000, OKLCH, WCAG contrast.
---
# Color management

## Scope
Color spaces and ICC profiles, conversions for print, spot colors, color difference, perceptual palettes,
contrast, dark mode, calibration, soft-proofing and tagging exports. Not here: PDF/X export and preflight
(`print-production`), chart palettes (`data-visualization`), brand color strategy (`brand-identity`).

Tools: Pillow `ImageCms`, ColorAide and colour-science (`uv run --with coloraide --with colour-science …`),
ImageMagick, macOS `sips`; Illustrator MCP (`get_colors`, `get_separation_info`, `get_overprint_info`,
`check_contrast`, `manage_swatches`, `export_pdf` with `output_intent_profile`); the huetension color MCP
server: `color.convert` (hex/RGB/HSL/HSV/Lab/LCH/OKLab/OKLCH), `harmony.generate`, `gradient.generate`
(OkLab/OkLCH interpolation), `palette.random` (seedable), `contrast.check` (WCAG 2.1 and APCA; `suggest=true`
returns the nearest passing OKLCH lightness), `blindness.simulate`, `image.extract`, `export.css`,
`export.tailwind`; ASE/ACO swatch files come from its CLI's palette commands (`-f ase -o brand.ase`; see
`huetension <cmd> --help`). huetension does no ICC/CMYK conversion and no ΔE: use Python for those.

## 1. Ground rules
- A number without a color space is not a color. HEX and `rgb()` in CSS, SVG and untagged web images mean
  sRGB. CMYK numbers mean something only together with a named printing condition (profile).
- ICC PCS, CSS `lab()`/`lch()` and ColorAide's `lab` are D50; colour-science's `XYZ_to_Lab` defaults to D65:
  pass the illuminant and adapt before comparing with Pantone or ICC Lab values.
- Gamuts differ in shape, not only size: saturated RGB blues, greens and oranges fall outside offset CMYK;
  some CMYK cyans and many spots (bright oranges/greens, fluorescents, metallics) fall outside sRGB. Decide
  per color which space is the reference and document the compromise in the others.
- Convert once, from a tagged source, as late as possible. Keep masters: 16-bit RGB for images, the spot or
  Lab definition for brand colors.

## 2. Choose the profile
| Deliverable | Profile (characterization) | TAC in profile | Notes |
|---|---|---|---|
| Web, UI, social, slides, video stills | sRGB IEC61966-2.1 | — | Default for anything on screen |
| Wide-gamut screen (Apple apps, P3 web) | Display P3 | — | Keep an sRGB fallback; CSS `color(display-p3 …)` + `@media (color-gamut: p3)` |
| Photo/retouch master | Adobe RGB (1998) or ProPhoto, 16-bit | — | Convert per output at the end |
| Offset coated, Europe (ISO 12647-2:2013) | PSO Coated v3 (FOGRA51) | 300 %, max K 96 % | ECI successor to ISO Coated v2 |
| Offset coated, legacy or unknown | ISO Coated v2 (ECI) (FOGRA39L) / `ISOcoated_v2_300_eci.icc` | 330 % / 300 % | ECI: the 300 % variant is a good choice when conditions are unknown |
| Offset uncoated, Europe | PSO Uncoated v3 (FOGRA52) | 300 % | Wood-free uncoated, with brighteners |
| Offset, US premium coated | GRACoL2013_CRPC6 | 320 % | CGATS 21-2 / ISO 15339 |
| Offset, US publication (web) | SWOP2013C3_CRPC5 | 300 % | |
| Offset, US uncoated | GRACoL2013UNC_CRPC3 | 280 % | |
| Newspaper (coldset) | WAN-IFRAnewspaper26v5 (ISO 12647-3:2013); US: CGATS21_CRPC1 | low; CRPC1: 240 % | Use the paper's own limit |
| CMYK exchange, unknown digital press | eciCMYK v2 (FOGRA59) | — | Exchange space; still ask the printer |

ISO 15339 CRPC1–7: coldset news, heatset news, premium uncoated, supercalendered, publication coated,
premium coated, extra-large gamut. The printer's own profile and limits override the table. Ask for: press
and paper, characterization, TAC and max K, PDF/X version, RGB-with-output-intent or CMYK, spot handling,
rich-black recipe. Profiles: eci.org (ECI profiles may be embedded and exchanged, not redistributed or
altered), registry.color.org (GRACoL/SWOP profiles, free; CGATS datasets at printtechnologies.org).

## 3. Rendering intents
| Intent | Behaviour | Use for |
|---|---|---|
| Relative colorimetric + black point compensation | In-gamut colors kept (relative to paper white), out-of-gamut clipped; BPC maps black to black | Vector art, brand colors, images near the target gamut |
| Perceptual | Compresses the whole gamut (tables differ by profile vendor) | Saturated photos/renders with much out-of-gamut content |
| Saturation | Keeps saturation, sacrifices accuracy | Business graphics only |
| Absolute colorimetric | Also simulates the source paper white | Proofing only, never production |
Soft-proof relative and perceptual side by side for images, choose visually, record the choice.

## 4. RGB to CMYK, correctly
Read `references/print-cmyk-spot.md` when converting RGB to CMYK or handling spot and Pantone colors.

## 5. Spot colors and Pantone
Read `references/print-cmyk-spot.md` when converting RGB to CMYK or handling spot and Pantone colors.

## 6. Measuring difference
- Use ΔE00 (CIEDE2000). ΔE76 (ΔE*ab) overstates differences in saturated colors.
- Reading it: < 1 imperceptible to most observers; 1–2 visible on close side-by-side inspection; ≥ 3 clearly
  visible. Brand spot specs are often ≤ 2 (≤ 1 for luxury goods). A spec names the metric, D50/2°,
  measurement condition (M0/M1/M2), backing, instrument; instruments alone disagree by about 0.3–1 ΔE.
- `Color("#e63946").delta_e("#e5383b", method="2000")` (ColorAide; Lab D65 unless you pass `space="lab"` for
  D50) and `colour.delta_E(lab1, lab2, method="CIE 2000")` (colour-science) agree on the same Lab (2.81 in D65,
  2.77 in D50 for that pair).

## 7. Perceptual palettes (OKLCH)
- OKLCH lightness tracks perceived lightness far better than HSL, and hue stays put along a ramp. CSS
  `oklch()` works in current browsers.
- Ramp: fix the hue, step L (0.97 → 0.29 for a 50–900 scale), let chroma peak mid-ramp, gamut-map every
  step to sRGB (and P3 if used), then check contrast pairs. Maximum sRGB chroma sits at a different L per hue
  (yellow near L 0.96, blue and purple near 0.5): shape the chroma curve per hue.
```python
# uv run --with coloraide python ramp.py
from coloraide import Color
L = [0.97, 0.93, 0.86, 0.77, 0.67, 0.57, 0.47, 0.38, 0.29]
C = [0.02, 0.04, 0.08, 0.12, 0.15, 0.15, 0.13, 0.10, 0.07]
ramp = [Color("oklch", [l, c, 260]).convert("srgb").fit().to_string(hex=True) for l, c in zip(L, C)]
print(ramp, Color(ramp[-1]).contrast(ramp[0], method="wcag21"))   # fit(): default method raytrace
```
- Contrast by lightness: in CIE L* (= HCT tone) a gap ≥ 38.4 guarantees 3:1, ≥ 50.2 guarantees 4.5:1,
  ≥ 62.2 guarantees 7:1 (derived from the WCAG formula). OKLCH L is a different scale: compute contrast.
- huetension `gradient.generate` (OKLCH/OKLab interpolation), `harmony.generate`, `palette.random` with a
  seed for exploration; `export.css`/`export.tailwind` for tokens.

## 8. Contrast (WCAG 2.2)
- Relative luminance: linearize each sRGB channel (c ≤ 0.04045 ? c/12.92 : ((c+0.055)/1.055)^2.4),
  L = 0.2126 R + 0.7152 G + 0.0722 B; ratio = (L1 + 0.05)/(L2 + 0.05). WCAG 2.1 and 2.2 share it (the old
  0.03928 threshold made no practical difference).
- AA: text 4.5:1, large text 3:1 (18 pt or 14 pt bold ≈ 24 px / 18.7 px CSS), UI components and graphical
  objects 3:1 (1.4.11). AAA: 7:1 and 4.5:1. Logotypes and incidental text are exempt.
- `#767676` on white = 4.54:1 (pass), `#777777` = 4.48:1 (fail): never round a ratio up.
- Compute with ColorAide `contrast(method="wcag21")`, huetension `contrast.check`, or Illustrator MCP
  `check_contrast` (auto-detects overlapping pairs). Text on photos: measure the worst local background,
  add a scrim if needed.
- APCA: removed from the WCAG 3 draft in 2023, not normative, WCAG 3's method is undecided. Use it only as a
  second, perceptual check (Lc 90 preferred body text, 75 minimum body, 60 other content text, 45 large
  headlines, 30 spot-readable, 15 non-text), never instead of WCAG 2.x.
- Color-vision deficiency: never encode meaning by hue alone; simulate protan/deutan/tritan/achroma with
  `blindness.simulate`.

## 9. Dark mode palettes
- Re-derive, don't invert: the same hue ramps with different role assignments (surface, on-surface,
  primary, on-primary, outline) stored as light/dark token pairs.
- Surfaces: dark gray rather than pure black (Material recommends #121212); show elevation with lighter
  surfaces; body text off-white.
- Accents: lighter, less saturated tones (Material uses its 200 tones for primaries in dark theme) so they
  don't vibrate against dark surfaces; re-check every pair, since contrast does not carry over.
- Logos, charts and illustrations need their own dark variants (reverse logo, dark chart palette).
- CSS: `@media (prefers-color-scheme: dark)` swapping custom properties; `color-scheme: light dark`.

## 10. Displays, calibration, soft-proofing
Read `references/displays-profiles.md` when calibrating displays, soft-proofing, or embedding and checking profiles.

## 11. Embedding and checking profiles
Read `references/displays-profiles.md` when calibrating displays, soft-proofing, or embedding and checking profiles.

## 12. Checklists per deliverable
Read `references/checklists.md` when checking a deliverable before handoff.

## Verify
- Recompute every contrast pair and ΔE with code, not by eye; list the numbers.
- Open each export and confirm its embedded profile (commands in §11); PDF output intent present.
- CMYK files: max TAC ≤ limit, text K-only, no white overprint, only intended plates
  (`get_separation_info`, Acrobat Output Preview).
- Soft-proof screenshots reviewed with Simulate Paper Color on; out-of-gamut brand colors flagged.
- Physical proof or sample for color-critical print and apparel, measured against the spec when a
  spectrophotometer is available.

## Deliverables / Report
- Color spec table: name | role | reference (Pantone C/U or Lab D50) | HEX (sRGB) | RGB | OKLCH |
  Display P3 (optional) | CMYK per condition with profile name | contrast notes.
- Files: swatches (`.ase` via the huetension CLI or Illustrator), CSS/Tailwind tokens, converted assets,
  the ICC profiles used (by name and source; don't redistribute ECI profiles).
- Conversion log: source profile, destination, intent, BPC, TAC limit, rich-black recipe, soft-proof
  settings, out-of-gamut decisions and open risks.
