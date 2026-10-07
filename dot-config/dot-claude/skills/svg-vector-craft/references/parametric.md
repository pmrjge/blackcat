# svg-vector-craft — parametric (reference)
Read when generating SVG from code or parameters. Parent: `svg-vector-craft` SKILL.md.

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
