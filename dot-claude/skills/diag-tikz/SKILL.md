---
name: diag-tikz
description: Use for TikZ diagrams — tikz-cd, quiver, string diagrams, TikZiT, SVG/PNG conversion.
---
# TikZ: tikz-cd, quiver, string diagrams

Part of `diagrams-as-code` (tool choice, embedding, readability rules, QA). What a categorical diagram asserts: `category-theory`; LaTeX documents and builds: `latex-typesetting`.

## 6. TikZ: tikz-cd, quiver, string diagrams
```latex
\documentclass[border=2pt]{standalone}
\usepackage{amssymb,tikz-cd}              % amssymb for \lrcorner
\begin{document}
\begin{tikzcd}[column sep=large, row sep=large]
  X \arrow[drr, bend left, "f"] \arrow[ddr, bend right, "g"'] \arrow[dr, dashed, "\exists!\,u" description] & & \\
  & P \arrow[r, "p_2"] \arrow[d, "p_1"'] \arrow[dr, phantom, "\lrcorner", very near start] & B \arrow[d, "k"] \\
  & A \arrow[r, "h"'] & C
\end{tikzcd}
\qquad
\begin{tikzcd}[column sep=huge]           % 2-cell: name the arrows' midpoints, then connect them
  \mathcal{C} \arrow[r, bend left=50, "F", ""{name=U, below}] \arrow[r, bend right=50, "G"', ""{name=D}]
  & \mathcal{D} \arrow[Rightarrow, from=U, to=D, "\alpha"]
\end{tikzcd}
\end{document}
```
- Arrow vocabulary: direction letters `r l u d` combined (`drr`); `"f"` label left of travel, `"f"'` swapped,
  `description` on the arrow; `hook`, `two heads`, `tail`, `maps to`, `equal`, `dash`, `dashed`, `squiggly`
  (needs `\usetikzlibrary{decorations.pathmorphing}`), `Rightarrow`, `shift left`/`shift right` for parallel
  arrows, `bend left=40`, `crossing over` (cube faces), `phantom` for corners and `\cong` labels, `near start`,
  `shorten <=2pt, shorten >=2pt`. `\ar` abbreviates `\arrow`.
- Inside macro arguments or beamer frames: `\begin{tikzcd}[ampersand replacement=\&]` and `\&` between
  cells; otherwise "Single ampersand used with wrong catcode".
- quiver (q.uiver.app): draw, then export LaTeX: tikz-cd code addressed by `from=row-col, to=row-col` plus a
  comment URL that reopens the diagram for editing. Curved (`curve={height=…}`), shortened and 2-tail styles
  need `\usepackage{quiver}` (quiver.sty is on CTAN and in TeX Live).
- String diagrams in plain TikZ (read top to bottom here: $g\circ f : A\otimes B \to D$; state the convention):
```latex
\documentclass[tikz,border=2pt]{standalone}
\begin{document}
\begin{tikzpicture}[box/.style={draw, fill=white, minimum width=14mm, minimum height=7mm}, wire/.style={thick}]
  \node[box] (f) at (0,0) {$f$};  \node[box] (g) at (0,-1.6) {$g$};
  \draw[wire] ([xshift=-3mm]f.north) -- ++(0,0.8) node[above] {$A$};
  \draw[wire] ([xshift=3mm]f.north) -- ++(0,0.8) node[above] {$B$};
  \draw[wire] (f.south) -- node[right] {$C$} (g.north);
  \draw[wire] (g.south) -- ++(0,-0.8) node[below] {$D$};
\end{tikzpicture}
\end{document}
```
  TikZiT edits such figures graphically: `\usepackage{tikzit}`, `\input{styles.tikzstyles}`, then
  `\tikzfig{figures/fig1}` (inline) or `\ctikzfig{…}` (centered).
- Render and convert:
```sh
latexmk -lualatex cd.tex                            # standalone under LuaLaTeX needs luatex85.sty (full TeX Live/MacTeX)
tectonic -X compile cd.tex                          # XeTeX-based; fetches packages on first use
pdftocairo -svg cd.pdf cd.svg                       # glyphs as paths: renders the same everywhere (also pdf2svg)
dvisvgm --pdf --font-format=woff2 -o cd.svg cd.pdf  # selectable text with embedded WOFF2 fonts, smaller file
pdftocairo -png -r 300 -singlefile cd.pdf cd        # writes cd.png
# DVI route (no PDF step): \documentclass[dvisvgm,border=2pt]{standalone}, then
latexmk -dvi cd.tex && dvisvgm --font-format=woff2 --exact-bbox -o cd.svg cd.dvi
```
  dvisvgm's default `--font-format=svg` writes SVG fonts, which Chrome and Firefox ignore (math italic and
  calligraphic letters fall back to a plain serif); use `woff2`, or `--no-fonts` for paths.

## Pitfalls
| Symptom | Cause | Fix |
|---|---|---|
| `luatex85.sty not found` | `standalone` under LuaLaTeX on a minimal TeX | install the package or use pdflatex |
| Wrong math glyphs in a dvisvgm SVG | default SVG fonts, unsupported by browsers | `--font-format=woff2` or `--no-fonts` |
| tikz-cd 2-cell attaches to the wrong place | `name` on the label instead of an empty node | `""{name=U, below}` on the curved arrow |

## Verify
- LaTeX log without errors or overfull boxes; the SVG shows the right math glyphs in a browser (`woff2` fonts or paths).
- Arrow directions, labels and 2-cells checked against the intended diagram; the quiver URL kept as a comment for later edits.
