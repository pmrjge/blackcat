# Color management: print cmyk spot

Read when converting RGB to CMYK or handling spot and Pantone colors (moved from `color-management` SKILL.md).

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
