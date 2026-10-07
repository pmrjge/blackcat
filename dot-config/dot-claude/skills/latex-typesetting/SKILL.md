---
name: latex-typesetting
description: Use for LaTeX (papers, theses, beamer, arXiv) or Typst — engines, math, biblatex, errors.
---
# LaTeX typesetting (and when Typst fits)

## Scope
- Covers engines and builds, classes, mathematics packages, theorems and cross-references, bibliographies, fonts,
  floats and tables, algorithms, code listings, error diagnosis, reproducible builds, conversion, Typst.
- Not here: TikZ/tikz-cd/pgfplots/Mermaid/Graphviz syntax (`diagrams-as-code`); trim sizes, bleed, PDF/X and
  EPUB for books (`book-production`); prose quality (`technical-writing`); reference verification and BibTeX
  hygiene (`literature-review`); Portuguese conventions (`portuguese-pt-writing`); choosing typefaces
  (`typography`); slide design as opposed to beamer mechanics (`presentation-design`).
- Versions as of Sept 2026: TeX Live 2026 (released March 2026; MacTeX 2026 via
  `brew install --cask mactex-no-gui`), Tectonic 0.17, Typst 0.15.x, Pandoc 3.11 (now 3.12). On Linux prefer upstream
  `install-tl` over distro TeX packages (often a year or more behind); update with `tlmgr update --self --all`.
- Verified 2026-10-02 (`git ls-remote --tags`): Tectonic 0.17.0 (github.com/tectonic-typesetting/tectonic), Typst 0.15.1
  (github.com/typst/typst), Pandoc 3.12 (github.com/jgm/pandoc). TeX Live 2026, CTAN package versions and arXiv's
  TeX Live set-up: unverified since Sep 2026.

## Modules (load the one the task touches)
| Module | Load for |
|---|---|
| `tex-math-bib`* | amsmath/mathtools, theorems, siunitx, cross-references and cleveref, biblatex/BibTeX and arXiv `.bbl`, fonts and unicode-math, algorithms |
| `tex-build-debug`* | latexmk and Tectonic, code listings and shell escape, reading the log, reproducible builds, Pandoc and HTML conversion |
| `typst`* | Typst as an alternative: strengths, limits, LaTeX → Typst syntax |

`*` = not in the skill listing: Read `__CLAUDE_DIR__/skills/<name>/SKILL.md` (the Skill tool won't load it).

## 1. Choose the engine
| Situation | Engine | Reason |
|---|---|---|
| arXiv, journal/conference templates, maximum compatibility | pdfLaTeX | arXiv supports pdfLaTeX and (since Nov 2025) XeLaTeX, not LuaLaTeX; most publisher classes assume it |
| New document, OpenType/system fonts, Unicode input, unicode-math, tagged/accessible PDF | LuaLaTeX | Recommended by the LaTeX team for new documents and for PDF tagging; full microtype |
| OpenType fonts with faster compiles than LuaLaTeX; templates that require it | XeLaTeX | HarfBuzz shaping; microtype protrusion and tracking, no font expansion |
microtype (load it always): character protrusion works in pdfTeX, LuaTeX and XeTeX; font expansion only in
pdfTeX and LuaTeX; interword spacing/kerning adjustments only in pdfTeX.
pdfLaTeX preamble needs `\usepackage[T1]{fontenc}` plus a font package (UTF-8 input is the default since 2018);
Lua/XeLaTeX use `fontspec` (+ `unicode-math`) and never `fontenc`/`inputenc`.

## 3. Classes
| Class | Use |
|---|---|
| `article` | short papers and notes |
| `amsart` / `amsbook` | AMS-style mathematics; `\address`, `\email`, `\subjclass[2020]{…}`, `\keywords` |
| KOMA-Script `scrartcl` / `scrreprt` / `scrbook` | European typography; `typearea` layout: `paper=6in:9in` (width:height in portrait), `BCOR=` (binding correction), `DIV=calc`, `\areaset{w}{h}` |
| `memoir` | books with full layout control (`\setstocksize`, `\settrimmedsize`, `\setlrmarginsandblock`, `\setulmarginsandblock`, `\checkandfixthelayout`); many packages built in |
| `beamer` | slides; `\begin{frame}{Title}`, overlays `\pause`, `\only<2>{…}`; use `[fragile]` frames for verbatim/code |
| publisher/journal class | use unchanged; never override its layout, fonts or bibliography style |

## 8. Floats, figures, tables
- Vector PDF for plots and diagrams, PNG/JPEG ≥ 300 ppi at printed size for raster;
  `\includegraphics[width=\linewidth]{fig.pdf}`; `\centering` inside the float (not the `center` environment);
  sub-figures with `subcaption` (not `subfig`/`subfigure`); placement `[tbp]`; `[H]` (float package) only when
  a float must not move, e.g. in slides.
- Tables: `booktabs` (`\toprule`, `\midrule`, `\cmidrule(lr){2-3}`, `\bottomrule`), no vertical rules, units in the
  header, decimals aligned with siunitx `S` columns; `tabularx` for fixed width; `longtable`/`xltabular` across
  pages; `tabularray` (2025C) as a modern all-in-one alternative — do not mix it with booktabs rules in one table.
- Caption above tables, below figures (the usual convention); caption states the takeaway (`technical-writing`).
- "Too many unprocessed floats" → fewer consecutive floats, `[tbp]`, `\clearpage` at a section end.

## 15. Final checklist
- [ ] Clean rebuild from scratch (`latexmk -C` then build) with zero errors.
- [ ] Log reviewed: no undefined references/citations, no `Missing character`, no overfull boxes > 1 pt.
- [ ] Engine matches the venue (arXiv: pdfLaTeX/XeLaTeX; `.bbl` version if uploaded).
- [ ] `pdffonts`: all embedded, no Type 3; PDF metadata (title, author, language) set.
- [ ] Every `\label` referenced; theorem numbering consistent; `\cref` names correct.
- [ ] Bibliography entries verified; DOIs present; one style; `checkcites` clean.
- [ ] Figures vector where possible, raster ≥ 300 ppi; tables with booktabs and units.
- [ ] Language set (`\usepackage[portuguese]{babel}` or `[english]`) so hyphenation matches the text.
- [ ] Source archive builds in a clean container.

## Verify / Deliverables
- Build log excerpt showing a clean final run; `pdffonts` output; page renders spot-checked at 100–200 %.
- Hand back: the source tree (`main.tex`, `.bib`, figures, `.latexmkrc`), the PDF, the exact build command,
  TeX Live year and engine, and the list of accepted warnings with reasons; for arXiv, the tested tarball
  (plus `.bbl` if biblatex is used).

