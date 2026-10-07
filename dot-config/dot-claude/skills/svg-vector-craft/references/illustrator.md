# Illustrator practice
Read from `svg-vector-craft` (core rules in its SKILL.md).

## 5. Illustrator practice
- One artboard per deliverable or size, named; artboard = trim for print.
- Swatches: Global process swatches for brand colors (edit once, update everywhere); Spot swatches for Pantone inks and technical plates (die, foil, varnish, white); delete unused swatches before delivery.
- Graphic Styles for repeated appearances (a cut line: 0.25 pt stroke, spot `CutContour`, overprint); Character/Paragraph Styles for type; Symbols for repeated elements.
- Effect › Document Raster Effects Settings at the output resolution; decide Scale Strokes & Effects before scaling.
- Keep a master .ai with live text and appearances; derive delivery copies (outlined text, expanded appearances); File › Package collects links and fonts.
- Scripting: ExtendScript (.jsx) via File › Scripts, or `osascript -e 'tell application "Adobe Illustrator" to do javascript "app.activeDocument.name"'`. As of mid-2026 Illustrator has no public UXP API for third-party code (CEP remains for panels); check before assuming. Script units are points (1 pt = 0.3528 mm); `PathItem.closed` finds open paths; the API cannot read the document bleed setting.
- Illustrator MCP server, when mounted: list its tools first. Typical coverage: document, artboard and layer info; creating paths and text; importing SVG as editable objects; swatches; overprint, separation and preflight info; SVG/PNG/PDF export. Confirm the coordinate system it reports (print and web documents can differ), confirm each export on disk (`ls -la`), and Read a PNG render for visual QA. Use the screen only when no scripted route exists (`computer-use-apps`).
