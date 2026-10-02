# Math: KaTeX or MathJax

Part of `markdown-publishing`.

## 2. Math: KaTeX or MathJax
| | KaTeX (`rehype-katex`) | MathJax (`rehype-mathjax`) |
|---|---|---|
| Output | HTML + MathML (`output: 'htmlAndMathml'`); needs `katex/dist/katex.min.css` and its fonts | SVG by default (no CSS); `rehype-mathjax/chtml` needs `chtml.fontURL`; `rehype-mathjax/browser` defers to client MathJax |
| Coverage | a documented subset: `\label`, `\eqref`, `\ref` are unsupported (they print literally); `\tag` only in display math; no `\DeclareMathOperator` (use `\operatorname` or a macro); `\begin{CD}` for simple commutative squares | broader LaTeX; numbered equations and linked `\eqref` with `tex: {tags: 'ams'}` (tested) |
| Macros | `[rehypeKatex, {macros: {'\\R': '\\mathbb{R}'}}]` | `[rehypeMathjax, {tex: {tags: 'ams', macros: {R: '\\mathbb{R}'}}}]` |
| Errors in built HTML | parse errors: `class="katex-error" title="ParseError: …"`; unknown commands render as red text | `data-mjx-error="…"` |

KaTeX for speed and plain notation; MathJax when equations are numbered and cross-referenced or the notation
is heavy. `trust` (default `false`) keeps KaTeX from honoring `\href`/`\includegraphics` in untrusted input.
Syntax (remark-math): `$…$` inline (`singleDollarTextMath: false` if prose uses dollar signs), `$$…$$` display,
or a ```` ```math ```` fence. GitHub renders math with MathJax (`$…$`, `` $`…`$ ``, `$$…$$`, ```` ```math ````); GitLab with KaTeX.
