---
name: tex-math-bib
description: Load for LaTeX maths and references — amsmath, theorems, siunitx, cleveref, biblatex, fonts.
---
# LaTeX mathematics, references, bibliographies and fonts

Part of `latex-typesetting` (engine choice, classes, floats, final checklist). Section numbers (§4–§9) are kept from the original skill.

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

## 9. Algorithms
- `algorithm2e`: `\usepackage[ruled,vlined,linesnumbered]{algorithm2e}`; `\KwIn{…}`, `\KwOut{…}`, `\For{…}{…}`,
  `\If{…}{…}`, `\Return`. Single package, many options.
- algorithmicx family: `\usepackage{algorithm}` (float) + `\usepackage{algpseudocode}`; `\State`, `\For{…}…\EndFor`,
  `\If{…}…\EndIf`, `\Function{Name}{args}…\EndFunction`, `\Return`; `algpseudocodex` (1.2) extends it.
- Never load algorithm2e together with algorithm/algpseudocode (both define an `algorithm` environment).
- State inputs, outputs, invariants and complexity in the text, not only in the pseudocode.

## Verify
- Log free of undefined references and citations and of `Missing character`; `checkcites` clean; `pdffonts` shows every font embedded, none Type 3.
- Every `\label` referenced; theorem numbering consistent; `\cref` names correct in the output.
