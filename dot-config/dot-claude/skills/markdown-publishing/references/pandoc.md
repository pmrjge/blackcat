# Pandoc

Part of `markdown-publishing`.

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
