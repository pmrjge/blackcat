---
name: tattoo-design
description: Load before drawing or revising a tattoo design. Artwork a studio can execute — consultation brief, placement on curved anatomy and distortion, size versus detail as lines spread with age, line weight, negative space and contrast, style conventions, lettering, 1:1 line art and stencil-ready files, value and color references, consented placement mockups, revisions, rights and cultural guardrails.
---
# Tattoo design artwork

## Scope
- Produces the design and the reference files a professional tattoo artist uses to prepare the stencil and tattoo. The artist decides what is executable on that skin and may redraw; needles, machines, stencil application, hygiene and aftercare are the artist's domain: do not advise on them, and route medical questions (allergies, skin conditions, scarring) to the artist or a physician.
- Line art in Illustrator (MCP) or code-generated SVG (`svg-vector-craft` for construction and export), raster painting for values. Image generation (`image-prompting`) only for private mood exploration, never as the delivered design.
- Numeric sizes below are guidance collected from studios, not rules; confirm with the executing artist before finalizing.

## 1. Consultation brief
- Meaning and story; must-have symbols; things to avoid.
- Placement: exact area, orientation (reads upright with the arm down? to the wearer or to others?), visibility at work and in the client's cultural context.
- Size: measure it (§2). Size drives detail more than anything else.
- Style (§5) and references the client likes and dislikes. If the artist is chosen, design within that artist's style and check their healed work.
- Skin: tone, texture, moles, scars, stretch marks, existing tattoos nearby; cover-up? (photo of the old tattoo at scale).
- Color or black-and-grey; sun exposure; acceptance of touch-ups.
- Budget in sessions or hours at the artist's rate; single or multi-session; deadline (events, travel).
- Lettering: exact text, language, verified spelling and translation (§6).
- Rights: who owns any logo, character or artwork requested (§12). The client must be of legal age where tattooed (the studio verifies).

## 2. Anatomy and placement
Measure at the placement: length along the axis, width of the visible face, circumference for anything that wraps; photograph with a tape in frame, camera perpendicular to the skin, in neutral posture and in the positions the area takes (arm raised, fist, seated).

| Area | Surface | Movement and distortion | Design implications |
|---|---|---|---|
| Forearm | truncated cone | pronation twists the outer forearm; half the circumference is visible at once | long vertical compositions along the axis; inner forearm suits lettering |
| Wrist | small, creased, thin skin | flexion creases soften fine lines | small, simple; no fine text across the crease |
| Upper arm, shoulder | cylinder with the deltoid cap | flexing changes shape | follow the deltoid curve; cap designs wrap |
| Ribs, side | curved over ribs | breathing, posture and weight change stretch skin | elongated vertical or diagonal flows; mock up standing and seated |
| Chest, sternum | curved, often asymmetric | stretch with arm movement | symmetric designs on the sternum axis; check standing |
| Back | large, fairly flat | shoulder blades and spine curvature | large compositions; symmetry about the spine |
| Thigh, calf | large cylinders and cones | muscle | large pieces; cone development for wraps |
| Ankle, foot | small circumference, malleoli, tendons | shoe and sock friction, swelling | bold and simple; wraps need a flattened pattern; fine detail blurs |
| Hands, fingers | high friction, fast skin turnover | fading and blurring faster | bold minimal designs; expect touch-ups; many artists limit this work |

Flow: align the main axis with the limb or muscle direction (forearm axis, deltoid curve, rib lines, spine); avoid long straight horizontals across joints; symmetric designs need a body axis to sit on (sternum, spine, neck center).

Wrapping math (build the design on the flat pattern, then mock it up):
- Cylinder of circumference C: the flat band is a rectangle C × h; a motif spanning angle φ is φ/360 · C wide. Seen head-on, a point at angle θ from the view axis is compressed horizontally by cos θ (half width at 60°): circles on the sides read as ellipses.
- Truncated cone (forearm, calf), circumferences C1 < C2, slant length s between them measured along the skin: the flat pattern is an annular sector with inner radius r1 = s·C1/(C2 − C1), outer radius r2 = s·C2/(C2 − C1), angle θ = (C2 − C1)/s radians. A straight band drawn as a rectangle spirals when wrapped; draw it inside the sector. Example: C1 = 16 cm, C2 = 26 cm, s = 20 cm gives r1 = 32 cm, r2 = 52 cm, θ = 0.5 rad (28.6°).
- The artist fine-tunes placement live with the stencil; design for that tolerance (no alignments that fail if moved 5 mm).

## 3. Size versus detail
- Pigment sits in the dermis, held by macrophages that capture and re-capture it for years (Baranska et al., J Exp Med 2018): lines soften and widen, small negative spaces close up, and high-friction or high-turnover areas (hands, fingers, feet) blur and fade faster; UV exposure fades everything.
- Studio guidance: lowercase letters at least about 5 mm tall (one studio requires lettering at least 0.5 in / 12.7 mm tall), more for script, hands and feet; open the letter spacing at small sizes. Working rule: keep counters and gaps no smaller than the neighboring line weight, because gaps close first; details only a few millimeters across disappear. Bold, simple silhouettes survive; "bold will hold" is the traditional rule.
- When the client wants more detail than the area allows: enlarge, simplify, or move to a larger area. Say so early.
- Aging stress test (a visual heuristic, not a prediction): render the art at 1:1 (px = mm × ppi / 25.4; at 600 ppi 1 mm ≈ 23.6 px), thicken dark lines by ~0.1–0.2 mm per side and blur by ~0.2–0.4 mm, then check it still reads at arm's length:
```sh
magick art_600ppi.png -morphology Erode Disk:3 -blur 0x5 aged.png   # Erode grows dark on white; Disk:3 ≈ 0.13 mm, sigma 5 px ≈ 0.21 mm at 600 ppi
```
(ImageMagick 6: `convert`.) Read the result next to the original. If letters or gaps merge, redesign.

## 4. Line weight, negative space, contrast
- Hierarchy: outer silhouette heaviest, main internal forms medium, texture and detail lightest; consistent weights within each tier; fine-line styles use one light weight throughout.
- Skin is the lightest value: there is no reliable white (white ink fades and yellows), so highlights are open skin. Plan negative space as part of the image.
- Values: design in 3–5 steps (black, one or two greys, skin); squint or blur to test; avoid all-midtone designs; solid black near the silhouette improves longevity.
- Darker skin tones reduce the contrast of mid-greys and light colors: lean on black, strong value steps, larger negative spaces; pastels and white read weakly. Ask the artist for healed examples on similar skin.

## 5. Style conventions

| Style | Hallmarks | Implications for the artwork |
|---|---|---|
| Fine-line | thin single-weight lines, little shading, delicate script | larger than clients expect; generous spacing; few crossings; expect softening |
| American traditional | bold black outlines, few strong colors (red, yellow, green), solid fills, black shading, iconic motifs | thick consistent outline; flat color map; minimal gradients |
| Neo-traditional | varied line weights, richer palette, illustrative depth, ornament | line hierarchy critical; color reference with a clear value structure |
| Blackwork | solid black fields, patterns, negative-space motifs | big clean shapes; mark intended skin breaks inside large fields |
| Geometric, dotwork | precise geometry, symmetry, stippled gradients | construct in vector on the flattened body template; geometry distorts on curves, so mock up; give stipple density as a value map |
| Script, lettering | typefaces or hand lettering | exact spelling proof; kerning; baseline following the body (§6) |
| Realism (black-and-grey or color) | photographic values | large size; reference photos you have rights to; value map essential |
| Japanese (irezumi) | traditional motifs and composition rules, large backgrounds (wind bars, waves, clouds) | study the conventions or work with a specialist; composition follows the whole body area |
| Watercolor | soft washes, few or no outlines | soft edges without black structure age poorly; add a structure layer or discuss with the artist |

## 6. Lettering
- Get the text in writing and paste it; never retype. Proofread letter by letter; confirm dates (DD.MM vs MM.DD), numerals and roman numerals; for other languages and scripts (Arabic, Hebrew, CJK, Devanagari, etc.) get a native speaker to verify meaning, grammar, direction and letterforms. Machine translation is not verification.
- Fonts: use a properly licensed font (a purchased desktop license or SIL OFL) and check its EULA for restrictions. Convert to outlines, then adapt: open counters, add spacing, thicken hairlines, simplify flourishes, make script joins deliberate.
- Baseline follows the body contour; decide whether it reads for the wearer or for others; test on the mockup.

## 7. References and mood boards
- Record the source (URL, artist, photographer, license) of every reference. References set direction; never trace or closely copy another artist's flash or custom piece, and don't base a realism piece on a photo without the photographer's permission.
- Board: 6–12 images grouped by aspect (composition, line, value, palette, motif), each annotated with what to take from it.
- Generated images can echo existing tattoos and art: use them only for private exploration and redraw an original design.

## 8. Build workflow
1. Thumbnails: several compositions, small, on the measured placement outline.
2. Rough at 1:1 on the flat template (§2); quick mockup to check flow.
3. Clean line art: vector (preferred: crisp stencils, lossless resizing), or raster at ≥ 600 ppi at 1:1. Expand strokes to outlines at their final weights.
4. Value study in grayscale; color study if color.
5. Aging stress test (§3) and mockups (§10); adjust.
6. Package the deliverables (§9).

## 9. Deliverables for the artist

| File | Spec |
|---|---|
| Line art master | vector PDF/SVG plus 600 ppi PNG, 1:1, black on white, strokes expanded, no hidden layers; a 50 mm scale bar and overall dimensions outside the art; labeled "NOT MIRRORED" |
| Stencil version | pure black (#000000) 1-bit lines only; no greys, fills or anti-aliasing unless the artist asks; 1:1 PDF and 600 ppi PNG; optional dashed or dotted lines for shading or color boundaries if the artist uses that convention; do not mirror unless the artist asks |
| Size variants | the stencil at about 90%, 100% and 110% so the artist can choose at the fitting |
| Value reference | grayscale render in 3–5 values, skin as the lightest |
| Color reference | flat color map with numbered areas plus a rendered preview; screen colors do not map to tattoo ink brands, so treat it as intent |
| Placement mockups | on the client's photos (§10), at least two angles, with scale |
| Notes | meaning, must-keep versus flexible elements, confirmed text, reference sources and licenses |

Stencil from line art (ImageMagick 7; IM6 uses `convert`; verified):
```sh
magick lineart.png -colorspace Gray -threshold 50% -type Bilevel -units PixelsPerInch -density 600 stencil.png
magick stencil.png -units PixelsPerInch -density 600 stencil.pdf    # page size = pixels / 600 in, i.e. 1:1
pdfinfo stencil.pdf | grep -a "Page size"                           # pt / 72 = inches; -a: IM writes a NUL into Title
magick identify -format "%[type]\n" stencil.png                     # Bilevel
```
Size variants: `magick stencil.png -resize 110% -threshold 50% -type Bilevel -units PixelsPerInch -density 600 stencil_110.png` (re-threshold after resampling), or scale the vector and re-export.

## 10. Placement mockups
- Consent: written consent to use the client's body photos for this project; keep them local in the project folder; never upload them to third-party services (image generation, online mockup tools) without explicit consent; don't publish mockups without consent; delete on request or when the project closes.
- Method: warp the line art onto the photo (Photoshop Warp, Puppet Warp or a displacement map, or map the flattened template), match perspective and scale using the tape in frame, multiply blend; label mockups as approximate.

## 11. Revision workflow
- Version files `<design>_v01…`, with a short change log (what changed and why); agree the number of revision rounds up front; compare versions as overlays at 1:1.
- Final approval in writing: design version, size, placement and the exact text. Freeze the approved files and hand them over; later changes go through the artist, who may adapt the design to the skin and their technique.

## 12. Legal and ethical guardrails
- Trademarks and logos (brands, teams, event and race-series marks): the mark belongs to its owner even on skin. Note the rights holder in the brief and let the client decide with the artist; reproduce officially supplied artwork faithfully instead of inventing variants; never sell, publish as flash or reuse the design commercially without a license.
- Other artists' work: no copying of flash or custom pieces; credit references; refuse "exact copy" requests of another artist's tattoo, or get that artist's permission.
- Cultural and religious symbols: research origin and meaning before using them. Māori tā moko carries genealogy and identity and is not for outsiders to copy; Māori-inspired work for non-Māori (kirituhi) still needs cultural input, ideally from a Māori practitioner. Take similar care with Polynesian tatau, sacred scripts, deities and religious figures (some traditions consider certain placements, such as below the waist, disrespectful). Refuse hate symbols.
- Privacy: body photos are sensitive personal data (§10).

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Small text unreadable after a few years | letters too small, spacing too tight | ≥ ~5 mm lowercase, open spacing, bolder weight, or a larger area |
| Design looks distorted on the body | drawn flat for a curved area | measured template, cone/cylinder development, mockups |
| Stencil misses lines | grey, anti-aliased or hairline lines | 1-bit pure black, thicker lines |
| Tattoo reversed | pre-mirrored file | deliver unmirrored and labeled; the artist mirrors if their process needs it |
| Color expectations missed | screen RGB treated as ink colors | value structure plus a color intent map; discuss inks with the artist |
| Spelling or translation error | unverified text | written confirmation, native-speaker check |
| Too close to another artist's piece | a single reference followed too literally | combine multiple references, redraw originally |

## Verify
- Physical size equals the measurement (`pdfinfo` page size; the 50 mm bar measures 50 mm when printed at 100%); hold a 100% print against the body.
- The aging stress test still reads; the stencil file is Bilevel; line art has no hidden layers or stray points; text proofed against the written confirmation.
- Mockups exist from at least two angles; every reference and font has a recorded source and license; nothing trademarked or cultural is used without the note in §12.

## Deliverables / report
- The files in §9 with paths, plus a short summary: size and placement, style, value/color decisions, what was simplified for longevity and why, open questions for the artist, and the rights notes.
