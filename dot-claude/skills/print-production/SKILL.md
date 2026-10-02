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
| Bleed | 3 mm (EU) / 0.125 in (US) on every edge that prints to the edge; large format per vendor; wraps 3–5 in (§12 in `references/finishes-large-format.md`) |
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

Vehicle wraps: 100–150 ppi at 1:1 (§12 in `references/finishes-large-format.md`).

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
- Illustrator "large canvas" documents (up to 2270 in) save at 1/10 size to PDF 1.5 or lower, which includes PDF/X-1a, and to versions before 24; build oversized pieces at a stated scale instead (§12 in `references/finishes-large-format.md`).

## 8. Proofs
- Soft proof: calibrated display; Illustrator View › Proof Setup › Customize (device = printer profile, Preserve CMYK Numbers, Simulate Paper Color), then View › Proof Colors. For layout and color intent, not a contract.
- Contract proof: inkjet proof to ISO 12647-7 with a measured control strip (Fogra Media Wedge or the Idealliance strip) and a pass label; judged under D50 light (ISO 3664 viewing booth). The press matches this.
- Physical dummy for folds, die cuts, finishes and stock; strike-off on the actual media and laminate for wide format.
- Press check: compare the sheet to the signed proof under D50; registration, key colors (skin, brand), density across the sheet, hickeys, finish registration; sign the OK sheet.

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

## References
- `references/color.md` — read when setting up colour, profiles, ink limits or rich black.
- `references/preflight.md` — read when preflighting a print PDF in detail.
- `references/finishes-large-format.md` — read when specifying finishes (foil, spot UV, die cuts, white ink) or large-format and vehicle-wrap jobs.

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
