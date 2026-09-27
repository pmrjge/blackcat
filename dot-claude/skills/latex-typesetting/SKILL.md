---
name: latex-typesetting
description: Load before writing, fixing or building LaTeX — papers, theses, lecture notes, beamer slides, arXiv submissions — or when choosing Typst instead. Covers pdfLaTeX vs XeLaTeX vs LuaLaTeX, latexmk and Tectonic, classes, amsmath/mathtools/thmtools/cleveref, siunitx, biblatex vs BibTeX, fonts and unicode-math, floats, booktabs, algorithms, listings vs minted, log errors, reproducible builds, Pandoc limits.
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
  `brew install --cask mactex-no-gui`), Tectonic 0.17, Typst 0.15.x, Pandoc 3.11. On Linux prefer upstream
  `install-tl` over distro TeX packages (often a year or more behind); update with `tlmgr update --self --all`.

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

## 2. Build
- **latexmk** runs the engine, biber/BibTeX and makeindex as often as needed:
  `latexmk -lualatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex`
  (`-pdf` = pdfLaTeX, `-xelatex`; `-pvc` continuous preview; `-outdir=build`; `-c` removes auxiliary files,
  `-C` also the PDF). Engine options such as `-file-line-error` and `-shell-escape` are passed through to the
  engine (`latexmk -showextraoptions` lists them). Project `.latexmkrc`:
```perl
$pdf_mode = 4;                     # 1 pdflatex, 4 lualatex, 5 xelatex
$out_dir  = 'build';
set_tex_cmds('-interaction=nonstopmode -halt-on-error -file-line-error %O %S');
```
- **Tectonic** (XeTeX-based, self-contained, downloads packages from a bundle on first use, reruns TeX/BibTeX
  automatically): `tectonic -X compile main.tex`; project mode `tectonic -X new` / `tectonic -X build` with a
  `Tectonic.toml`. Shell escape only with `-Z shell-escape`; pass `--untrusted` for untrusted input; `--keep-logs`
  to keep the log. biblatex needs an external `biber` whose version matches the bundle's biblatex — mismatches
  are a known failure. No LuaLaTeX. Good for CI and quick builds; use TeX Live for anything unusual.

## 3. Classes
| Class | Use |
|---|---|
| `article` | short papers and notes |
| `amsart` / `amsbook` | AMS-style mathematics; `\address`, `\email`, `\subjclass[2020]{…}`, `\keywords` |
| KOMA-Script `scrartcl` / `scrreprt` / `scrbook` | European typography; `typearea` layout: `paper=6in:9in` (width:height in portrait), `BCOR=` (binding correction), `DIV=calc`, `\areaset{w}{h}` |
| `memoir` | books with full layout control (`\setstocksize`, `\settrimmedsize`, `\setlrmarginsandblock`, `\setulmarginsandblock`, `\checkandfixthelayout`); many packages built in |
| `beamer` | slides; `\begin{frame}{Title}`, overlays `\pause`, `\only<2>{…}`; use `[fragile]` frames for verbatim/code |
| publisher/journal class | use unchanged; never override its layout, fonts or bibliography style |

## 4. Mathematics
- `amsmath` (align, gather, multline, split, cases, `\DeclareMathOperator`, `\text`); `mathtools` loads and
  fixes amsmath (`\coloneqq`, `\DeclarePairedDelimiter\abs{\lvert}{\rvert}`, `dcases`, `\shortintertext`);
  `amssymb` for the AMS symbol fonts — but not together with unicode-math (§7).
- Never `$$…$$` (plain TeX; wrong spacing) — use `\[…\]` or `equation*`; `align` not `eqnarray`;
  `\operatorname`/`\DeclareMathOperator` for `\operatorname{rank}`, `\Tr`; `\mid` in set-builder;
  `\langle…\rangle`, not `<…>`; `\colon` for maps `f\colon X\to Y`.
- **Theorems** (amsthm + thmtools):
```latex
\usepackage{amsthm,thmtools}
\declaretheorem[name=Theorem, numberwithin=section]{theorem}
\declaretheorem[name=Lemma, sibling=theorem]{lemma}          % shares the theorem counter
\declaretheorem[name=Definition, style=definition, sibling=theorem]{definition}
\declaretheorem[name=Remark, style=remark, numbered=no]{remark}
```
  One shared counter for all numbered statements makes "Lemma 3.4" easy to find; `\begin{proof}…\end{proof}`
  with `\qedhere` when a proof ends in a display.
- **siunitx v3** (3.6): `\num{12345.678}`, `\unit{\kilo\gram\per\metre\cubed}`, `\qty{9.81}{\metre\per\second\squared}`,
  `\qtyrange`, `\numlist`, table column `S[table-format=2.3]`. The v2 names `\SI`, `\si`, `\SIrange` still work but
  are not recommended. Portuguese/European output: `\sisetup{output-decimal-marker={,}}`.
- **physics** (v1.3, old) is convenient but clashes: it defines `\qty` — if loaded before siunitx, siunitx's `\qty`
  is not defined (fix per the siunitx manual: `\AtBeginDocument{\RenewCommandCopy\qty\SI}` and use `\quantity` for
  physics' version); it also redefines `\div`, `\Re`, `\Im`. Prefer your own `\DeclarePairedDelimiter` macros or
  the modular `physics2`.
- Diagrams: `tikz`, `tikz-cd` (commutative diagrams), `pgfplots` (`\pgfplotsset{compat=1.18}`) — syntax in
  `diagrams-as-code`.

## 5. Cross-references and links
- `\label` immediately after `\caption`, or inside the numbered environment; key prefixes `sec:`, `thm:`,
  `lem:`, `eq:`, `fig:`, `tab:`, `alg:`.
- Load order: other packages → `hyperref` → `cleveref` last: `\usepackage[capitalise,noabbrev]{cleveref}`;
  `\cref{thm:main}`, `\Cref` at sentence start, `\crefrange`; `\eqref` if not using cleveref. cleveref (0.21.4,
  2018) is unmaintained; the LaTeX kernel ships "first aid" patches that keep it working — keep TeX Live current.
  On arXiv's TL 2025 every `\cref` to a theorem-like environment prints the same name (arXiv: switch to
  zref-clever, select TL 2023, or add a `\crefalias` per theorem environment). Maintained alternative: `zref-clever`.
- `\hypersetup{colorlinks=true, linkcolor=…, citecolor=…, urlcolor=…}`; long URLs: `xurl`.
- "Reference … undefined" / "Label(s) may have changed" → rerun (latexmk does it); persistent ones are typos.

## 6. Bibliographies
| | biblatex + biber | natbib + BibTeX |
|---|---|---|
| Unicode names/titles | yes | limited (8-bit) |
| Styles | `numeric`, `alphabetic`, `authoryear`, `authortitle`, contributed (biblatex-ieee, biblatex-apa, …) | `.bst`: plainnat, abbrvnat, amsplain, amsalpha, venue `.bst` |
| Use when | own papers, theses, books | venue requires BibTeX/.bst; simplest for arXiv |
```latex
\usepackage[backend=biber, style=alphabetic, maxbibnames=99, giveninits=true,
            doi=true, url=false, eprint=true, isbn=false]{biblatex}
\addbibresource{refs.bib}   % extension required
...
\printbibliography
```
- `doi` field holds the bare DOI (`10.1145/1273445.1273458`), never the resolver URL. arXiv preprints in biblatex:
  `eprint = {2106.09685}, eprinttype = {arxiv}, eprintclass = {cs.LG}`. arXiv's own BibTeX export uses `eprint`,
  `archivePrefix = {arXiv}`, `primaryClass`; whether a given `.bst` prints these varies — check the output (or put
  the arXiv ID in `note`).
- **arXiv:** runs BibTeX or biber itself when it detects them, or uses an uploaded `.bbl`. An uploaded biblatex
  `.bbl` must come from the same biblatex/biber as arXiv's TeX Live (TL 2025 default: biblatex 3.20, biber 2.20,
  bbl format 3.3; TL 2023 selectable). An up-to-date TeX Live 2026 has newer versions (CTAN: biblatex 3.22a,
  biber 2.22), so either let arXiv run biber or produce the `.bbl` in a TL 2025 container. Test the exact tarball.
- Entry verification and key/field hygiene: `literature-review`. Unused/undefined citations: `checkcites main.aux`
  (BibTeX) or `checkcites --backend biber main.bcf` (biblatex + biber).

## 7. Fonts
LuaLaTeX/XeLaTeX:
```latex
\usepackage{amsmath,mathtools}   % before unicode-math
\usepackage{fontspec}
\usepackage{unicode-math}        % load after all other maths/font packages
\setmainfont{STIX Two Text}
\setmathfont{STIX Two Math}
```
| Family (TeX Live) | pdfLaTeX | LuaLaTeX / XeLaTeX |
|---|---|---|
| Latin Modern | `lmodern` | default; `Latin Modern Math` |
| STIX Two | `\usepackage{stix2}` (stix2-type1) | `STIX Two Text` / `STIX Two Math` (stix2-otf) |
| Libertinus | `\usepackage{libertinus}` (wrapper picks type1 or otf) | same wrapper, or `Libertinus Serif` / `Libertinus Math` |
| New Computer Modern | — | `\usepackage{newcomputermodern}` (Book weight; `[regular]` for Regular) |
| Times-like | `newtxtext` + `newtxmath` | `TeX Gyre Termes` + `TeX Gyre Termes Math` |
- With unicode-math, TFM maths fonts are gone: drop `amssymb` and `bm`; bold symbols with `\symbf`, sets with
  `\symbb` (or `\mathbb`).
- LuaLaTeX/XeLaTeX report a missing glyph only as a log warning "Missing character: There is no … in font …" —
  grep the log for it; the PDF silently omits the character.
- Check the result with `pdffonts main.pdf`: every font `emb yes`, no `Type 3` (matplotlib PDFs embed Type 3 by
  default — set `rcParams["pdf.fonttype"] = 42`). Commercial fonts: the licence must allow PDF embedding.

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

## 9. Algorithms
- `algorithm2e`: `\usepackage[ruled,vlined,linesnumbered]{algorithm2e}`; `\KwIn{…}`, `\KwOut{…}`, `\For{…}{…}`,
  `\If{…}{…}`, `\Return`. Single package, many options.
- algorithmicx family: `\usepackage{algorithm}` (float) + `\usepackage{algpseudocode}`; `\State`, `\For{…}…\EndFor`,
  `\If{…}…\EndIf`, `\Function{Name}{args}…\EndFunction`, `\Return`; `algpseudocodex` (1.2) extends it.
- Never load algorithm2e together with algorithm/algpseudocode (both define an `algorithm` environment).
- State inputs, outputs, invariants and complexity in the text, not only in the pseudocode.

## 10. Code listings
| | `listings` | `minted` 3.x | `piton` |
|---|---|---|---|
| Highlighting | TeX-native, keyword based | Pygments via the bundled `latexminted` (Python ≥ 3.8 on PATH) | LPeg lexers, LuaLaTeX only |
| Shell escape | no | not needed on TeX Live 2024+ (latexminted is a trusted restricted-shell program); older TL and MiKTeX need `-shell-escape` | no |
| Watch out | non-ASCII under pdfLaTeX needs `literate=` mappings | cache in `_minted/`; `frozencache=true` compiles without Python from an existing cache | engine lock-in |
- For arXiv prefer `listings` (arXiv warns that minted-based sources can fail after announcement), or build
  `_minted/` with arXiv's TeX Live year (TL 2025, minted 3; arXiv says `frozencache` is not needed), upload it,
  and test the tarball in a clean build.
- `-shell-escape` runs arbitrary commands from the document: never on untrusted sources.

## 11. Reading the log
Compile with `-file-line-error`; fix the **first** error only, then rebuild; `l.<n>` is the input line reached.
`texfot` (TeX Live) filters routine noise: `texfot lualatex -interaction=nonstopmode main.tex`.
| Message | Usual cause | Fix |
|---|---|---|
| `Undefined control sequence` | typo, package not loaded | correct the name; load the package |
| `Missing $ inserted` | `_`, `^` or a math command in text | wrap in `$…$`; escape `\_` |
| ``File `x.sty' not found`` | package not installed | `tlmgr install x` or the full scheme |
| `Option clash for package x` | loaded twice with different options | load once; `\PassOptionsToPackage{…}{x}` before `\documentclass` |
| `Command \x already defined` | two packages define the same macro | change load order; `\RenewCommandCopy`; drop one package |
| `Runaway argument?` / `Paragraph ended before … complete` | unbalanced braces | balance `{}` |
| `Misplaced alignment tab character &` / `Extra alignment tab` | `&` outside a table / too many columns | escape `\&`; count columns |
| `\begin{x} … ended by \end{y}` | mismatched environments | fix nesting |
| `Too many unprocessed floats` | float queue overflow | see §8 |
| `Overfull \hbox (… pt too wide)` | unbreakable line | rewrite, `xurl`, `\allowbreak`, microtype; anything > 1 pt shows in print |
| `Underfull \hbox (badness 10000)` | `\\` used to end paragraphs | blank line instead of `\\` |
| `Citation … undefined` | key typo, biber not run, `.bib` path | check `.blg`; `\addbibresource{refs.bib}` with extension |
| `Package inputenc Error: Unicode character …` | character not in the pdfLaTeX font encoding | `\newunicodechar` or switch to LuaLaTeX |
| `Missing character: There is no …` | glyph absent from font (Lua/XeLaTeX) | another font or `\newfontfamily` fallback |
| biber `data source not found` / version error | wrong path; biber ≠ biblatex version | fix path; matching versions |
| `Dimension too large` (pgfplots) | coordinates out of TeX's range | rescale data; `compat=1.18` |
| `TeX capacity exceeded` | runaway recursion or huge TikZ | fix the macro; externalize figures |
Lint and tidy: `chktex -q main.tex`, `lacheck main.tex`, `latexindent -w main.tex`.

## 12. Reproducible builds
- Record `lualatex --version` (or `pdflatex`), `biber --version`, `latexmk -v` and the TeX Live year with the PDF.
- Containers: `texlive/texlive:latest` (rebuilt weekly) or `texlive/texlive:TL2025-historic` (frozen TL year;
  the OS layer is refreshed monthly) — pin the image digest (`@sha256:…`) for byte-identical builds.
- Deterministic PDFs: set `SOURCE_DATE_EPOCH`. pdfTeX then fixes the PDF dates (`FORCE_SOURCE_DATE=1` also
  freezes `\year`, `\month`, `\day`, `\time`, hence `\today`); `\pdftrailerid{}` omits the /ID and
  `\pdfsuppressptexinfo=-1` drops the `PTEX.*` keys, which contain file names. LuaTeX derives its dates, random
  seed and PDF /ID from `SOURCE_DATE_EPOCH` directly.
- Vendor custom `.cls`, `.sty` and `.bst` files in the repository; commit `.latexmkrc`; CI builds in the same
  container; compare page renders (`pdftoppm -r 100 -png`) between builds to catch layout drift.
- TeX Live cannot pin single packages; freeze whole years (historic images or a frozen TL repository).

## 13. Conversion (Pandoc and others)
- Pandoc reads standard LaTeX structure, math, simple `\newcommand` macros (expanded by the `latex_macros`
  extension) and citations (`--citeproc --bibliography=refs.bib`); it drops TikZ, custom environment formatting,
  most package semantics and complex tables. `pandoc main.tex -s --citeproc --bibliography=refs.bib -o main.docx`
  turns math into native Word equations; always review the output.
- Markdown → LaTeX/PDF: `pandoc in.md --pdf-engine=lualatex -o out.pdf` or `-t latex --template=…` for control.
- LaTeX → HTML: LaTeXML (what arXiv uses for its HTML papers) or `make4ht`.

## 14. Typst as an alternative (0.15.x)
Strengths: millisecond incremental compiles, one coherent markup + scripting language, readable errors, built-in
bibliographies (`.bib` or Hayagriva YAML, CSL styles), tagged/accessible PDF by default since 0.14, PDF/A-1b…4f
and PDF/UA-1 via `--pdf-standard a-2a,ua-1`, packages from Typst Universe (`#import "@preview/<pkg>:<version>"`),
Pandoc reads and writes Typst (`--pdf-engine=typst`).
Limits: arXiv and most journals require LaTeX sources; no PDF/X export; HTML export still behind a feature flag;
0.x releases break things (0.15 dropped backslashes in paths) — pin the version per project.
| LaTeX | Typst |
|---|---|
| `$x^2$`; display `\[ x^2 \]` | `$x^2$`; display `$ x^2 $` (spaces inside the dollars) |
| `\frac{a}{b}` | `a/b` or `frac(a, b)` |
| `\alpha`, `\mathbb{R}`, `\to`, `\cdot` | `alpha`, `RR`, `->`, `dot` |
| `\sum_{i=1}^{n}` | `sum_(i=1)^n` |
| `ab` (product of a and b) | `a b` — `ab` is looked up as a variable/function |
| `\text{if }`, `\mathrm{d}x` | `"if "`, `dif x` |
| `\begin{pmatrix}1&2\\3&4\end{pmatrix}` | `mat(1, 2; 3, 4)` |
| `\label{eq:e}` … `\eqref{eq:e}` | `$ … $ <eq-e>` … `@eq-e` with `#set math.equation(numbering: "(1)")` |
Choose Typst for internal reports, notes, CVs and books with no LaTeX submission requirement where iteration
speed matters; LaTeX for journals, arXiv, AMS classes, heavy TikZ and established templates.

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
