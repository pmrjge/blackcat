# Method-specific rules

Part of `apparel-merch-print`.

## 3. Screen printing
Separation types:

| Type | Use | Screens |
|---|---|---|
| Spot | logos, flat art; one screen per ink, halftones for tints | 1–6 |
| Simulated process | photoreal art on dark garments: opaque spot inks + halftones + underbase | often 7–10 |
| Index | square or stochastic dots from a limited palette; forgiving registration | 4–10 |
| CMYK process | photos on white or light garments only (transparent inks) | 4 |

- Underbase: white printed first under colors on dark garments, flashed, choked slightly so it never shows at edges; highlight white printed last. Count both as screens.
- Halftones: garment work runs about 35–65 LPI (45 LPI is a common default); mesh ≈ 4–5 × LPI (e.g., 45 LPI on ~200–230 mesh); angle 22.5° to avoid moiré with the mesh; elliptical or round dots; holding an 8% dot is high quality, so remap tints below that. Supply grayscale separations at 1:1 and let the shop's RIP screen them unless they ask for pre-screened bitmaps.
- Mesh reference: 60 athletic; 86 heavy ink, puff, dark garments; 110 underbase for block letters; 156 general on light garments; 196 multicolor; 230 sim-process underbase; 305 process and fine halftones.
- Minimum features: lines ≥ 1 pt (0.35 mm), 1.5 pt safer on tees; text ≥ 8 pt; reversed (knocked-out) text and fine negative space larger; ink spreads on ribbed, fleece and textured fabric.
- Files: vector (AI, PDF, EPS, SVG), fonts outlined, one spot swatch per ink named with its Pantone reference (Pantone Solid Coated is the usual ink-matching book), each ink on its own layer; sim process as layered PSD/TIFF with named spot channels at 1:1, 300 ppi; print size, placement and garment color on a spec page.

## 4. DTG
- PNG with transparency, sRGB IEC61966-2.1, at print size, ≥ 150 ppi minimum (300 ppi preferred).
- Semi-transparent pixels fail: DTG inks are concentrated and spread, leaving gaps with the white base showing. No soft shadows, feathered edges or opacity < 100% on dark garments; convert fades to halftones; threshold anti-aliased edges.
- Dark garments are pretreated and printed on a white underbase the RIP builds from your alpha channel. Knock black out of designs on black shirts (let the fabric be the black) instead of printing a black-on-white patch; thicken very thin light details so they keep underbase.
- Neon and many Pantone brand colors are out of the CMYK-plus-white gamut: flag them.

Check and fix transparency (sci venv has numpy and Pillow; ImageMagick 7 `magick`, IM6 `convert`):
```sh
__CLAUDE_DIR__/venvs/sci/bin/python -c "
import sys, numpy as np; from PIL import Image
a = np.asarray(Image.open(sys.argv[1]).convert('RGBA'))[..., 3]
print('semi-transparent px:', int(((a > 0) & (a < 255)).sum()), 'of', a.size)" art.png
magick art.png -channel A -threshold 50% +channel art_hard.png          # hard edges
magick art.png -channel A -ordered-dither h8x8a +channel art_ht.png     # fades -> halftone alpha
```
The halftone cell is in pixels: at 300 ppi an orthogonal 8 px cell (`h8x8o`) is 37.5 LPI; angled maps (`h8x8a`) differ. Match the vendor's recommended LPI.

## 5. DTF
- PNG, transparent background, RGB, 300 ppi at print size.
- Any pixel with alpha receives adhesive powder: semi-transparency prints as haze or speckle, so use the §4 check and fixes. Every isolated fragment becomes a separate film piece; tiny dots and hairlines peel. Lines ≥ ~2 pt (Sticker Mule's DTF and hat guidance).
- Large solid areas feel like a patch: break them with negative space or distressing.

## 6. Sublimation
- Polyester only (or poly-coated hard goods), white or light: sublimation dye is transparent and there is no white ink. Blends below ~65% polyester look faded and wash out.
- Finished garments: seams, collars and underarm folds the transfer cannot touch stay white. All-over prints are cut-and-sew: print per-size panel templates (front, back, sleeves for every size), extend art to the template's bleed, keep faces and text away from seams, and align patterns across seams only if promised.
- Files: RGB (or the vendor's profile) at 1:1 per panel, 150–300 ppi per the vendor, patterns as vectors or seamless tiles.

## 7. Heat-transfer vinyl
- Vector cut paths, one layer per vinyl color; supply unmirrored and say so (the cutter mirrors).
- Weeding limits (Printify specialty vinyl): glitter/metallic lines ≥ 1.8 mm, text ≥ 6.5 mm, gaps ≥ 1.5 mm; puff lines 3–5 mm, text ≥ 31 mm, gaps ≥ 3 mm. Keep layered vinyl to 2–3 layers.

## 8. Embroidery
- A digitizer converts art to stitches (satin, fill/tatami, run) with underlay and pull compensation. Deliver clean vector art or 300 ppi raster at the finished size; get back the native file (e.g., Wilcom EMB, editable) and the machine file (DST for Tajima-compatible machines: stitches and commands only, no colors; PES Brother; EXP Melco). Resizing a machine file changes stitch length and density (limits commonly cited at 10–20%): resize from the native file or re-digitize.
- Guidance (confirm with the digitizer): text ≥ 0.25 in (6.35 mm) lowercase and ≥ 0.3 in uppercase (some accept 5 mm); lines ≥ 0.05 in (1.3 mm); gaps ≥ 0.05 in; satin columns within ~10 mm (Wilcom), wider areas become fill; no gradients, photos, fine negative space or thin script.
- Sizes: left chest 3.5–4 in wide (up to ~4.5 in); cap front typically ≤ ~2.1 in tall × ~4.5 in wide (varies with cap profile and frame); POD large front up to 10 × 6 in.
- Stitch counts: left-chest logos commonly 6,000–12,000; fills ~1,250–1,500 stitches per square inch, satin borders ~150–200 per linear inch; 3D puff 1.5–2 ×. Big fills are expensive and stiff; use satin outlines, open fills or appliqué.
- Colors by thread chart code (Madeira, Isacord, Robison-Anton); Pantone is only a reference. Approve a sew-out before production.
