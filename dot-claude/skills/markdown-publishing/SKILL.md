---
name: markdown-publishing
description: Load before building or fixing a Markdown publishing pipeline — GFM, KaTeX/MathJax, Mermaid, MDX, Astro sites, Pandoc to PDF/DOCX/EPUB/HTML, markdownlint and lychee.
---
# Markdown publishing

## Scope
- Markdown sources published as websites (Astro), documents (Pandoc: PDF via LaTeX or Typst, DOCX, EPUB,
  HTML) and forge-rendered docs. Book-length print output is `book-production`; LaTeX itself is
  `latex-typesetting`; diagram syntax and rendering is `diagrams-as-code`; prose is `technical-writing`.
- Checked Sep 2026 by building a test site and documents: Astro 7.3 (Node ≥ 22.12, Zod 4), Shiki 4,
  remark-math 6, rehype-katex 7 (KaTeX 0.18), rehype-mathjax 7.1 (bundles MathJax 3), rehype-mermaid 3,
  @astrojs/mdx 8, @astrojs/rss 4, @astrojs/sitemap 3.7, pandoc 3.9 (Homebrew ships 3.11), markdownlint-cli2 0.23, lychee 0.24.

## 1. Flavors
| Flavor | Adds | Use for |
|---|---|---|
| CommonMark 0.31.2 | the core spec | the portable baseline |
| GFM (spec 0.29-gfm) | tables, task lists, strikethrough, extended autolinks, disallowed raw HTML; github.com also renders footnotes, alerts (`> [!NOTE]`, `TIP`, `IMPORTANT`, `WARNING`, `CAUTION`), math and Mermaid | READMEs, forge docs; Astro renders GFM + SmartyPants by default |
| Pandoc Markdown | footnotes, citations `[@key]`, fenced divs `::: {.note}`, bracketed spans, attributes `{#id .class}`, implicit figures, raw TeX, YAML metadata (`alerts` off by default; `-f gfm`, `-f commonmark_x` also available) | documents |
| MDX | JSX components and expressions inside Markdown | component-rich pages |

Portable habits: blank lines around blocks, ATX headings, fenced code with a language, one H1 (or `title` in
frontmatter), relative links, no raw HTML that MDX would parse as JSX.

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

## 3. Astro 7 site
Read `references/astro-site.md` when creating, configuring or building an Astro site (content collections, math and diagram plugins, deployment).

## 4. Frontmatter conventions
- Site: `title`, `description` (the meta description), `pubDate`/`updatedDate` as ISO 8601 dates, `draft`,
  `tags`, `cover` + `coverAlt`, `canonical` for cross-posts, `lang` when not the site default.
- Pandoc: `title`, `author`, `date`, `lang`, `abstract`, `keywords`, `bibliography`, `csl`, `link-citations`.
- Quote strings containing `:` or `#`; one schema per collection; filter drafts everywhere pages, feeds and
  sitemaps are generated.

## 5. Footnotes and cross-references
- Footnotes `[^id]` work in GFM, Astro and Pandoc (rendered with back-links).
- Headings get ids automatically (Astro, GitHub, Pandoc); ids change when headings change, so check anchors
  with lychee `--include-fragments` after every build.
- Equations on the web: MathJax `\label{eq:x}` / `\eqref{eq:x}` with `tags: 'ams'`; KaTeX offers only `\tag{…}`.
- Documents: pandoc-crossref. `![Caption](img.png){#fig:x}`, `$$ … $$ {#eq:x}`, a table caption
  `: Caption {#tbl:x}`, `# Heading {#sec:x}`; cite as `@fig:x` or `[@fig:x]`. Run it before citeproc
  (`-F pandoc-crossref --citeproc`), and use a pandoc-crossref build made for the installed pandoc version
  (Homebrew keeps the two in step). Use `--top-level-division=chapter` for chapter-numbered documents.

## 6. Pandoc
```sh
pandoc doc.md -o doc.pdf --pdf-engine=lualatex --citeproc -N --toc -V geometry:margin=2.5cm -V mainfont="Source Serif 4" -V colorlinks=true
pandoc doc.md -o doc.pdf --pdf-engine=typst --citeproc        # needs the typst CLI; or: pandoc doc.md -s -t typst -o doc.typ && typst compile doc.typ
pandoc -o custom-reference.docx --print-default-data-file reference.docx    # restyle in Word/LibreOffice, then
pandoc doc.md -o doc.docx --reference-doc=custom-reference.docx --citeproc
pandoc doc.md -o doc.epub --toc --css=epub.css --epub-cover-image=cover.png --mathml --citeproc
pandoc doc.md -s -o doc.html --embed-resources --mathml --toc --citeproc   # one self-contained file
pandoc -d pdf.yaml                                                          # defaults file (below)
```
```yaml
# pdf.yaml
input-files: [doc.md]
output-file: doc.pdf
pdf-engine: lualatex
number-sections: true
table-of-contents: true
filters: [pandoc-crossref, citeproc]   # order matters; citeproc may be listed here
variables: { geometry: margin=2.5cm, mainfont: Source Serif 4, colorlinks: true }
```
- Version notes: 3.11 adds `--math-method=mathml|mathjax|katex|webtex|gladtex|plain` (old `--mathml`,
  `--katex` … still work) and makes MathML the default; before 3.11 unflagged HTML/EPUB math was plain text and
  complex formulas stayed as raw TeX ("Could not convert TeX math …"). 3.8 added
  `--syntax-highlighting=none|default|idiomatic|<style>` (replacing `--highlight-style`/`--no-highlight`).
  `--embed-resources` replaces `--self-contained`. Check `pandoc --version` before copying flags.
- `mainfont` needs lualatex or xelatex (fontspec) and an installed font. Lua filters (`-L filter.lua`) for
  custom callouts or shortcodes; JSON filters (pandoc-crossref) are separate executables on PATH.
- Books, print PDFs, EPUB validation (epubcheck) and print-on-demand: `book-production`.

## 7. Linting and link checking
```sh
markdownlint-cli2 "**/*.md" "#node_modules"                     # --fix applies fixable rules
lychee --offline --root-dir "$PWD/dist" --index-files index.html --include-fragments dist   # internal links + #anchors
lychee --root-dir "$PWD/dist" --index-files index.html --cache --max-cache-age 1d --no-progress dist   # adds external links
vale src/content                                                # prose rules from .vale.ini, if the project uses Vale
```
```jsonc
// .markdownlint-cli2.jsonc
{
  "config": { "default": true, "MD013": false, "MD033": false, "MD041": false },
  "globs": ["**/*.md"],
  "ignores": ["node_modules/**", "dist/**"],
  "gitignore": true
}
```
- Check the built `dist/`: root-relative links (`/blog/x/`) in Markdown sources cannot be resolved without it.
  `--root-dir` must be absolute; lychee exits 2 on broken links (CI-friendly). `.lycheeignore` lists URL regexes
  to skip (give each a reason); for rate-limited hosts accept `429` (`--accept '100..=103,200..=299,429'`).
- markdownlint misreads JSX in `.mdx`; lint `.md` sources and validate MDX by building.

## 8. Images
- Photos: AVIF with WebP fallback (Astro `<Picture>`); screenshots and UI: PNG or lossless WebP; vector: SVG
  (optimize; never inline untrusted SVG); animation: MP4/WebM instead of GIF (`media-ffmpeg`).
- Keep originals in `src/` so the pipeline makes responsive widths; always ship intrinsic width/height (no layout
  shift); lazy-load below the fold; mark the hero image `priority`.
- Alt text: describe content and purpose in context; `alt=""` for decorative images; charts and diagrams get a
  one-sentence takeaway plus a text equivalent when detail matters; never leave essential text only in pixels.
- Image and font licences: record source and licence for every asset you did not make.

## Publishing checklist
1. Build is clean: `astro build` (and `astro check`) or pandoc with no warnings; math errors grepped
   (`katex-error`, `data-mjx-error`, literal `\` commands) in `dist/`.
2. Content: every entry passes the schema; drafts absent from pages, RSS and sitemap; dates and authors right.
3. Links: lychee on `dist/`, offline with fragments, then online for external links; zero unexplained failures.
4. Lint: markdownlint clean or each exception justified; spelling and prose pass.
5. Rendering: code highlighting in light and dark mode, math, Mermaid, footnotes and tables checked in a browser
   at phone and desktop widths.
6. Metadata: unique title and description per page, canonical URL, OG image loads by absolute URL,
   `sitemap-index.xml` and RSS present and valid, `lang` set, `site`/`base` correct for the host.
7. Accessibility: one H1, ordered headings, alt text, contrast, visible focus, reduced motion respected.
8. Documents: open every PDF/DOCX/EPUB output; fonts embedded (`pdffonts doc.pdf`); cross-references resolved (no `??`).
9. Deploy to a preview first; check 404 page, trailing-slash behavior and redirects, then production.

## Verify
- Re-run the full build from a clean clone (`rm -rf dist node_modules && npm ci && npm run build`).
- Spot-check rendered HTML: `grep -rlE 'katex-error|data-mjx-error' dist` prints nothing, footnote back-links
  are present, `<img>` tags carry width, height and alt.
- Validate feeds and sitemap (XML parses; URLs absolute and live), and confirm the OG image in a link preview tool.

## Deliverables / Report
Source changes (content, config, schema), the build and deploy commands, output locations (`dist/`, PDF/DOCX/
EPUB paths), checklist results with lint and link-check counts, known exceptions with reasons, and the
preview/production URLs.
