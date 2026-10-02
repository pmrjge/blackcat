# Color management: checklists

Read when checking a deliverable before handoff (moved from `color-management` SKILL.md).

## 12. Checklists per deliverable
- **Web/UI:** sRGB, tagged; tokens as HEX (+ OKLCH source); every text/background pair meets 4.5:1 (3:1 large
  text and UI parts); dark-mode pairs checked separately; CVD simulated; P3 only as enhancement.
- **App assets:** Apple icons accept sRGB, Gray Gamma 2.2 or Display P3; Google Play store icon is sRGB;
  interface colors from the same tokens as web.
- **Print (offset/digital):** agreed profile and TAC; brand colors as explicit CMYK or spot; K-only text,
  overprinting; rich black only on large areas; no RGB or Lab objects left unless the workflow is late
  binding; spot names match the printer; images at ≥ 300 ppi effective size unless the printer says
  otherwise; soft-proofed; separations checked.
- **Apparel** (method choice and files: `apparel-merch-print`): screen print uses spot inks matched to
  Pantone (one screen per color; halftones about 35–65 LPI, the printer decides); DTG/DTF files are sRGB PNGs
  with fully transparent backgrounds and no
  semi-transparent pixels, glows or soft shadows (they trigger a visible white underbase on dark garments;
  put a bright test layer behind the art to find stray alpha); resolution per vendor (150–300 ppi at print
  size); embroidery matches thread charts, not CMYK: ask for the thread numbers; approve a physical sample.
- **Slides and video:** sRGB; check projector or TV washout on low-contrast pairs; video tagged BT.709.
