# typography — web fonts (reference)
Read when loading and subsetting fonts for the web. Parent: `typography` SKILL.md.

## 9. Web fonts
1. WOFF2, self-hosted (no visitor data sent to a third party; you control subsets and caching).
2. Subset per script and keep the features you use. By default `pyftsubset` keeps only shaping features (for
   Latin `calt ccmp clig curs dnom frac kern liga locl mark mkmk numr rclt rlig rvrn`): `tnum`, `onum`, `smcp`,
   `case`, `ss01` vanish unless added.
```bash
uv run --with fonttools --with brotli pyftsubset Font.ttf --flavor=woff2 --output-file=font-latin.woff2 \
  --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD" \
  --layout-features+=tnum,lnum,onum,smcp,c2sc,case,zero,ss01
```
   That range is Google Fonts' current `latin` subset (covers Portuguese); repeat it in `unicode-range`.
3. `font-display: swap` when the brand face must appear; `optional` when layout stability matters more.
   Preload only the one or two files used above the fold:
   `<link rel="preload" href="/fonts/font-latin.woff2" as="font" type="font/woff2" crossorigin>`
   (`crossorigin` is required even for same-origin fonts).
4. Less layout shift: a metric-matched fallback, e.g.
   `@font-face { font-family: "Brand Fallback"; src: local("Arial"); size-adjust: 97%; }` (tune the value).
   `size-adjust` is Baseline since 2023; `ascent-override`/`descent-override`/`line-gap-override` don't
   work in Safari.
5. Licensing: web use needs a web license (§11). OFL: subsetting or reformatting is a modification (OFL FAQ
   2.6; plain WOFF wrapping of unchanged data is the exception, 2.2.1), so a font with a Reserved Font Name
   must be renamed in the subset unless its authors allow otherwise.
