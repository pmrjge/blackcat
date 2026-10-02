# Brand identity and logo design: export matrix

Read when exporting logo and asset files (moved from `brand-identity` SKILL.md).

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
