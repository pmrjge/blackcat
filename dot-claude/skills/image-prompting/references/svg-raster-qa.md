# Image prompting: SVG QA and raster post-processing

## 9. SVG QA and clean-up
- Root viewBox, sensible width/height; `paths` from the result (hundreds for an icon means
  over-detailed); stray specks, hidden shapes, needless clip paths and masks.
- An embedded raster (`<image>` with a data: URI) defeats the point: regenerate or redraw.
- `npx svgo --multipass in.svg -o out.svg`, then confirm the viewBox survived; `role="img"` and a
  `<title>` for web use. Rasterize at 16, 32 and 48 px to check small sizes.

## 10. Raster post-processing
- Prefer native resolution (`generate_image` or `edit_image` at 4K) over upscaling. Upscaling invents
  detail: up to 2× is usually safe for photos; inspect faces, hands, text and fabric at 100 %; never
  upscale text or logos.
- Background removal: `background="transparent"` first (either raster tool); otherwise rembg with
  `-m birefnet-general` (MIT; its default model is non-commercial). Check edges over black, white and
  mid-gray.
- Compositing: match perspective and horizon, lens and depth of field, light direction and softness,
  color temperature, black level, grain and sharpness; add contact shadows. `edit_image` can harmonize
  ("match the product's light and color to the scene; keep its shape, label and colors unchanged").
- Color: outputs are 8-bit sRGB. Web: keep sRGB. Print: convert once at the end with the printer's
  profile (`color-management`).
- Raster exports of an SVG, only when asked: `rsvg-convert -w 1024 logo.svg -o logo.png`; PDF with
  `-f pdf`; favicon `magick -background none logo.svg -define icon:auto-resize=16,32,48 favicon.ico`.
