# Deliverables for the artist
Read from `tattoo-design` (core rules in its SKILL.md).

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
