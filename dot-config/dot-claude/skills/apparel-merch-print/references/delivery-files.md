# Apparel and merchandise print: delivery files

Read when preparing the delivery files for a print method (moved from `apparel-merch-print` SKILL.md).

## 14. Delivery files per method

| Method | Format | Color | Resolution / size | Also include |
|---|---|---|---|---|
| Screen | vector AI/PDF/EPS/SVG, or layered PSD/TIFF with spot channels | spot per ink, Pantone references | 1:1; raster 300 ppi | separations (underbase and highlight as separate), outlined fonts, placement spec |
| DTG | PNG with alpha | sRGB | 1:1, 150–300 ppi | garment colors; no semi-transparency |
| DTF | PNG with alpha | RGB | 1:1, 300 ppi | minimum feature check |
| Sublimation | per vendor template (PNG/TIFF/PDF) | RGB or vendor profile | panels at 1:1 | bleed per template, per-size files |
| HTV | SVG/PDF/AI vector | vinyl color names | 1:1 | one layer per vinyl color, unmirrored |
| Embroidery | vector PDF/SVG/AI or 300 ppi PNG to the digitizer | thread chart codes | exact finished size | stitch estimate, sew-out approval; keep EMB + DST |

Name files `<design>_<placement>_<method>_<size-range>_v<NN>.<ext>`.
