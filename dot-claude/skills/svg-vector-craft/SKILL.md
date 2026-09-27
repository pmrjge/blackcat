---
name: svg-vector-craft
description: Load before creating, converting or delivering vector files. Production-grade vector work — path construction, booleans and compound paths, SVG as code in real units, parametric drawings from Python or JavaScript, safe svgo settings, Illustrator practice and scripting, tracing (Image Trace, potrace, vtracer), cutter/laser/plotter output, SVG/PDF/EPS/DXF export and QA.
---
# Vector and SVG craft

## Scope
- Covers path construction, SVG as code, generated drawings, optimization, Illustrator practice and scripting, tracing, fabrication output, export formats and QA.
- Not here: print color, PDF/X and preflight (`print-production`), garment separations and embroidery (`apparel-merch-print`), tattoo stencils (`tattoo-design`), screen-driven app control (`computer-use-apps`).
- Tools verified for this skill: svgo 4.1, potrace 1.16, vtracer 0.6.5 (CLI) / 0.6.15 (Python), Inkscape 1.x CLI, librsvg `rsvg-convert` 2.58, ezdxf 1.4, vpype 1.15, svgelements 1.9, skia-pathops 0.9, drawsvg 2.4.

## 1. Construction
- Anchor economy: the fewest points that hold the shape. Put points at extrema (leftmost, rightmost, top, bottom) with horizontal/vertical handles, at true corners, and at inflections only when needed. Extra points cause wobble and bloat.
- Handles: smooth points have collinear handles (G1); handle length roughly 1/3 of the segment chord; no handles crossing or reversing. A quarter circle uses handles of κ·r with κ = 4(√2 − 1)/3 ≈ 0.5523. Collinear handles give only G1; curvature continuity (G2) also needs matching curvature on both sides, which depends on the handle lengths: check with a curvature comb where the tool has one.
- Booleans: Illustrator Pathfinder shape modes (Unite, Minus Front, Intersect, Exclude, then Expand), Divide/Trim/Merge, Shape Builder; Inkscape Path › Union/Difference; in code `skia-pathops` (`pathops.op(a, b, PathOp.UNION)`). Afterwards remove redundant anchors and stray points.
- Stroke to outline: Illustrator Object › Path › Outline Stroke, Inkscape Path › Stroke to Path, `skia-pathops` `path.stroke(width, cap, join, miter_limit)`. Do it for cutters, stencils, embroidery digitizers and fonts-free delivery; keep a stroked master.
- Compound paths and fill rules: holes are subpaths of one compound path. `fill-rule="nonzero"` depends on direction (holes must run opposite to the outer contour); `evenodd` does not. Illustrator compound paths default to non-zero (toggle in the Attributes panel). Cutters ignore fill rules: every subpath is cut.
- Grids: construct on a grid or keyline system; snap endpoints; align icons to the pixel grid at 1× for screens; use a mm grid for print and fabrication.
- Optical vs mathematical: round and pointed shapes overshoot the baseline and cap height (about 1–3% of the height in type design); triangles and play icons are centered by visual mass, not the bounding box; a circle needs to be larger than a square to look the same size; horizontals look heavier than verticals of equal width. Judge at the target size.

## 2. SVG as code
```xml
<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="210mm" height="297mm" viewBox="0 0 210 297">   <!-- 1 user unit = 1 mm -->
  <title>Part A cut sheet</title>
  <g id="cut" inkscape:groupmode="layer" inkscape:label="cut">…</g>
</svg>
```
- Units: absolute units on width/height with the same numbers in the viewBox give 1 unit = 1 mm (or in). CSS and browsers use 96 px/in (1 mm = 3.7795 px); unitless width means px. Illustrator reads and writes SVG at 72 units/in (1 px = 1 pt), which is the classic 75%/133% scale error: always carry absolute units and check the size after import.
- Precision: 3 decimals in mm is 1 µm; 2 decimals suffices for px-based web icons.
- Structure: one top-level `<g>` per layer or production step with stable semantic IDs (`cut-inner`, `cut-outer`, `score`, `engrave`, `print`, `notes`). Inkscape recognizes `inkscape:groupmode="layer"` plus `inkscape:label` (declare the namespace). Illustrator exports layers as `<g id>` (Object IDs: Layer Names); after importing into Illustrator, check the Layers panel.
- Transforms compose right to left; for CAD and fabrication bake them into coordinates (svgelements `reify()`, Inkscape Object to Path, re-export from Illustrator). Non-uniform scaling distorts strokes.
- `<symbol id viewBox>` + `<use href="#id">` for repeats; older importers and some cutter software only read `xlink:href`, so add it (with `xmlns:xlink`) or expand the uses before delivery.
- Text: live `<text>` with a font stack for web (accessible, selectable); outlined text for print, fabrication, logos and anything opened where the font is missing. Text on a path renders differently across renderers: outline it.
- Images: embedded `data:` URIs are portable but large; linked files break when moved. Ship linked originals in the package for print.
- Accessibility on the web: `<title>` as first child, `role="img"`, `aria-labelledby` pointing at the title id (or `aria-label`); decorative graphics get `aria-hidden="true"`.
- SVG strokes are always centered: expand inside/outside-aligned Illustrator strokes before exporting.

## 3. Parametric and generated drawings
Pattern (tested; plain Python, no dependencies): parameters in mm, geometry as path strings with fixed precision, one layer per production step, arrowheads drawn as paths (markers are ignored by many cutters and CAD converters), notes on a non-production layer.
```python
"""Parametric panel in mm: outer cut, four holes, centre score, one dimension, 50 mm scale bar."""
import math
W, H, R, HOLE, INSET, M = 120.0, 80.0, 6.0, 5.0, 10.0, 15.0   # parameters; M = sheet margin for notes

def f(v):                                          # fixed precision, never "-0"
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s

def rrect(x, y, w, h, r):
    a = f"A{f(r)} {f(r)} 0 0 1"
    return (f"M{f(x+r)} {f(y)}H{f(x+w-r)}{a} {f(x+w)} {f(y+r)}V{f(y+h-r)}{a} {f(x+w-r)} {f(y+h)}"
            f"H{f(x+r)}{a} {f(x)} {f(y+h-r)}V{f(y+r)}{a} {f(x+r)} {f(y)}Z")

def circle(cx, cy, r):                             # closed path of two arcs
    return f"M{f(cx-r)} {f(cy)}A{f(r)} {f(r)} 0 1 0 {f(cx+r)} {f(cy)}A{f(r)} {f(r)} 0 1 0 {f(cx-r)} {f(cy)}Z"

def arrow(x, y, ang, L=2.0, w=0.7):                # filled arrowhead path; <marker> is not portable
    c, s = math.cos(ang), math.sin(ang)
    return f"M{f(x)} {f(y)}L{f(x-L*c+w*s)} {f(y-L*s-w*c)}L{f(x-L*c-w*s)} {f(y-L*s+w*c)}Z"

def layer(name, attrs, body):
    return f'<g id="{name}" inkscape:groupmode="layer" inkscape:label="{name}" {attrs}>{body}</g>\n'

SW, SH, yd = W + 2*M, H + 2*M, M + H + 7
cut = 'fill="none" stroke="#ff0000" stroke-width="0.01"'
holes = "".join(circle(M+cx, M+cy, HOLE/2) for cx in (INSET, W-INSET) for cy in (INSET, H-INSET))
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
       f'width="{f(SW)}mm" height="{f(SH)}mm" viewBox="0 0 {f(SW)} {f(SH)}">\n<title>Panel {f(W)} x {f(H)} mm</title>\n'
       + layer("cut-inner", cut, f'<path d="{holes}"/>')           # inner cuts first
       + layer("cut-outer", cut, f'<path d="{rrect(M, M, W, H, R)}"/>')
       + layer("score", 'fill="none" stroke="#0000ff" stroke-width="0.01"', f'<path d="M{f(M+W/2)} {f(M)}V{f(M+H)}"/>')
       + layer("notes", 'fill="#808080" font-family="sans-serif" font-size="3.5"',
               f'<path fill="none" stroke="#808080" stroke-width="0.2" d="M{f(M)} {f(M+H+1)}V{f(yd+1.5)}'
               f'M{f(M+W)} {f(M+H+1)}V{f(yd+1.5)}M{f(M)} {f(yd)}H{f(M+W)}M{f(M)} {f(SH-3)}h50"/>'
               f'<path d="{arrow(M, yd, math.pi)}{arrow(M+W, yd, 0)}"/>'
               f'<text x="{f(M+W/2)}" y="{f(yd-1)}" text-anchor="middle">{f(W)}</text>'
               f'<text x="{f(M+52)}" y="{f(SH-2)}">50 mm</text>')
       + "</svg>\n")
open("panel.svg", "w").write(svg)
```
- Drawing conventions: extension lines with a small gap from the part, dimension line with arrowheads, value above the line, units stated once in a title block (name, scale, units, material and thickness, revision, date); a scale bar and "print at 100%" note; notes layer in a non-production color.
- Kerf: offset part outlines outward and holes inward by kerf/2 when the machine software does not; measure kerf on a test cut.
- Deterministic output (fixed precision, stable element order and IDs) keeps diffs reviewable; store parameters in `<metadata>` or `data-*` attributes. Property-test generators with hypothesis (sci venv) for invariants: cut paths closed, overall size equals the parameters, holes inside the part.
- Libraries: drawsvg 2.x (`Drawing(w, h)`, `set_render_size('100mm', '50mm')` writes mm width/height with a matching viewBox); svgelements (parse with units and transforms); svgpathtools (lengths, intersections); skia-pathops (booleans, stroke outlines); shapely (offsets/buffers on polylines); ezdxf (DXF); JavaScript: `@svgdotjs/svg.js` 3.x (DOM; Node needs `svgdom`), paper.js (booleans), opentype.js (text to paths from a licensed font file).
- Hairline strokes are invisible in previews: render a copy with a CSS override, `printf 'path{stroke-width:.4 !important}' > preview.css; rsvg-convert -s preview.css -d 100 -p 100 -o preview.png panel.svg`, then Read the PNG.

## 4. Optimization with svgo 4
Keep an editable master; optimize copies. Verified svgo 4.1 defaults: removes Inkscape layer attributes and namespaces, deletes "unused" IDs (including a `<title id>` referenced by `aria-labelledby`, breaking the accessible name), strips `role`, collapses groups, merges same-style paths into one, converts shapes to paths and deletes hidden elements. `removeViewBox` and `removeTitle` are no longer in the default preset. svgo looks for `svgo.config.mjs` in the current directory and its parents, so a stray config applies silently: pass `--config`.
```js
// svgo.config.mjs: production-safe (tested): keeps layers, IDs, shapes, per-object paths, a11y and units
export default {
  multipass: true,
  js2svg: { pretty: true, indent: 2 },
  plugins: [{
    name: 'preset-default',
    params: { overrides: {
      cleanupIds: false, collapseGroups: false, mergePaths: false,
      convertShapeToPath: false, removeHiddenElems: false, removeEditorsNSData: false,
      removeUnknownsAndDefaults: { keepRoleAttr: true },
      cleanupNumericValues: { floatPrecision: 4, convertToPx: false },
      convertPathData: { floatPrecision: 4 },
    } },
  }],
};
```
Run `npx svgo@4 --config svgo.config.mjs in.svg -o out.svg`. For fabrication also set `moveElemsAttrsToGroup: false` and `convertColors: false` so every path keeps the exact hex color the machine maps to an operation (default output rewrites `#ff0000` as `red`). For inline web icons, keep only the IDs you reference (`cleanupIds: { preserve: [...] }`) and use `prefixIds` when several SVGs share a page.

## 5. Illustrator practice
- One artboard per deliverable or size, named; artboard = trim for print.
- Swatches: Global process swatches for brand colors (edit once, update everywhere); Spot swatches for Pantone inks and technical plates (die, foil, varnish, white); delete unused swatches before delivery.
- Graphic Styles for repeated appearances (a cut line: 0.25 pt stroke, spot `CutContour`, overprint); Character/Paragraph Styles for type; Symbols for repeated elements.
- Effect › Document Raster Effects Settings at the output resolution; decide Scale Strokes & Effects before scaling.
- Keep a master .ai with live text and appearances; derive delivery copies (outlined text, expanded appearances); File › Package collects links and fonts.
- Scripting: ExtendScript (.jsx) via File › Scripts, or `osascript -e 'tell application "Adobe Illustrator" to do javascript "app.activeDocument.name"'`. As of mid-2026 Illustrator has no public UXP API for third-party code (CEP remains for panels); check before assuming. Script units are points (1 pt = 0.3528 mm); `PathItem.closed` finds open paths; the API cannot read the document bleed setting.
- Illustrator MCP server, when mounted: list its tools first. Typical coverage: document, artboard and layer info; creating paths and text; importing SVG as editable objects; swatches; overprint, separation and preflight info; SVG/PNG/PDF export. Confirm the coordinate system it reports (print and web documents can differ), confirm each export on disk (`ls -la`), and Read a PNG render for visual QA. Use the screen only when no scripted route exists (`computer-use-apps`).

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

## 7. Cutting, engraving and plotting output
- Vinyl and print-and-cut: closed paths; the cut line as a spot swatch named for the RIP (Roland VersaWorks: `CutContour`, stroke 0.25 pt); extend printed art 1–3 pt past the cut line against white slivers; respect the material's minimum text and weeding sizes.
- Laser: operation by stroke color, and the mapping is shop-specific (one Epilog lab uses blue #0000FF cut, red #FF0000 vector engrave, black raster; others use red for cut): get the shop's table. RGB document; hairline strokes as the driver defines them (e.g., 0.001 pt or 0.001 in; thicker strokes may be treated as raster engraving in print-driver workflows); fills only for raster engraving; closed cut paths; no duplicates or overlaps (double burns); inner cuts before outer; text outlined; delete hidden objects and release clipping masks (the clipped geometry is still cut).
- Pen plotters: strokes only; `vpype read in.svg linemerge --tolerance 0.1mm linesort write out.svg` merges touching lines and orders them to cut pen-up travel (vpype converts curves to polylines).
- CNC milling: closed contours, arcs preferred to splines, tool offsets left to CAM.
- Check before sending (tested; needs mm or in units on the SVG): `uv run --no-project --with svgelements python check_fab.py part.svg '#ff0000' 600 400`
```python
"""usage: check_fab.py file.svg [cut_hex=#ff0000] [material_w_mm material_h_mm]"""
import sys
from collections import Counter
import svgelements as se

f, cut = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "#ff0000").lower()
svg = se.SVG.parse(f, ppi=25.4)                       # 1 user px == 1 mm after parsing
problems, sigs, colours = [], Counter(), Counter()
lo, hi = [float("inf")] * 2, [float("-inf")] * 2
r = lambda pt: (round(pt.x, 3), round(pt.y, 3))
for el in svg.elements():
    if not isinstance(el, se.Shape) or isinstance(el, se.Text):
        continue
    stroke = str(el.stroke).lower(); colours[stroke] += 1
    p = se.Path(el); p.reify()                          # shape -> path, transforms applied
    for sub in p.as_subpaths():
        segs = [s for s in se.Path(sub).segments() if not isinstance(s, se.Move)]
        if not segs:
            continue
        closed = isinstance(segs[-1], se.Close) or r(segs[0].start) == r(segs[-1].end)
        if stroke == cut and not closed:
            problems.append(f"open cut path starting at {r(segs[0].start)} mm")
        sigs[frozenset((r(s.start), r(s.end)) for s in segs if s.start is not None)] += 1
    if (b := p.bbox()):
        lo = [min(lo[0], b[0]), min(lo[1], b[1])]; hi = [max(hi[0], b[2]), max(hi[1], b[3])]
if (d := sum(n - 1 for n in sigs.values() if n > 1)):
    problems.append(f"{d} duplicate subpath(s): double cuts/burns")
if len(sys.argv) == 5 and (min(lo) < 0 or hi[0] > float(sys.argv[3]) or hi[1] > float(sys.argv[4])):
    problems.append("geometry outside the material")
print(f"stroke colours {dict(colours)}; bbox mm {lo[0]:.2f},{lo[1]:.2f} .. {hi[0]:.2f},{hi[1]:.2f}")
print("\n".join(problems) or "OK"); sys.exit(1 if problems else 0)
```
The duplicate test compares segment endpoints, so treat a hit as "inspect", not proof.

## 8. Export formats

| Target | Format | How | Watch |
|---|---|---|---|
| Web and UI | SVG | Illustrator Export As SVG (Styling: Presentation Attributes or Internal CSS; Font: Convert to Outlines for logos; Images: Embed or Link; Object IDs: Layer Names; Decimal 2–3; Responsive off for fixed sizes), then svgo (§4) | a11y attributes, unique IDs per page |
| Print | PDF, PDF/X | Illustrator Save As Adobe PDF with the printer's preset; CLI `rsvg-convert -f pdf -o out.pdf in.svg` or `inkscape in.svg --export-type=pdf --export-text-to-path --export-filename=out.pdf`; ReportLab when CMYK and spot colors must come from code | SVG is RGB-only and CLI PDFs are RGB: pure black becomes four-color black on conversion. Finish color in Illustrator or generate CMYK directly; see `print-production` |
| Sign RIPs, stock libraries, legacy | EPS | Illustrator Save As EPS; `inkscape --export-type=eps`; `potrace -e` | no transparency (flattened), single page |
| CAD / CAM | DXF | Illustrator File › Export › AutoCAD Interchange File (version, units, scale); Inkscape `--export-extension=org.ekips.output.dxf_outlines` (R14 dialog; tested: header AC1014, which ezdxf loads as AC1015, `$INSUNITS` 4 = mm, curves as SPLINE, Inkscape layers → DXF layers) or `org.inkscape.output.dxf_twelve`; `potrace -b dxf`; ezdxf | units and scale on import; flatten Béziers if the consumer cannot read SPLINE; layer names |

ezdxf from code (tested; `uv run --no-project --with ezdxf python gen_dxf.py`):
```python
import ezdxf
from ezdxf import units
doc = ezdxf.new("R2010", setup=True); doc.units = units.MM
doc.layers.add("CUT", color=1)                                # ACI 1 = red
msp = doc.modelspace()
msp.add_lwpolyline([(0, 0), (50, 0), (50, 30), (0, 30)], close=True, dxfattribs={"layer": "CUT"})
msp.add_circle((25, 15), radius=5, dxfattribs={"layer": "CUT"})
doc.saveas("part.dxf")
```

## 9. QA checklist
- [ ] Physical size right in the target application (no 75%/133% error); viewBox present; units as intended
- [ ] No open paths where closed are required (`PathItem.closed` or `check_fab.py`), no stray points (Illustrator Select › Object › Stray Points; Object › Path › Clean Up), no duplicate or overlapping paths, no self-intersections on cut lines
- [ ] Anchors economical; extrema placed; curves smooth at 400% zoom
- [ ] Layers and IDs named; no empty groups; no hidden objects or layers left in fabrication files; clipping masks released where the consumer ignores clipping (Select › Object › Clipping Masks)
- [ ] Strokes expanded and effects expanded where the target needs geometry; strokes centered or expanded for SVG
- [ ] Fonts outlined or embedded as the target requires; font licenses checked
- [ ] Color: RGB hex for web and machines (exact operation colors), CMYK/spot via PDF for print; swatches named
- [ ] Images embedded or linked as agreed, resolution adequate
- [ ] Renders the same in two engines (Illustrator or Inkscape vs `rsvg-convert`)

## Verify
```sh
xmllint --noout out.svg                                             # well-formed XML
rsvg-convert -f pdf -o out.pdf out.svg && pdfinfo out.pdf | grep -a "Page size"   # 210 mm = 595.28 pt
inkscape out.svg --query-all | head                                 # id,x,y,w,h in px at 96/in
rsvg-convert -d 150 -p 150 -o out.png out.svg                       # then Read the PNG
```
Plus `check_fab.py` for fabrication files, a DXF re-read with ezdxf (`doc.header["$INSUNITS"]`, entity types and layers) for CAD, and an overlay against the source for traces.

## Deliverables
- Master (editable .ai or clean source SVG with live text) plus exports per target (§8), named `<name>_<target>_v<NN>.<ext>`.
- Report: sizes and units, layer/operation map (color → operation), fonts (outlined or embedded, license), tools and versions used, check results (commands and outputs), and known limitations (e.g., splines in DXF, approximated brand colors).
