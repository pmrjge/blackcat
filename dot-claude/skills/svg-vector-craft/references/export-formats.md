# Export formats
Read from `svg-vector-craft` (core rules in its SKILL.md).

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
