---
name: brand-identity
description: Load before creating or revising a logo or identity. Brand identity and logo design end to end — discovery brief and positioning, three concept directions, logo construction with optical corrections, wordmarks, scalability to 16 px, lockups, color and type systems, imagery and icons, brand guidelines, export matrix (SVG/PDF/EPS/PNG, favicon, app icons), client presentation, trademark and AI legal checks.
---
# Brand identity and logo design

## Scope
From brief to guidelines and export files for logos and visual identities. Elsewhere: color science,
profiles and ΔE → `color-management`; type choice, licensing, language rules → `typography`; clean vector
construction and SVG hygiene → `svg-vector-craft`; PDF/X and print files → `print-production`; garments
and merch → `apparel-merch-print`; generated imagery → `image-prompting`; brand decks →
`presentation-design`.

Tools: Illustrator MCP (`create_document` in points, `create_path`/`create_ellipse`/`create_text_frame`,
`convert_to_outlines`, `manage_swatches`, `place_color_chips`, `place_style_guide`, `extract_design_tokens`,
`resize_for_variation`, `export`, `export_pdf`, `preflight_check`); SVG written as code and previewed with
`rsvg-convert`; the huetension color MCP server for palettes, contrast and CVD checks; computer use for
GUI-only steps (`computer-use-apps`).

## 1. Discovery
Ask, then write a one-page brief the client approves:
- Business: offer, customers, model, stage, ambition in 3–5 years; what must change and what equity
  (colors, shapes, name) must survive.
- Positioning: "For [audience] who [need], [brand] is the [category] that [difference], because [proof]."
- Audience: segments, markets and languages, the moments they meet the brand.
- Personality: 3–5 attributes as "X, not Y" pairs ("confident, not arrogant"); voice.
- Competitors and references: 8–15 competitors; brands the client admires or dislikes, and why.
- Constraints: final name and its trademark status, mandatory elements, application list (signage,
  packaging, app icon, social, embroidery, vehicles, merch), print methods and ink budget (spot vs CMYK),
  accessibility, regulated wording, timeline, decision makers, number of rounds.
- Success criteria: how directions will be judged (reuse them when presenting).
Competitor audit: a grid of marks, colors, type, imagery and tone; place competitors on two axes that
matter to the positioning (traditional ↔ progressive, premium ↔ accessible); list category clichés to
avoid or subvert deliberately.

## 2. Concept development
1. Diverge: 50–100 fast black thumbnails across routes: wordmark, monogram, symbol (literal, metaphor,
   abstract), emblem, combination mark, mascot.
2. Mood boards per route (12–20 items: type, color, imagery, texture, layout), each labeled with what it
   contributes. References set direction only: never traced or shipped; keep their sources.
3. Converge to three directions that differ in idea, not styling. Each gets: the idea in one sentence, a
   rationale tied to the criteria, a black-on-white mark, palette, type pairing, 3–5 applications.
4. Image generation may feed mood boards and form exploration (`image-prompting`); the final mark is
   always drawn or rebuilt as vectors by hand (§11).

## 3. Logo construction
- Black on white first, tiny and large side by side; color comes last.
- Geometry: derive a module (stroke width, cap height) and build on it; arcs with few anchors at the
  extrema (0°/90°/180°/270°) and horizontal/vertical handles; consistent terminal angles and corner radii;
  no stray points. A construction grid documents real logic: never claim golden-ratio construction that did
  not drive the shapes.
- Optical corrections:
  - Overshoot: round and pointed forms pass the baseline and cap height by a few percent of the height, or
    they look small.
  - Equal apparent size: a circle or triangle must be larger than a square to look the same size.
  - Weight: horizontals thinner than verticals for equal apparent weight; ink traps where strokes meet if
    the mark will be tiny or printed on absorbent stock.
  - The optical center sits above the geometric one; center asymmetric shapes by eye.
  - Light-on-dark marks look heavier: make a slightly lighter reverse version when it shows.
  - Space letters and elements by area, not by equal gaps.
- Balance: blur/squint test; flip horizontally and vertically to expose lopsided weight.
- Counters and gaps must survive 16 px rendering, dot gain, embroidery and engraving; ask the printer or
  producer for minimum positive and reversed line widths (uncoated stock and reverses need more).
- Scalability tests: 16, 24, 32, 48, 64, 128 px and 10, 15, 20 mm printed; black only; white on black; on
  a photo; blurred; 1-bit threshold (laser engraving, fax, stamps).
- Responsive set: full lockup → compact → symbol → favicon. Small versions may be redrawn simpler (fewer
  details, heavier strokes, larger counters) instead of shrunk.
- Versions: full color, one-color black, one-color white (reverse), spot, grayscale only if needed.
- Lockups: horizontal, stacked, symbol only, wordmark only, with fixed size ratios and gaps in module
  units; a tagline lockup has its own minimum size.

## 4. Wordmarks and custom lettering
- From a typeface: confirm the license covers logo use and modified outlines (OFL allows both; Adobe
  Fonts allows logos and trademark registration of the logo; commercial EULAs vary, so read the modification
  clause). Outline, then customize: optical kerning per pair, proportions, one signature detail (ligature,
  cut, terminal), consistent stroke contrast and terminals.
- From scratch: draw on baseline/x-height/cap-height guides with overshoots and one stress axis.
- Draw every glyph the name and its variants need, accents included (Portuguese Ã Ç É Ê Ó Õ …), and check
  sub-brand names and both cases.
- Test legibility at 16 px and at signage distance; spacing should look even when blurred.
- Ship outlined; archive the live-type source and the font license with the masters.

## 5. Color system
- Roles: primary (1–2), secondary/accent (2–4), neutrals (ink, grays, paper), semantic states for digital
  products; a proportion guide (60/30/10 as a starting point).
- Each color: reference (Pantone C/U or Lab D50) → CMYK per printing condition (coated and uncoated builds
  differ; name the profile) → sRGB HEX/RGB → optional Display P3 and OKLCH tokens; named and numbered.
- Accessible pairings: a matrix of text/background combinations with their contrast ratios (4.5:1 text,
  3:1 large text, UI and graphics); forbidden pairs marked. Logos are exempt from WCAG contrast, yet a mark
  that vanishes on its background is still a failure.
- Simulate color-vision deficiency (huetension `blindness.simulate`); never let hue alone carry meaning.
- Tools: huetension `harmony.generate`, `gradient.generate`, `contrast.check`, `export.css`,
  `export.tailwind`, `.ase` swatches via its CLI; Illustrator `manage_swatches`, `place_color_chips`.
  Profiles, conversions and ΔE: `color-management`.

## 6. Typography system
Brand/display family and text family (plus mono if needed); a scale per medium; rules for numerals, caps
and language conventions; web font packaging; licensed fallbacks for Office, Google Slides and email
(metrically similar system fonts or Google Fonts families). Details: `typography`.

## 7. Imagery, icons, illustration
- Photography: subjects, light, color grade, crops and composition, what to avoid, do/don't pairs; a
  palette-driven `.cube` LUT can come from the huetension CLI (`lut`).
- Icons: grid (e.g. 24 px with 2 px padding), stroke width, corner radius, caps and joins, filled vs
  outline, metaphor rules; pixel-fit at 1×; delivered as an SVG set.
- Illustration: palette subset, line weight, texture, proportions, perspective; a commissioning brief
  and license terms (exclusivity, transfer).
- Graphic devices: patterns, crops and shapes derived from the mark; motion principles if animated.

## 8. Brand guidelines
1. Essence: positioning, attributes and voice on one page.
2. Logo: versions, construction, clear space (a unit taken from the mark, such as the wordmark's cap height
   or a quarter of the symbol's width, on all sides), minimum size per version (mm for print, px for
   screen, from the scalability tests), placement, approved and forbidden backgrounds, misuse examples
   (stretching, recoloring, rotating, effects, outlines, busy backgrounds, re-typeset wordmark, altered
   lockup ratios).
3. Color: spec table (Pantone C/U, CMYK with profile name, RGB, HEX, OKLCH), proportions, accessible pairs.
4. Typography: families, weights, scale, examples, fallbacks, licensing.
5. Imagery, icons, illustration, graphic devices.
6. Applications and templates; the file matrix (§9); contacts, version, date.
Illustrator MCP shortcuts: `place_style_guide` (colors, fonts, spacing on a non-printing layer),
`place_color_chips`, `extract_design_tokens` (CSS, JSON or Tailwind).

## 9. Export matrix
| Use | Deliver | Color | Notes |
|---|---|---|---|
| Master | `.ai`, one artboard per version and lockup | Spot + process swatches | Live-type source kept apart |
| Print, vector | PDF (PDF/X per `print-production`) | CMYK per condition; spot versions | Type outlined |
| Legacy print, signage | EPS only on request | CMYK/spot | No live transparency |
| Web, apps | SVG | sRGB | `viewBox`, outlined text, no embedded rasters, optimized (`svg-vector-craft`) |
| Raster | PNG with transparency, e.g. 256/512/1024/2048 px wide | sRGB | JPG only where transparency is impossible |
| Favicon | `favicon.ico` 32×32 (add 16×16 only if 32 blurs when downscaled), `icon.svg` (dark mode via `prefers-color-scheme` inside), `apple-touch-icon.png` 180×180, manifest PNGs 192 and 512 + maskable 512 | sRGB | Maskable: essentials inside a centered circle with radius 40 % of the width |
| iOS, iPadOS, macOS app icon | 1024×1024 px layers into Icon Composer (ships with Xcode) | sRGB, Gray Gamma 2.2 or Display P3 | Default, dark, clear and tinted appearances; vector layers preferred; text only if essential; watchOS 1088×1088 |
| Android adaptive icon | 108×108 dp foreground and background layers; 72 dp visible; logo 48–66 dp inside the 66 dp safe zone | sRGB | Monochrome layer for themed icons (Android 13+) |
| Google Play store icon | 512×512 px 32-bit PNG, ≤ 1024 KB, full square | sRGB | Play adds the 30 % corner radius and shadow |
| Social avatars | Square master (1024 px), symbol inside a circular safe area | sRGB | Platforms crop to circles; check current cover sizes at delivery |
File names such as `brand_logo-horizontal_fullcolor_rgb.svg`, `brand_symbol_black_cmyk-coated.pdf`, in
`print/`, `screen/`, `source/`.
```bash
rsvg-convert -w 512 -h 512 symbol.svg -o symbol-512.png
for s in 16 32 48; do rsvg-convert -w $s -h $s favicon.svg -o fav-$s.png; done
convert fav-16.png fav-32.png fav-48.png favicon.ico              # ImageMagick 6; `magick` in 7
convert fav-16.png -filter point -resize 800% fav-16-zoom.png     # inspect pixels, then Read the PNG
```
Illustrator MCP `export` writes SVG/PNG/JPG per artboard (`artboard:all`), with `scale` for rasters
(dpi × scale ≤ 2400) and SVG options (`text_outline`, `decimal_places`); `export_pdf` takes a PDF/X preset,
bleed and `output_intent_profile`.

## 10. Presenting to a client
1. Recap brief, positioning and the agreed criteria.
2. Per direction: the idea in one sentence → the mark in black, large and small → color → 3–5 realistic
   applications with real content (licensed mockups; no third-party brands without permission) → how it
   meets the criteria.
3. A recommendation with reasons; steer feedback to the criteria ("does it signal X?"), not taste.
4. Record decisions and the next round's scope. Present live; send the PDF afterwards marked as a draft.

## 11. Legal guardrails
- Originality: no imitation of existing marks. Similar sight, sound or meaning in the same or related goods
  and services means confusion risk. Screen before presenting finalists and again before adoption: USPTO
  Trademark Search (replaced TESS in 2023), EUIPO eSearch plus, TMview (EU and national offices), WIPO
  Global Brand Database (image search), the national office (Portugal: INPI online search); figurative
  elements by Vienna Classification codes (10th edition), goods and services by Nice class (13th edition, in
  force since 1 January 2026); plus reverse image search, web, domain and handle checks. This is screening
  only: clearance and filing belong to a trademark attorney.
- Third-party logos (partners, clients, app-store and payment badges): only with permission, from official
  kits, unmodified, per their guidelines.
- Fonts must be licensed for logo use (§4). Stock images and icons: many stock licenses exclude use in
  logos or trademarks; check before using any stock element in a mark.
- AI-generated marks: purely AI-generated material is not copyrightable in the US (Copyright Office report,
  January 2025: prompts alone are not enough; Thaler v. Perlmutter, certiorari denied March 2026), and EU
  copyright requires the author's own intellectual creation. Trademark rights don't depend on authorship,
  but an uncopyrightable logo is easier to copy and models can reproduce existing logos. So: read the
  generator's terms, run the similarity screening, rebuild the final as clean vectors with genuine human
  authorship (`svg-vector-craft`), and keep sketches, construction files and iterations as evidence.
- Contract: copyright in the final artwork assigned to the client; AI assistance, third-party elements and
  font licenses disclosed.

## Verify
- Scalability sheet reviewed at every size and version; favicon legible at 16 px (zoomed render read);
  reverse version checked on black and on photos.
- Every color pair in the guidelines computed; every CMYK build soft-proofed for its condition.
- Exports opened: SVGs render the same in a browser and in `rsvg-convert`; PDFs pass `preflight_check`;
  app icons previewed in Icon Composer/Android Studio; the maskable icon viewed under a circular mask.
- Similarity screening documented: databases, queries, classes, Vienna codes, dates, findings.

## Deliverables / Report
- Brief and positioning; three directions with rationale; the final mark with its construction sheet.
- Guidelines PDF; master `.ai`; export folders per §9 with an index (file | use | format | color space |
  size).
- Color spec table and swatch files; type specification with licenses.
- Legal note: searches and results, third-party assets and permissions, AI use and how the final was built.
