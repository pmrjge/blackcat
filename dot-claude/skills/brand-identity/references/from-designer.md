# designer procedure (moved from its prompt)

1. Spec: purpose, audience, medium, sizes, bleed, color mode, brand constraints, deliverables. Vector or raster undecided by the brief and the use → the designer's ASK USER gate (in its prompt) before any paid call.
2. Concept: 2–3 distinct directions in words (idea, grid, type, palette, imagery); choose one unless the user must decide.
3. Build with the most precise tool:
   - Generated art (load `image-prompting` first): `generate_svg` for logos, icons, illustrations and graphics (always SVG); `generate_image` for photos and raster imagery; `edit_image` for retouching, composites, mockups. Models are the user's choice in stack.env — never change it.
   - Vector: Illustrator MCP; without it, clean SVG previewed with `rsvg-convert` or `magick`.
   - Color: huetension for palettes, WCAG/APCA contrast, color-blindness checks, CSS/Tailwind exports and ASE/ACO swatches (`__HUETENSION__ … -f ase|aco -o <file>`). Give hex + RGB, and CMYK for print.
   - Other Creative Cloud apps: scripted first (`adobe-creative-cloud`), computer use for GUI-only steps; raster conversion → ImageMagick/libvips (`raster-imaging`).
4. QA: render every deliverable and Read it; hierarchy, alignment, spacing, text contrast ≥ WCAG AA, spelling, bleed, export settings.
5. Deliver: file paths (sources + exports), specs (sizes, color values, fonts), a rationale of at most 5 lines.
