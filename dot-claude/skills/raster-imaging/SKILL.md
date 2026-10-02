---
name: raster-imaging
description: Load before resizing, converting, compositing or compressing images in code — magick, vips, Pillow.
---
# Raster imaging

## Scope
- Deterministic pixel work: resize, crop, pad, convert, composite, quantize, rasterize, compress, inspect. Generating or AI-editing images is image-studio's job (`image-prompting`); vectorizing rasters is in `svg-vector-craft`; color science in `color-management`; print halftones and separations in `print-production` and `apparel-merch-print`; video frames in `media-ffmpeg`.
- Tools: ImageMagick 7 (`magick …`; `convert` is the deprecated v6 name), libvips (`vips`, `vipsthumbnail`, pyvips — fast, streaming, low memory; the choice for big images and batches), Pillow (Python glue), OpenCV (analysis), macOS `sips`, encoders (`oxipng`, `pngquant`, `cjpeg` from mozjpeg, `cwebp`, `avifenc`, `cjxl`), `exiftool`, `resvg`/`rsvg-convert`/`inkscape` for SVG.
- Always write to a new file; never overwrite the user's original.

## Inspect first
`magick identify -verbose in.png | head -40` (size, depth, colorspace, profile, alpha), `vipsheader -a in.tif`, `exiftool -a -G1 in.jpg` (orientation, profile, GPS). Then Read the image when its content matters.

## Resampling
- Downscale with a good filter: Lanczos (IM default for downsizing is fine; `-filter Lanczos`), libvips `thumbnail`/`resize` (Lanczos3 by default). Box/area averaging for large integer factors.
- Gamma-correct resizing avoids darkened edges and thin lines: `magick in.png -colorspace RGB -resize 50% -colorspace sRGB out.png` (linearize, resize, back); libvips: `vips resize … --kernel lanczos3` on a linear-light image (`vips colourspace in.png lin.v scrgb`).
- Light sharpening after strong downscales: `-unsharp 0x0.75+0.75+0.008`.
- Upscaling adds no detail: for pixel art use nearest neighbour at integer factors (`-filter point -resize 400%`); for photos use a model (Real-ESRGAN, or `edit_image` for AI upscale) and say it's synthesized.
- Shrink-only in batch: `-resize '1920x1920>'` (the `>` never enlarges). The stack's upload limit (any side ≤ 1919 px) is `sips -Z 1919 in.png --out out.png` or `magick in.png -resize '1919x1919>' out.png`.

## Alpha and compositing
- Resize and blur in premultiplied alpha, or edges get dark/light halos; IM handles it for `-resize`, but custom pipelines in numpy/Pillow must premultiply first.
- `-background none` for transparent canvases; `-alpha off`/`-flatten -background white` to drop alpha deliberately (JPEG has none).
- Composite: `magick base.png overlay.png -gravity southeast -geometry +24+24 -composite out.png`; blend modes via `-compose multiply|screen|overlay …`; masks with `-compose CopyOpacity`.
- Trim and pad: `-trim +repage`, `-gravity center -extent 1200x630`, `-bordercolor none -border 20`.
- Background removal: rembg (local model) or `edit_image`; check hair/edges at 100 %.

## Rasterizing SVG
- `resvg in.svg out.png -w 2048` (strict, fast, consistent), `rsvg-convert -w 2048 -o out.png in.svg` (librsvg), `inkscape in.svg --export-type=png --export-width=2048` (closest to Inkscape's own rendering), `magick -density 300 in.svg out.png` (delegates; least predictable).
- Fonts must be installed on the machine or converted to outlines, or text falls back silently — compare renders from two engines when in doubt. For print, rasterize at final size × 300 ppi (`-d 300 -p 300` in rsvg-convert).

## Color and depth
- Keep or convert embedded ICC profiles deliberately: `magick in.jpg -profile /path/sRGB.icc out.jpg` converts when a source profile exists; `vips icc_transform in.jpg out.jpg srgb`. `-strip` removes profiles *and* metadata — follow with an explicit sRGB tag for web output.
- Web deliverables: sRGB (or Display P3 with an embedded profile when wide gamut is intended). Print: CMYK conversion with the printer's profile in `color-management`/`print-production`, not ad hoc.
- 16-bit for editing and gradients; 8-bit for delivery; dither when reducing depth to avoid banding (`-dither FloydSteinberg`).

## Formats and encoding
| Format | Use | Command hints |
|---|---|---|
| PNG | graphics, UI, screenshots, alpha, lossless | `oxipng -o 4 --strip safe`; lossy palette `pngquant --quality 65-85` |
| JPEG | photos | mozjpeg `cjpeg -quality 80`; `-sampling-factor 4:4:4` for sharp text/lines (4:2:0 smears color edges); progressive |
| WebP | web photos and graphics with alpha | `cwebp -q 80`, `-lossless` for graphics |
| AVIF | best compression for photos on the web | `avifenc -q 60 --speed 6`; slow encode |
| JPEG XL | high quality, lossless JPEG recompression | `cjxl in.jpg out.jxl` (lossless transcode); check target support |
| TIFF | print masters, archives | LZW/ZIP compression, 16-bit, embedded profile |
| GIF | legacy animation | prefer WebP/AVIF/MP4; palette ≤ 256 |
| ICO/ICNS | app and favicon icons | `magick in.png -define icon:auto-resize=16,32,48,256 favicon.ico`; macOS `iconutil -c icns icon.iconset` |
- Pick quality by measurement, not habit: SSIMULACRA2 (`ssimulacra2 ref.png test.png`; about 90 = visually lossless at 1:1, 70 = high quality, 50 = medium), butteraugli, or `magick compare -metric SSIM a.png b.png null:`. Compare at 100 % crop too.

## Quantization and dithering
Limited palettes (screen printing, e-ink, pixel art, GIF): `magick in.png -dither FloydSteinberg -colors 16 out.png`, ordered dither `-ordered-dither o8x8`, remap to a fixed palette `-remap palette.png`; posterize for spot-color separations (`apparel-merch-print`).

## Batch pipelines
```bash
mkdir -p out
vipsthumbnail photos/*.jpg -s 1920x1920 -o "$PWD/out/%s.webp[Q=82,keep=none]"   # fast, shrink-to-fit; -o is relative to each input's folder unless absolute (keep=none needs libvips ≥ 8.15; older: strip)
find src -name '*.png' -print0 | xargs -0 -n1 -P8 sh -c 'magick "$0" -resize "1200x1200>" "out/$(basename "$0")"'
magick mogrify -path out -auto-orient -resize '2048x2048>' -quality 82 *.jpg   # never mogrify in place
```
- `-auto-orient` (or vips' autorotate) before anything else for camera JPEGs.
- Metadata: strip location data before publishing (`exiftool -gps:all= -xmp:geotag= out.jpg`); keep copyright/IPTC when the user wants it.
- Contact sheets for review: `magick montage out/*.png -tile 6x -geometry 320x320+8+8 sheet.png`, then Read the sheet.

## Checklist
Originals untouched · inspected before processing · gamma/alpha handled · ICC profile intended and embedded · format and quality chosen by use and measured · metadata policy applied · result Read at 100 % crop and full view.
