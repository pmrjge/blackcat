---
name: tattoo-design
description: Load before drawing a tattoo — placement, ageing of detail, line weight, lettering, stencils, mockups.
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

Area-by-area surfaces, movement and design implications (forearm, wrist, ribs, back, hands …) and the cylinder/cone wrapping math with a worked example: `references/placement.md`.

Flow: align the main axis with the limb or muscle direction (forearm axis, deltoid curve, rib lines, spine); avoid long straight horizontals across joints; symmetric designs need a body axis to sit on (sternum, spine, neck center).

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
Hallmarks and artwork implications per style (fine-line, American traditional, neo-traditional, blackwork, geometric/dotwork, script, realism, Japanese, watercolor): `references/styles.md`.

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
Line art master, stencil (1-bit pure black, 1:1, never mirrored unless asked), 90/100/110% size variants, value and color references, mockups and notes; file specs and the verified ImageMagick stencil commands: `references/deliverables.md`.

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
