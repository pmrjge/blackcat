# svg-vector-craft — cutting plotting (reference)
Read when preparing SVG for laser cutting, engraving, vinyl cutting or pen plotting. Parent: `svg-vector-craft` SKILL.md.

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
