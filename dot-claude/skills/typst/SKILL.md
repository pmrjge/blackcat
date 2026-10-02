---
name: typst
description: Use to write in or convert to Typst — when it beats LaTeX, its limits, math syntax, packages, PDF/A output.
---
# Typst

Part of `latex-typesetting` (engine choice and when LaTeX is required). Typst 0.15.1 is current (Verified 2026-10-02 `git ls-remote --tags https://github.com/typst/typst`).

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

## Verify
- `typst compile main.typ` finishes without warnings on the pinned Typst version; the PDF passes the requested `--pdf-standard`.
- The project records its Typst version and the exact `@preview` package versions it imports.
