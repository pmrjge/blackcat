---
name: print-production
description: Load before building, exporting or checking any file meant for print — trim, bleed, dielines, ppi, CMYK and ink limits, spot colors, overprint, PDF/X, preflight, proofs.
---
# Print production and prepress

## Scope
- Covers document setup, resolution, color, fonts and transparency, PDF/X export, preflight (GUI and command line), proofs, finishes, paper, common products, large format and vehicle wraps, and the delivery package.
- Not here: garment decoration (`apparel-merch-print`), path construction and SVG/DXF output for cutters (`svg-vector-craft`), driving apps through the screen (`computer-use-apps`).
- The printer's spec sheet and templates override every default below. The defaults are for when no spec exists and for sanity-checking a spec. Never guess a profile, a finish setup or a die line: ask.

## 1. Spec intake
Ask before building: finished (trim) size and page count · quantity · process (offset sheetfed/web, digital toner/inkjet, wide-format inkjet) · stock (coated/uncoated, weight, brand) · output condition (profile or characterization such as FOGRA51, GRACoL2013) and TAC limit · spot colors allowed · bleed and safety · PDF standard and version · printer's marks yes/no (many online printers want bleed only, no marks) · how finishes and dielines are supplied (spot plate in the same PDF or separate pages/files, exact swatch names) · fold/die template · proof type · file naming and upload.

## 2. Document setup

| Item | Default when no spec |
|---|---|
| Artboard | = trim size; one artboard per page/side, named |
| Bleed | 3 mm (EU) / 0.125 in (US) on every edge that prints to the edge; large format per vendor; wraps 3–5 in (§12) |
| Safety (live area) | ≥ 3 mm / 0.125 in inside trim; 5 mm+ for thin frames and borders; booklets add gutter and creep |
| Units | mm or in, never px |
| Color mode | File › Document Color Mode › CMYK Color for print documents |
| Raster effects | Effect › Document Raster Effects Settings = output resolution (300 ppi); drop shadows and glows rasterize at this value |

Technical layers (die, kiss-cut, crease, perforation, foil, spot UV, emboss, white ink):
- Each on its own locked top layer, vector only; die cuts are closed paths, stroke 0.25 pt (or per printer), no fill.
- Colored with a spot swatch at 100% tint named exactly as the printer specifies (`CutContour`, `Dieline`, `Crease`, `Perf`, `Foil`, `SpotUV`, `Emboss`, `White`) and set to overprint (Attributes panel), so it never knocks out the art.
- Some printers want these as spot plates in the print PDF, others as separate pages or files in 100K. Follow the template.
- Never use the [Registration] swatch for artwork: it prints on every plate.

Folded and bound items:
- Roll fold (tri-fold): the panel that folds in is narrower by about 1/16 in (1.5–2 mm). US letter: outside panels 3.625 | 3.688 | 3.688 in, inside mirrored 3.688 | 3.688 | 3.625 in. Use the printer's template for gate, Z and accordion folds.
- Saddle stitch: page count is a multiple of 4; creep (shingling) moves inner pages' fore-edge content toward the trim, growing with sheet count and caliper. Printers compensate at imposition; ask, keep live content well inside, avoid thin frames near the fore-edge.
- Score before folding heavier stocks (commonly from ~150 gsm / 100 lb text); fold parallel to the grain; heavy ink across a fold on coated stock cracks, so avoid dark solids across folds or laminate.

## 3. Resolution
- Effective ppi = image pixels / printed inches (a 300 ppi image scaled to 150% is 200 ppi). Upsampling does not add detail; check the source pixel count.
- Offset and digital at reading distance: 300 ppi effective for contone (about 2 × a 150 lpi screen); 1-bit line art 1200 ppi.
- Viewing distance: pixels stop being resolvable at 1 arcminute, so ppi ≥ 1/(d · tan(1/60°)) ≈ 3438 / d(in) ≈ 87 / d(m). Vendors target more than this floor because viewers step closer and edges show:

| Distance | Acuity floor | Common vendor target | Typical products |
|---|---|---|---|
| 0.3–0.9 m | 290–97 ppi | 150–300 ppi | posters, retractable banners |
| 0.9–3 m | 97–29 | 75–150 | trade-show walls, window graphics |
| 3–7.5 m | 29–12 | 50–75 | large banners, murals |
| 7.5–15 m | 12–6 | 25–50 | building wraps, outdoor signs |
| > 15 m | < 6 | 15–25 | billboards |

Vehicle wraps: 100–150 ppi at 1:1 (§12).

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

## 5. Fonts and transparency
- PDF/X requires every font embedded (subsets are fine). `pdffonts`: every row `emb yes`; Type 3 fonts deserve a look.
- Outline text only when the font license forbids embedding, for logo lockups, for cutting/engraving, or when the printer asks. Keep a live-text master; outline a copy (Type › Create Outlines). Proofread before outlining.
- Transparency (opacity, blend modes, soft shadows, glows, masks) stays live in PDF/X-4 and is flattened for PDF/X-1a. Flattening can outline or rasterize nearby text (visible weight change), convert spot colors inside blend modes to process, and show stitching lines on screen (usually not in print). Inspect Window › Flattener Preview (highlight rasterized regions and outlined text) and use the [High Resolution] flattener preset.

## 6. PDF/X

| | PDF/X-1a (:2001 / :2003) | PDF/X-4 (:2008 / :2010) |
|---|---|---|
| Standard, base | ISO 15930-1 / 15930-4; PDF 1.3 / 1.4 | ISO 15930-7; PDF 1.6 |
| Color | CMYK, spot, gray only | also ICC-based RGB/Lab, with output intent |
| Transparency | flattened | live, rendered by the RIP |
| Layers | no | optional content allowed |
| Choose when | the printer or publisher requires it; older RIPs | modern RIPs (Adobe PDF Print Engine); the usual recommendation, Ghent Workgroup specs build on it |

- Both need: all fonts embedded, an output intent, TrimBox (or ArtBox) on every page, BleedBox when bleeding, no encryption, no JavaScript, no form fields or annotations inside the bleed or trim area. PDF/X-3 (color-managed, no transparency) and PDF/X-6 (PDF 2.0, 2020) only on request.
- Many printers still list X-1a on their site but accept X-4; ask rather than flatten needlessly.
- Illustrator: File › Save As › Adobe PDF → preset [PDF/X-4:2008] or [PDF/X-1a:2001] → Marks and Bleeds: Use Document Bleed Settings, marks only if requested → Output: Convert to Destination (Preserve Numbers), destination = the printer's profile, Output Intent Profile Name = the same → save as a new file with Preserve Illustrator Editing Capabilities off.
- Illustrator "large canvas" documents (up to 2270 in) save at 1/10 size to PDF 1.5 or lower, which includes PDF/X-1a, and to versions before 24; build oversized pieces at a stated scale instead (§12).

## 7. Preflight
GUI:
- Illustrator: Window › Document Info (fonts, linked/embedded images, spot colors), Links panel (link info shows image resolution; confirm effective ppi with `pdfimages -list` on the exported PDF), Separations Preview, Overprint Preview, Flattener Preview, File › Package.
- Illustrator MCP server, when mounted: read document info, image resolution and color space, overprint and separation info, run its preflight against the target PDF/X, then export the PDF. Illustrator's scripting API cannot read the document bleed setting, so always verify the boxes in the exported PDF.
- Acrobat Pro: Print Production › Preflight with the matching PDF/X profile (the real standards validator); Output Preview for separations, Total Area Coverage highlight at the profile's TAC, and overprint simulation; Object Inspector for per-object color and ppi.

Command line (poppler, Ghostscript, qpdf; all verified):
```sh
pdfinfo -box file.pdf                    # pages, Media/Crop/Bleed/Trim/Art boxes in pt (1 pt = 0.3528 mm)
pdfinfo -custom file.pdf                 # Info keys GTS_PDFXVersion / GTS_PDFXConformance (X-1a)
pdfinfo -meta file.pdf | grep -ai pdfx   # XMP pdfxid:GTS_PDFXVersion (X-4); -a because some producers write NUL bytes
pdffonts file.pdf                        # emb must be yes on every row
pdfimages -list file.pdf                 # color space, bpc, x-ppi/y-ppi = effective resolution
qpdf --check file.pdf                    # structure; exit 0 ok, 2 errors, 3 warnings
qpdf --json --json-key=qpdf file.pdf | grep -o '"/OutputConditionIdentifier": "[^"]*"'   # output intent
gs -q -dSAFER -o - -sDEVICE=ink_cov file.pdf     # average ink % per plate per page (inkcov = share of pixels touched)
gs -q -dSAFER -o sep-%d.tif -sDEVICE=tiffsep -r150 file.pdf       # one TIFF per plate, spots included: sep-1(Foil).tif
gs -q -dSAFER -o soft-%d.png -sDEVICE=png16m -r150 -dOverprint=/simulate file.pdf   # overprint-accurate RGB view
```
Maximum TAC per pixel (the number printers reject files for):
```sh
gs -q -dSAFER -o tac-%03d.tif -sDEVICE=tiff32nc -r100 file.pdf
__CLAUDE_DIR__/venvs/sci/bin/python - <<'EOF'
import glob, numpy as np
from PIL import Image
for f in sorted(glob.glob("tac-*.tif")):
    t = np.asarray(Image.open(f), dtype=np.float32).sum(axis=2) / 2.55   # C+M+Y+K in %
    print(f, f"max {t.max():.0f}%", f"area over 300%: {(t > 300).mean():.3%}")
EOF
```
DeviceCMYK passes through unchanged. RGB/ICC objects are converted with Ghostscript's default profiles unless you add `-sOutputICCProfile=printer.icc` (and `-dUsePDFX3Profile` to honor the file's output intent), so treat those numbers as approximate. Render a PNG of each page (`-sDEVICE=png16m -r100`) and Read it.

## 8. Proofs
- Soft proof: calibrated display; Illustrator View › Proof Setup › Customize (device = printer profile, Preserve CMYK Numbers, Simulate Paper Color), then View › Proof Colors. For layout and color intent, not a contract.
- Contract proof: inkjet proof to ISO 12647-7 with a measured control strip (Fogra Media Wedge or the Idealliance strip) and a pass label; judged under D50 light (ISO 3664 viewing booth). The press matches this.
- Physical dummy for folds, die cuts, finishes and stock; strike-off on the actual media and laminate for wide format.
- Press check: compare the sheet to the signed proof under D50; registration, key colors (skin, brand), density across the sheet, hickeys, finish registration; sign the OK sheet.

## 9. Finishes (each is its own separation)

| Finish | Supply as | Constraints (typical; confirm) |
|---|---|---|
| Hot foil | vector mask, spot `Foil` 100% overprint, or a separate 100K page | lines ≥ 0.5–1 pt, type ≥ ~5 pt, no halftones; the block is made at the supplied size |
| Cold/digital foil | mask plate; CMYK can print over cold foil for metallic colors | tint rules per press |
| Spot UV / spot varnish | vector mask, spot `SpotUV` 100% overprint | lines ≥ ~0.5 pt; registration tolerance, so avoid hairline fits to printed edges; ask whether to choke |
| Emboss / deboss | vector mask at 1:1 (`Emboss`, `Deboss`); registered or blind | no fine detail; away from folds and trim; heavier uncoated stock works best; the reverse shows on the back |
| Flood varnish, aqueous, lamination | no file (flood) | lamination shifts color slightly; soft-touch scuffs on dark solids |
| Die/kiss cut, crease, perf | technical layer (§2) | closed paths; minimum inside radius per die maker |

Masks align exactly with the art. Add a composite preview page (art with the finish tinted) for approval.

## 10. Paper
- Coated (gloss/silk/matt) holds finer dots and denser blacks; uncoated absorbs (more dot gain, duller blacks): use the uncoated profile, lighter rich blacks, avoid heavy coverage.
- US basis weights to gsm: text lb × 1.4801 (25 × 38 in basis), cover lb × 2.7041 (20 × 26 in), bond lb × 3.7597 (17 × 22 in). 100 lb text ≈ 148 gsm; 100 lb cover ≈ 270 gsm.
- Caliper: a paper "pt" is 0.001 in, not a type point (14 pt card ≈ 0.36 mm); EU mills quote µm. Needed for spine width and creep.
- Grain: the second dimension of a sheet size is the grain direction (11 × 17 in = grain long), or it is underlined. Fold and score parallel to the grain; for cards, grain parallel to the fold.

## 11. Common products

| Product | Standard trim | Notes |
|---|---|---|
| Business card | 85 × 55 mm (EU), 3.5 × 2 in (US), 91 × 55 mm (JP), 85.60 × 53.98 mm (ID-1) | bleed 3 mm / 0.125 in, safety ≥ 3 mm, text ≥ ~6 pt |
| Greeting card | A6 folded from A5; 5 × 7 in folded from 10 × 7 in | score, fold parallel to grain, check panel order inside/outside; envelopes C6 / A7 (5.25 × 7.25 in) |
| Brochure | A4, A5, letter | roll-fold panel widths (§2) |
| Booklet | multiple of 4 pages | creep; supply single pages unless spreads are requested |
| Poster | A2–A0, 18 × 24, 24 × 36 in | ppi by distance (§3) |
| Sticker / label | die-cut (through) or kiss-cut (on liner) | cut path as spot (`CutContour` in Roland VersaWorks), 0.25 pt, closed; 1/16–1/8 in (1.5–3 mm) bleed outside and safety inside; white underprint plate on clear or metallic stock; roll labels: unwind direction, core, labels per roll |

## 12. Large format and vehicle wraps
- Build at 1:1 when it fits Illustrator's normal canvas (227 × 227 in, 5.77 m); otherwise at a stated scale and let the RIP enlarge. Add 2–3% noise to large smooth gradients against banding. Ask for hems, grommets, pole pockets and seams.

Vehicle wraps:
1. Measure the vehicle (overall length, beltline height, wheelbase, door, handle and fuel-door positions) and shoot each side straight on. Templates (1:10 is the North American norm; 1:20 for large vehicles) are drawings: verify key dimensions against the vehicle, trim level and model year.
2. Design at 1:10 (the RIP scales 1000%). Rasters at 10 × the final ppi: 100–150 ppi at 1:1 = 1000–1500 ppi in the 1:10 file; Document Raster Effects likewise; if you scale artwork up, turn on Scale Strokes & Effects. Put the scale in the file name and on a note layer.
3. Keep logos, phone numbers, URLs, faces and text off door gaps, handles, hinges, fuel doors, deep recesses and channels, rivets, body lines, compound curves and mirrors; make them readable with doors closed.
4. Bleed 3–5 in (75–125 mm) past every panel edge; some shops want 6 in on cars and vans, 2 in on box trucks. The installer decides.
5. Panelize to the printable width of the roll (54–60 in media, minus margins); overlap seams ≥ 0.5 in (12.7 mm), 0.5–1 in typical. Vertical seams shingle rear-to-front (each forward panel laps over the one behind it, so exposed edges face rearward, away from the airflow); horizontal seams bottom-up (upper panel over lower, edges face down). Never seam through text or logos. Number panels and mark orientation.
6. Film: cast (about 2 mil / 50 µm, conformable, dimensionally stable, 5–12 years) for compound curves, rivets and recesses; calendered (thicker, stiffer, shrinks) for flat or simple curves, polymeric for mid-term, monomeric for short-term. Laminate with the film maker's matched cast overlaminate (Avery MPI 1105 Easy Apply RS, for example, is approved only with DOL 1000Z, DOL 1400Z series or DOL 6460). Solid colors can use color-change films instead of print. Windows: perforated window film; keep the windshield and front side windows clear (legal limits vary; check local law).
7. Print: 3M IJ180mC and Avery MPI 1105 both specify maximum total ink 270%, so keep rich black ≤ 270% (C60 M40 Y40 K100 = 240% fits). Solvent and eco-solvent prints outgas before lamination (Avery: 24–48 h flat, 72 h for conforming or fleet work); latex needs no extra curing.
8. Installer notes (not design decisions): clean and decontaminate the surface; apply within the film's temperature range (3M IJ180mC: 16–32 °C on compound curves, 18–22 °C optimal); post-heat stretched areas and recesses to the film maker's value (3M lists 95–110 °C for IJ180); relief cuts in recesses; remove hardware where possible.
Deliver: each side (driver, passenger, rear, front, roof, hood) at scale with the panel map, a client mockup on the template, and the print files.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| White slivers at the trim | no bleed, or BleedBox missing | extend art, set bleed, check `pdfinfo -box` |
| Logo missing in print | white object set to overprint | turn off; Overprint Preview |
| Fuzzy black text, colored halos | four-color black from RGB conversion | 100K + overprint; check `tiffsep` plates |
| Drying/set-off complaints, rejected file | TAC over limit | convert with the right profile, lighter rich black, run the TAC script |
| Courier or substituted font | font not embedded | embed or outline; `pdffonts` |
| Extra plate on the proof | duplicate or unused spot names | merge or delete swatches; recheck separations |
| Spot printed as CMYK | converted on export or flattening (blend modes) | keep spot, avoid blend modes on spots, check plates in the PDF |
| Output 10 × too small | large-canvas document saved to PDF ≤ 1.5 | scale workflow or PDF/X-4 |
| Pixelated shadows and glows | raster effects at 72 ppi (36 ppi on large canvas) | set Document Raster Effects Settings |
| Die line printed on the product | die not spot, not overprint, or not separated as asked | spot + overprint + the printer's layout |

## Verify
Run the CLI block on the final PDF: boxes equal trim/bleed, output intent and PDF/X key present, fonts embedded, image ppi at target, plates as expected (`tiffsep`), maximum TAC under the limit, `qpdf --check` exit 0. Render PNG pages and Read them (overprint simulated). Validate the standard in Acrobat Preflight when available. For folded and die-cut pieces, print at 100%, cut and fold a dummy.

## Preflight checklist
- [ ] TrimBox = finished size on every page; BleedBox = trim + bleed; page count and order right
- [ ] Art reaches the bleed on bleeding edges; nothing critical outside the safety area
- [ ] Output condition correct (CMYK in the printer's profile, or PDF/X-4 with the right output intent); no stray RGB
- [ ] Plates = intended process + spot inks; no [Registration] art; TAC ≤ limit
- [ ] Small text, rules and barcodes 100K, overprinting; rich black only on large solids
- [ ] No white or [Paper] overprint; technical layers are spot, overprint, correctly named
- [ ] Effective ppi meets the target for the viewing distance; no upsampled low-res images
- [ ] Fonts embedded or intentionally outlined; text proofread
- [ ] Transparency live (X-4) or flattened at high resolution (X-1a) without damaged text
- [ ] Folds, scores, creep, grain, panel widths per template; finishes aligned with art
- [ ] PDF/X validated; `qpdf --check` clean; no printer's marks inside the bleed

## Deliverables
- Print files: `<job>_<product>_<trim>_<side-or-pages>_v<NN>.pdf` (PDF/X as specified), plus separate finish/die files if the printer wants them, named for the plate (`..._foil.pdf`).
- Proof: low-resolution PDF or PNG with the dieline and finish areas visible and annotated.
- Source package: .ai/.indd with links, a font list with license notes (never ship fonts whose license forbids it), and the spec sheet (trim, bleed, stock, output condition, spot inks, finishes, quantity, proof type).
- Report: the preflight table (check, result, evidence such as command output), known approximations (Pantone in CMYK, out-of-gamut RGB) and open questions for the printer.
