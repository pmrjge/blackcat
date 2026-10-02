---
name: tex-build-debug
description: Use to build or debug LaTeX — latexmk, Tectonic, listings, log errors, Pandoc conversion.
---
# Building LaTeX, reading the log, reproducible builds, conversion

Part of `latex-typesetting` (engine choice, classes, floats, final checklist). Section numbers are kept from the original skill.

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
| `Too many unprocessed floats` | float queue overflow | see §8 in `latex-typesetting` |
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

## Verify
- Clean rebuild from scratch (`latexmk -C`, then build) with zero errors; the first error fixed before any other.
- Build log excerpt of the clean final run kept; the source archive builds in a clean container with the recorded versions.
