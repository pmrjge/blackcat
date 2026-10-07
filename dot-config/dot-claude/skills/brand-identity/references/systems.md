# Wordmarks, color, typography and imagery systems

Part of `brand-identity`.

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
