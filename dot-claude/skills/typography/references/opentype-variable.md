# typography — opentype variable (reference)
Read when using OpenType features, figure styles or variable-font axes. Parent: `typography` SKILL.md.

## 6. OpenType features and figures
| Feature | CSS |
|---|---|
| Kerning `kern` | `font-kerning: normal` |
| Ligatures `liga`, `dlig`; contextual `calt` | `font-variant-ligatures: common-ligatures discretionary-ligatures contextual` |
| Small caps `smcp`; caps to small caps `c2sc` | `font-variant-caps: small-caps` / `all-small-caps` |
| Tabular/proportional `tnum`/`pnum`; lining/oldstyle `lnum`/`onum` | `font-variant-numeric: tabular-nums lining-nums` |
| Fractions `frac`, ordinals `ordn`, slashed zero `zero` | `font-variant-numeric: diagonal-fractions ordinal slashed-zero` |
| Superiors `sups`, case-sensitive forms `case`, stylistic sets `ss01`–`ss20`, variants `cv01`–`cv99` | `font-feature-settings: "sups" 1, "case" 1, "ss01" 1` |
- `font-feature-settings` is all-or-nothing per declaration (a later rule replaces the whole list): prefer
  the `font-variant-*` properties and keep low-level settings in one place.
- Illustrator: Window > Type > OpenType has figure styles (Tabular Lining, Proportional Oldstyle, …),
  position, ligatures, contextual/stylistic/titling alternates, swashes, ordinals, fractions and stylistic
  sets; All Caps and Small Caps are in the Character panel menu (Small Caps is synthesized when the font has
  no `smcp`: avoid).
- Numbers in tables: tabular lining figures, right-aligned or on the decimal (decimal tab), equal
  decimals per column, true minus U+2212, units in the header, thin-space digit groups. Oldstyle figures
  belong in running text.
- What a font offers (features, Portuguese coverage, embedding bits):
```python
# uv run --with fonttools python feats.py Font.otf
import sys
from fontTools.ttLib import TTFont
f = TTFont(sys.argv[1])
print(sorted({r.FeatureTag for t in ("GSUB", "GPOS") if t in f for r in f[t].table.FeatureList.FeatureRecord}))
need = "ÁÀÂÃÇÉÊÍÓÔÕÚáàâãçéêíóôõúºª«»“”‘’–—…−€" + chr(0xA0) + chr(0x202F)   # + no-break spaces
print("missing:", [f"U+{ord(c):04X}" for c in need if ord(c) not in f.getBestCmap()] or "none")
print("fsType:", f["OS/2"].fsType)   # embedding permissions, see §11
```

## 8. Variable fonts
- Registered axes map to CSS: `wght` → `font-weight`, `wdth` → `font-stretch`, `ital`/`slnt` →
  `font-style`, `opsz` → `font-optical-sizing: auto`. Custom axes are uppercase (`GRAD`) and need
  `font-variation-settings`, which also replaces its whole list per declaration: drive axes with custom
  properties.
```css
@font-face {
  font-family: "Brand Sans";
  src: url("/fonts/brand-sans-var.woff2") format("woff2") tech(variations); /* legacy: format("woff2-variations") */
  font-weight: 100 900; font-stretch: 75% 125%; font-style: normal; font-display: swap;
}
```
- Office apps, older RIPs and some tools mishandle variable fonts: make static instances
  (`fonttools varLib.instancer Font-VF.ttf wght=700 wdth=100 -o Font-Bold.ttf`, add `--update-name-table`
  when the font has STAT data), export PDF, or outline logotypes.
