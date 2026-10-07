# Book production: manuscript → print PDF, DOCX, EPUB: fonts pdf

Read when embedding fonts or exporting the print PDF (moved from `book-production` SKILL.md).

## 6. Fonts and PDF for print
- Embed every font (`pdffonts book.pdf`: `emb yes` everywhere, no Type 3). Acrobat's "Standard" preset does not
  embed the base-14 fonts, and IngramSpark may reject such files. Commercial fonts: the licence must cover print/PDF
  embedding (and ebook embedding for EPUB, often a separate licence).
- **PDF/X:** IngramSpark requires PDF/X-1a:2001 or PDF/X-3:2002 (no crop marks, single pages, no spot colours,
  no ICC-tagged objects — 100 % K text tagged with a profile can print as grey; total ink ≤ 240 %; rule lines
  ≥ 0.125 pt at 100 % K). KDP accepts a normal PDF meeting its rules (§2).
  Routes: `\usepackage[x-1a1]{pdfx}` (PDF/X-1a:2001; `x-302` = PDF/X-3:2002; load it first after
  `\documentclass`, configure hyperref via `\hypersetup` instead of loading it; metadata in `\jobname.xmpdata`;
  X-1a allows only CMYK/grey content); Ghostscript `-dPDFX=3` with an edited `PDFX_def.ps` naming the
  output-intent profile plus `-sColorConversionStrategy=CMYK` or `Gray`; WeasyPrint `--pdf-variant` (labels X-1a/X-3 as the :2003
  versions and does not convert RGB); Acrobat Pro
  or callas pdfToolbox. `\DocumentMetadata{pdfstandard=X-4}` only writes XMP metadata — it neither converts
  colours nor validates.
- Preflight with a PDF/X-capable tool (Acrobat Pro Preflight, pdfToolbox); veraPDF validates PDF/A and PDF/UA,
  not PDF/X. `pdfinfo -box` must show TrimBox (or ArtBox) on every page for PDF/X.
