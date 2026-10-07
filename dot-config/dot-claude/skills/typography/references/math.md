# typography — math (reference)
Read when setting mathematics. Parent: `typography` SKILL.md.

## 10. Math typography
- Use a font with an OpenType MATH table plus its text companion: STIX Two Math + STIX Two Text (OFL);
  Libertinus Math + Libertinus Serif (OFL); Latin Modern Math and TeX Gyre Bonum/Pagella/Schola/Termes Math
  (GUST Font License, legally equivalent to LPPL 1.3c) with the matching TeX Gyre text fonts. Others: Fira
  Math, XITS Math, Garamond Math, Asana Math, DejaVu Math TeX Gyre (check each license); Cambria Math ships
  with Windows/Office (proprietary).
- LaTeX: LuaLaTeX or XeLaTeX with `unicode-math`: `\setmainfont{STIX Two Text}`,
  `\setmathfont{STIX Two Math}`. Web: MathML Core with `math { font-family: "STIX Two Math", math; }`
  (`math` is a CSS generic family). Illustrator has no math layout: typeset in LaTeX or MathJax, export PDF/SVG, place as vector,
  keep the source. LaTeX engines, packages and builds: `latex-typesetting`.
- Conventions: italic variables; upright multi-letter functions (sin, log, exp: `\sin`,
  `\operatorname{…}`), units and, per ISO 80000-2, e, i, π and the differential d (US practice often
  italicizes these: choose one and be consistent); bold (ISO: bold italic) vectors and matrices; real −, ×,
  ≤, ≥, ≠; spacing from the math engine, not typed spaces. SI: a space between number and unit (5 mm,
  25 °C, and before %), none before plane-angle degrees (30°); many English house styles close up %.
- Never mix italic letters from the text face with symbols from a different math font.
