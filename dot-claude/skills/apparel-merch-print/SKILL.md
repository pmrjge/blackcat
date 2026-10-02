---
name: apparel-merch-print
description: Use for garment and merch art — screen print, DTG, DTF, sublimation, vinyl, embroidery.
---
# Apparel and merchandise print

## Scope
- Covers method choice, screen-print separations, DTG, DTF, sublimation, heat-transfer vinyl (HTV), embroidery, placements and sizes, sizing across a size run, legibility, mockups, delivery files and legal guardrails.
- Not here: paper/offset prepress and PDF/X (`print-production`), vector construction and tracing (`svg-vector-craft`), generated concept art and mockups (`image-prompting`).
- Numbers are common shop and print-on-demand (POD) guidance; the chosen vendor's template and minimums win. Get them before final art.

## 1. Brief
Blank (brand, style code, fabric content, weight, colors) · quantities per size and color · placements · method, or let §2 decide · ink or effect (plastisol, water-based, discharge, puff, metallic, glow) · budget per piece and deadline · fulfilment (local shop, POD, contract printer) · who owns every logo, character, photo and font used (§12).

## 2. Choose the method

| Method | Best for | Fabric / substrate | Art limits | Run size and cost | Hand / feel |
|---|---|---|---|---|---|
| Screen printing | 1–6 flat spot colors, bold graphics, volume | almost any, with the right ink | each color is a screen; photos need sim process | shop minimums commonly 12–72 pieces; setup per screen per color per location; cheapest per piece at volume | plastisol sits on top; water-based soft |
| DTG (direct to garment) | full color, photos, 1 to a few dozen pieces | 100% cotton best; blends with ≥ 60% cotton (Printful) | no semi-transparency; neon and exact Pantone out of gamut | no setup; higher per-piece cost | soft, ink in the fibers |
| DTF (direct to film) | full color on mixed fabrics, small to mid runs, dark or light | cotton, polyester, blends | no semi-transparency; tiny isolated bits peel | no screens; gang sheets | thin film, heavier than DTG on big solids |
| Sublimation | all-over prints, sportswear, photographic | polyester only (100% ideal, ≥ 65% for acceptable color), white or light | no white ink: white = fabric | per piece; cut-and-sew for all-over | none, dye inside the fiber |
| HTV (heat-transfer vinyl) | names and numbers, 1–3 colors, personalization | most fabrics per vinyl type | vector cut; no gradients; weeding limits | small runs, per piece | film on top; layers add thickness |
| Embroidery | polos, caps, jackets, premium look | stable woven or knit; caps | no gradients or photos; minimum text and line sizes | priced per 1,000 stitches; digitizing fee | raised, durable |

Rules of thumb: many colors plus a small run → DTG (cotton) or DTF (anything); 1–2 colors plus volume → screen (one vendor comparison puts the DTF/screen crossover around 150 pieces at 1–2 colors; get quotes); synthetic performance wear → sublimation or DTF; premium corporate → embroidery; per-person names → HTV or DTF.

Screen-print cost ≈ Σ(locations × screens × setup) + quantity × per-piece rate, where screens = inks + underbase + highlight white, and the per-piece rate rises with color count. Reducing one color often beats every other saving.

## 3–8. Method-specific rules
Read `references/methods.md` for the chosen method — screen printing (separation types, screens), DTG and DTF (PNG, alpha rules), sublimation (polyester only), heat-transfer vinyl (weeding limits), embroidery (digitizing, file formats).

## 9. Placements and print areas (adult tees)

| Placement | Typical size | Position |
|---|---|---|
| Left chest | 2.5–5 in wide (3.5–4 typical); embroidery ≤ 4 × 4 in | ~3 in below the collar, over the wearer's left chest |
| Center chest | 6 × 6 to 10 × 8 in (8 × 8 common) | 3–3.5 in below the collar |
| Full front | 12 × 16 in (some blanks 15 × 18) | 3–4 in below the collar |
| Full back | 10 × 12 to 12 × 16 in | per vendor, usually a few inches below the collar |
| Sleeve | ~4 × 3.5 in | centered on the sleeve |
| Inside neck label | ≤ 3 × 3 in, text ≥ 10 pt | inner back neck |

Measure vertical positions from the collar seam (tech packs often use HPS, the high point shoulder). Sizes are Printful-style POD values; check the blank's print area, especially on women's cuts, youth sizes, hoodies (pocket, drawcords) and ringer or raglan seams.

## 10. Sizing across a size run
- One art size must fit the smallest garment it prints on; check it against the XS/S blank's printable width (chest width minus side-seam clearance).
- Or supply 2–3 art sizes (e.g., youth/XS–S, M–XL, 2XL+) and specify which size prints on which garment in the order. Left-chest and sleeve art stay one size.
- All-over and sublimation work uses per-size templates (§6).

## 11. Slogans and legibility
- Sign-industry legibility index: about 30 ft of viewing distance per inch of capital height (≈ 3.6 m per cm) for signs read head-on; for glance reading (parallel signs) the index drops to about 10. Garments move, curve and wrinkle, so size caps at roughly distance / 120: about 4 cm to read at 5 m.
- Bold, open letterforms; no hairline serifs or thin scripts under ~1 pt stroke; strong value contrast with the garment color (check a desaturated preview or with the huetension MCP); keep key words off underarms and belly folds; kern display sizes; outline fonts in production files.
- Test: print at 100% on paper, tape it to a shirt, view it at the target distance.

## 12. Legal guardrails
- Trademarks: team, league, university, event and race-series names and logos, brands and slogans need a license from the rights holder to appear on merchandise, including small runs and fan items; shops and POD platforms refuse or take down. For client-supplied marks, get written confirmation that the client owns or licenses them.
- Characters and copyrighted art (cartoons, anime, film stills, photos, other artists' designs): license required; "inspired by" still infringes if substantially similar. Parody is a legal defense, not a production plan.
- Fonts: the license must cover merchandise ("products for sale", sometimes a POD or commercial-product license). Adobe Fonts allows designing merchandise for sale but not font vending (customers typing their own text in the font) or sending font files to the printer; many "free" fonts are personal-use only; SIL OFL fonts allow commercial use (the font itself may not be sold alone). Outline fonts in delivered files.
- Stock images and mockup templates: check "items for resale" rights (often an extended license) and that the mockup license allows client presentation.
- People: photos of identifiable people on merch need their consent (model release).

## 13. Mockups
- Smart-object mockups with displacement maps, or the vendor's generator; show the true garment color and the art at its real size relative to the garment; label "mockup, colors approximate".
- Generated lifestyle images (`image-prompting`) are for concept presentation only, never production art unless rights are clear.

## 14. Delivery files per method
Read `references/delivery-files.md` when preparing the delivery files for a print method.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| White or colored box around DTG/DTF art | background not removed, near-white pixels | transparent background; run the alpha check |
| Speckled halo on dark shirts | anti-aliased or semi-transparent edge pixels over underbase | threshold alpha, choke underbase, halftone fades |
| Fine lines or small type missing | below the method's minimum, or dots below what the mesh holds | thicken, enlarge, remap tints ≥ 8% |
| Moiré in sim process | halftone angle or LPI fights the mesh | 22.5°, LPI ≈ mesh / 4–5 |
| Dull colors on dark garments | no underbase or wrong print order | add underbase, highlight white last |
| Faded sublimation | low polyester content | 100% polyester blank |
| Puckered embroidery | dense fills on light fabric | smaller fills, satin or appliqué; the digitizer adjusts density and stabilizer |
| Art too wide on size S | sized on an XL | per-size art (§10) |
| Order refused | third-party trademark or character | license or redesign (§12) |

## Verify
- Each file at 100%: physical size matches the placement spec; ppi at size; color mode per method; alpha check passes (0 semi-transparent pixels for DTG/DTF unless the vendor says otherwise); separation count equals the quoted colors; fonts outlined; no feature below the method minimum (overlay a 1 pt line and 8 pt text sample, or the method's values).
- Render and Read every deliverable and the mockups; print a 1:1 paper test for the key placement.

## Deliverables
- Production files per §14, mockups per colorway, and a spec sheet: blank, garment colors, quantities by size, method and ink/thread colors, placements with measurements from the collar, art size per garment size, finishing notes.
- Report: method recommendation with the reasoning and quote-driving factors (colors, screens, stitch count), risks (out-of-gamut colors, fabric limits), and a rights note for every logo, character, photo and font used.
