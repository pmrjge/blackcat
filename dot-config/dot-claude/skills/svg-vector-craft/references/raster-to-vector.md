# Raster to vector
Read from `svg-vector-craft` (core rules in its SKILL.md).

## 6. Raster to vector
Choose: logos and wordmarks → rebuild by hand over a trace (true circles and straight lines, the identified and licensed typeface); line art and sketches → potrace; flat-color art → vtracer or Image Trace; photos → only for a deliberate posterized look.
- Illustrator Image Trace: Mode (Black and White, Grayscale, Color), Palette/Colors, Threshold; Advanced: Paths (fidelity), Corners, Noise (minimum area in px), Method Abutting (no overlaps, good for cutting) or Overlapping (stacked), Create Fills/Strokes, Snap Curves To Lines, Ignore White; then Object › Image Trace › Expand. Upscale small sources 2–4× first.
- potrace (PNM/BMP input only; verified):
```sh
magick in.png -colorspace Gray in.pgm                      # ImageMagick 6: convert
mkbitmap -f 4 -s 2 -t 0.45 in.pgm -o in.pbm                # highpass radius, 2x upscale, threshold (the defaults)
potrace -s --tight -t 4 -a 1 -O 0.2 in.pbm -o out.svg      # -t speckle area, -a corners (0 polygon .. 4/3 no corners), -O curve tolerance
potrace -b dxf in.pbm -o out.dxf                           # also -b pdf, -b eps; -W/-H/-r set physical size
```
potrace SVG uses pt units and a `scale(0.1,-0.1)` group transform; bake transforms before editing numerically.
- vtracer 0.6.x CLI (`cargo install vtracer`; the 1.0 alphas rename flags, check `vtracer --help`):
```sh
vtracer --input in.png --output out.svg --colormode color --hierarchical cutout --mode spline \
  --filter_speckle 4 --color_precision 6 --gradient_step 16 --corner_threshold 60 \
  --segment_length 4 --splice_threshold 45 --path_precision 3
```
`--colormode bw` for binary; `--hierarchical stacked` (default) layers shapes, `cutout` gives non-overlapping shapes (better for vinyl and cutting); `--preset bw|poster|photo`. Python package `vtracer`: `vtracer.convert_image_to_svg_py(inp, out, colormode="binary", hierarchical="cutout", mode="spline", filter_speckle=4, path_precision=3)`. The Python binding spells binary mode `"binary"` and silently falls back to color on unknown values (`"bw"` gives a color trace). Output has pixel width/height, no viewBox, and a `translate()` on every path: add a viewBox and physical size, bake transforms.
- Cleanup: delete speckles, merge same-color neighbors, reduce anchors, replace near-circles and near-lines with true primitives, unify stroke weights, sharpen corners, align to a grid; overlay on the source at 400% and against the brand guide.
