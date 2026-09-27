---
name: color-management
description: Load before choosing, converting or checking colors for any deliverable. Color that survives screens and print — ICC profiles (sRGB, Display P3, FOGRA39/51/52, GRACoL/SWOP 2013), rendering intents, RGB-to-CMYK with rich black and ink limits, Pantone/spot matching, ΔE2000, OKLCH ramps, WCAG 2.2 contrast (APCA as a note), dark mode, display calibration, soft-proofing, embedded profiles, per-deliverable checklists.
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
1. Binding. Late: keep RGB images and export PDF/X-4 with the printer's output intent; the RIP converts.
   Early: convert in the file (PDF/X-1a, or the printer wants CMYK). Either way, brand and vector colors get
   explicit CMYK builds per condition; never let a blind conversion choose them.
2. Convert once with the target profile (relative + BPC; perceptual for problem images) from a tagged
   16-bit source. Illustrator converts with the Color Settings CMYK working space when you switch
   File > Document Color Mode: set the working space to the target first, then check Edit > Assign Profile.
3. Black. Body text, hairlines and small type: `0/0/0/100`, overprinting. Never convert RGB black: sRGB
   `#000000` becomes C83 M67 Y51 K95 (296 %) in PSO Coated v3 and fringes on text. Large solids: the
   printer's rich black; common default C60 M40 Y40 K100 (240 %), cool C60 M0 Y0 K100, warm C40 M60 Y40 K100.
4. Ink limit: max(C+M+Y+K) ≤ the profile TAC (or the printer's, if lower). Check in Acrobat Pro Output
   Preview (Total Area Coverage) or with the code below.
5. Neutral grays in vector art: K only; CMY-built grays drift with press balance.
6. White objects must never overprint (they vanish). `get_overprint_info` reports overprint settings and
   K100/rich-black use; `get_separation_info` lists the plates actually used.
7. No CMYK→CMYK chains. To move a job between conditions use a device link (ECI publishes ISO Coated v2 ↔
   PSO Coated v3 links) or go back to the RGB/Lab master.

```python
# uv run --with pillow --with numpy python convert.py
import io
import numpy as np
from PIL import Image, ImageCms
src = Image.open("art.png")
icc = src.info.get("icc_profile")                    # embedded profile wins; untagged = sRGB
src_prof = ImageCms.ImageCmsProfile(io.BytesIO(icc)) if icc else ImageCms.createProfile("sRGB")
dst_prof = ImageCms.getOpenProfile("PSOcoated_v3.icc")
out = ImageCms.profileToProfile(src.convert("RGB"), src_prof, dst_prof, outputMode="CMYK",
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
out.save("art_pso3.tif", compression="tiff_lzw", icc_profile=dst_prof.tobytes())
tac = np.asarray(out, dtype=float).sum(axis=2) / 2.55   # % per pixel
print(f"max TAC {tac.max():.0f}%, pixels over 300%: {(tac > 300).sum()}")
```
CLI (ImageMagick 6; `magick` in 7):
`convert in.png -profile sRGB.icc -intent Relative -black-point-compensation -profile PSOcoated_v3.icc out.tif`
(for an already-tagged source pass only the target profile, or an Adobe RGB image gets clipped through sRGB). macOS: `sips -M <profile.icc> relative in.tif --out out.tif`
converts, `sips -e <profile.icc>` embeds without converting, `sips -g profile f` shows the profile.

## 5. Spot colors and Pantone
- Formula Guide (C coated, U uncoated) = spot inks. Color Bridge shows each spot's CMYK simulation
  (PANTONE 100 C → 100 CP; UP for uncoated). A spot's CMYK build is an approximation, not the spot.
- Illustrator no longer ships Pantone books (all removed with the October 2023 release): libraries need a
  Pantone Connect license and plugin; existing files keep their swatches.
- Pantone Connect Lab values are D50/2°; check which measurement condition (M0/M1/M2) they state and
  compare measurements under the same condition.
- Brand workflow: spot (or Lab D50) is the reference → CMYK per condition (coated and uncoated builds
  differ) from Color Bridge or from Lab through the target profile, confirmed on a proof → sRGB HEX from Lab
  (out of gamut: pick the closest in-gamut color by eye and ΔE, write it down).
- In files: swatch type Spot, name exactly as the printer's ink ("PANTONE 186 C"), one name per ink, unused
  spots deleted or set to process before export; check plates with Separations Preview or
  `get_separation_info`.
- Printed guides fade and vary between copies (differences around 2 ΔE00 are normal): use a current guide
  and measured values; don't specify tolerances tighter than guide plus instrument variation.

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
- Calibrate every display with a colorimeter (vendor software, or ArgyllCMS/DisplayCAL). Screen work:
  D65 white, sRGB/2.2 tone response. Print matching: match the D50 viewing booth and paper, not a number;
  ISO 12646 (proofing displays) specifies D50 and 160 cd/m²; dim rooms often need less.
- Apple displays with reference modes (Pro Display XDR, Studio Display/Studio Display XDR, MacBook Pro
  XDR): System Settings > Displays > Preset, e.g. "Design and Print (P3-D50)", "Photography (P3-D65)",
  "Internet and Web (sRGB)".
- Pen displays: gamut ranges from about sRGB to wide-gamut depending on model (check the spec sheet);
  Wacom does not supply ICC profiles and points to profiling with Wacom Color Manager. Set the display's
  OSD color mode first (if it has one), then profile it with a colorimeter; macOS assigns one profile per
  display, so profile each screen and judge color on the more capable one. A narrow-gamut screen cannot
  show out-of-gamut colors: trust numbers and proofs there.
- Soft-proof (Illustrator and Photoshop): View > Proof Setup > Customize → Device to Simulate (printer
  profile), Preserve CMYK Numbers (on for CMYK files), Rendering Intent, Black Point Compensation, Simulate
  Paper Color, Simulate Black Ink; toggle with View > Proof Colors. Illustrator: View > Overprint Preview
  and Window > Separations Preview for spots/overprints. PDFs: Acrobat Pro Output Preview.
- A soft proof is not a contract proof: color-critical print jobs get a certified proof (ISO 12647-7 with a
  control strip) or a press check.

## 11. Embedding and checking profiles
- Web: convert to sRGB and keep the profile (or the PNG sRGB chunk); browsers treat untagged images as sRGB.
  P3 images: embed Display P3 and keep an sRGB fallback. Metadata-stripping optimizers can drop the
  profile: check after optimizing.
- Print: PDF/X with the output intent set to the agreed profile (`export_pdf` accepts `output_intent_profile`;
  details in `print-production`). Video: sRGB stills become BT.709.
- Check: `identify -verbose f | grep -i icc` (ImageMagick), `sips -g profile f`,
  `exiftool -ICC_Profile:ProfileDescription f`; PDF output intent:
```python
from pypdf import PdfReader
oi = PdfReader("out.pdf").trailer["/Root"].get("/OutputIntents")
print([o.get_object().get("/OutputConditionIdentifier") for o in oi] if oi else "no output intent")
```

## 12. Checklists per deliverable
- **Web/UI:** sRGB, tagged; tokens as HEX (+ OKLCH source); every text/background pair meets 4.5:1 (3:1 large
  text and UI parts); dark-mode pairs checked separately; CVD simulated; P3 only as enhancement.
- **App assets:** Apple icons accept sRGB, Gray Gamma 2.2 or Display P3; Google Play store icon is sRGB;
  interface colors from the same tokens as web.
- **Print (offset/digital):** agreed profile and TAC; brand colors as explicit CMYK or spot; K-only text,
  overprinting; rich black only on large areas; no RGB or Lab objects left unless the workflow is late
  binding; spot names match the printer; images at ≥ 300 ppi effective size unless the printer says
  otherwise; soft-proofed; separations checked.
- **Apparel** (method choice and files: `apparel-merch-print`): screen print uses spot inks matched to
  Pantone (one screen per color; halftones about 35–65 LPI, the printer decides); DTG/DTF files are sRGB PNGs
  with fully transparent backgrounds and no
  semi-transparent pixels, glows or soft shadows (they trigger a visible white underbase on dark garments;
  put a bright test layer behind the art to find stray alpha); resolution per vendor (150–300 ppi at print
  size); embroidery matches thread charts, not CMYK: ask for the thread numbers; approve a physical sample.
- **Slides and video:** sRGB; check projector or TV washout on low-contrast pairs; video tagged BT.709.

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
