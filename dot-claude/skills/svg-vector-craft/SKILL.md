---
name: svg-vector-craft
description: Load before creating or delivering vector files — SVG as code, svgo, tracing, plotters, cutters.
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
Artboards, global and spot swatches, graphic styles, raster-effect settings, master vs delivery files, ExtendScript and the Illustrator MCP server: `references/illustrator.md`.

## 6. Raster to vector
Logos and wordmarks are rebuilt by hand over a trace; line art goes through potrace, colour art through vtracer or Image Trace, then cleanup. Verified commands and flags: `references/raster-to-vector.md`.

## 8. Export formats
SVG for web/UI, PDF or PDF/X for print, EPS for sign RIPs and legacy, DXF for CAD/CAM (tested ezdxf example), with what to watch per format: `references/export-formats.md`.

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

## References
- `references/parametric.md` — read when generating SVG from code or parameters.
- `references/cutting-plotting.md` — read when preparing SVG for laser cutting, engraving, vinyl cutting or pen plotting.

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
