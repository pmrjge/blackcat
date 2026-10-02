# Perceptual palettes, contrast, dark mode

Part of `color-management`.

## 7. Perceptual palettes (OKLCH)
- OKLCH lightness tracks perceived lightness far better than HSL, and hue stays put along a ramp. CSS
  `oklch()` works in current browsers.
- Ramp: fix the hue, step L (0.97 → 0.29 for a 50–900 scale), let chroma peak mid-ramp, gamut-map every
  step to sRGB (and P3 if used), then check contrast pairs. Maximum sRGB chroma sits at a different L per hue
  (yellow near L 0.96, blue and purple near 0.5): shape the chroma curve per hue.
```python
# uv run --with coloraide python ramp.py
from coloraide import Color
L = [0.97, 0.93, 0.86, 0.77, 0.67, 0.57, 0.47, 0.38, 0.29]
C = [0.02, 0.04, 0.08, 0.12, 0.15, 0.15, 0.13, 0.10, 0.07]
ramp = [Color("oklch", [l, c, 260]).convert("srgb").fit().to_string(hex=True) for l, c in zip(L, C)]
print(ramp, Color(ramp[-1]).contrast(ramp[0], method="wcag21"))   # fit(): default method raytrace
```
- Contrast by lightness: in CIE L* (= HCT tone) a gap ≥ 38.4 guarantees 3:1, ≥ 50.2 guarantees 4.5:1,
  ≥ 62.2 guarantees 7:1 (derived from the WCAG formula). OKLCH L is a different scale: compute contrast.
- huetension `gradient.generate` (OKLCH/OKLab interpolation), `harmony.generate`, `palette.random` with a
  seed for exploration; `export.css`/`export.tailwind` for tokens.

## 8. Contrast (WCAG 2.2)
- Relative luminance: linearize each sRGB channel (c ≤ 0.04045 ? c/12.92 : ((c+0.055)/1.055)^2.4),
  L = 0.2126 R + 0.7152 G + 0.0722 B; ratio = (L1 + 0.05)/(L2 + 0.05). WCAG 2.1 and 2.2 share it (the old
  0.03928 threshold made no practical difference).
- AA: text 4.5:1, large text 3:1 (18 pt or 14 pt bold ≈ 24 px / 18.7 px CSS), UI components and graphical
  objects 3:1 (1.4.11). AAA: 7:1 and 4.5:1. Logotypes and incidental text are exempt.
- `#767676` on white = 4.54:1 (pass), `#777777` = 4.48:1 (fail): never round a ratio up.
- Compute with ColorAide `contrast(method="wcag21")`, huetension `contrast.check`, or Illustrator MCP
  `check_contrast` (auto-detects overlapping pairs). Text on photos: measure the worst local background,
  add a scrim if needed.
- APCA: removed from the WCAG 3 draft in 2023, not normative, WCAG 3's method is undecided. Use it only as a
  second, perceptual check (Lc 90 preferred body text, 75 minimum body, 60 other content text, 45 large
  headlines, 30 spot-readable, 15 non-text), never instead of WCAG 2.x.
- Color-vision deficiency: never encode meaning by hue alone; simulate protan/deutan/tritan/achroma with
  `blindness.simulate`.

## 9. Dark mode palettes
- Re-derive, don't invert: the same hue ramps with different role assignments (surface, on-surface,
  primary, on-primary, outline) stored as light/dark token pairs.
- Surfaces: dark gray rather than pure black (Material recommends #121212); show elevation with lighter
  surfaces; body text off-white.
- Accents: lighter, less saturated tones (Material uses its 200 tones for primaries in dark theme) so they
  don't vibrate against dark surfaces; re-check every pair, since contrast does not carry over.
- Logos, charts and illustrations need their own dark variants (reverse logo, dark chart palette).
- CSS: `@media (prefers-color-scheme: dark)` swapping custom properties; `color-scheme: light dark`.
