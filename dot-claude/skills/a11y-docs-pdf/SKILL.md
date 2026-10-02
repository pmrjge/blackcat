---
name: a11y-docs-pdf
description: Use for accessible PDF, Word, EPUB or LaTeX output — tagged PDF, PDF/UA, LaTeX tagging, alt text, veraPDF.
---
# Accessible documents (PDF, Office, EPUB)
Hub: `web-accessibility` (WCAG 2.2 AA target, legal frame, contrast). File mechanics: the pdf/docx skills; LaTeX builds: `latex-typesetting`; Markdown → PDF/EPUB pipelines: `markdown-publishing`; book files: `book-production`.

## What "accessible" means for a document
- **Tagged structure:** headings, paragraphs, lists, tables (with header cells), figures, links and notes are tagged in reading order; decorative content is marked as an artifact.
- **Text alternatives:** every meaningful figure has alt text (what it shows and why it matters); complex charts get a longer description or the data table (`data-visualization` `references/design-rules.md`).
- **Language** set for the document and for passages in another language; a meaningful **title** shown in the window title.
- **Real text**, not images of text; scanned pages need OCR plus tagging, not just a text layer.
- Contrast, color-only meaning and font size follow the hub (§4); links have descriptive text.
- Forms: labeled fields, tab order, tooltips.
- Standards: PDF/UA (ISO 14289; PDF/UA-1 for PDF 1.x, PDF/UA-2 for PDF 2.0 — status details unverified as of 2026-10-02) for PDF, WCAG 2.2 for content.

## Producing tagged output
- **LaTeX:** the LaTeX tagging project's `\DocumentMetadata` before `\documentclass`, e.g. `\DocumentMetadata{lang=en, pdfstandard=ua-2, pdfstandard=a-4f, tagging=on}`; LuaLaTeX is the preferred engine (it generates MathML for formulas via `luamml`); use a current LaTeX release — `tagging=on` does not exist in older ones. Check each package used against the project's compatibility list.
- **Word / Office:** built-in heading and list styles (not manual formatting), table header rows, alt text on images, the built-in Accessibility Checker, then export to PDF with "document structure tags for accessibility" enabled (option names vary by version: unverified).
- **InDesign/Acrobat:** tag and order content in the source; Acrobat's accessibility tools to fix tags and reading order after export (`adobe-creative-cloud`).
- **HTML → PDF** (browser print, WeasyPrint, Paged.js): semantic HTML gives the structure; confirm the renderer emits tags (not all do: unverified per tool).
- **EPUB:** semantic XHTML, `lang`, navigation document, alt text, accessibility metadata (EPUB Accessibility spec; checker: DAISY Ace — unverified as of 2026-10-02).

## Checking
- **veraPDF** validates PDF/UA-1 and PDF/UA-2 machine-checkable rules (CLI and GUI).
- **PAC** (PDF Accessibility Checker, axes4; Windows) and Acrobat's Full Check add structure and screen-reader previews (unverified as of 2026-10-02).
- Machine checks catch only part of the problems: always read the tag tree and reading order, and listen to the document with a screen reader (VoiceOver: open in a reader that exposes tags — results differ by viewer).

## Verify
- [ ] Validator report attached (tool and version, profile PDF/UA-1 or -2) with zero failures or each failure explained.
- [ ] Tag tree and reading order inspected on the pages with tables, figures, formulas and multi-column layout.
- [ ] Every figure has alt text or is an artifact; language and title set; links descriptive.
- [ ] Screen-reader pass on the first pages and one complex table.

## Sources
- Verified 2026-10-02 https://latex3.github.io/tagging-project/documentation/usage-instructions — `\DocumentMetadata` keys (`lang`, `pdfstandard=ua-2`, `pdfstandard=a-4f`, `tagging=on`), LuaLaTeX preferred, `luamml` MathML, `tagging=on` absent from older releases.
- Verified 2026-10-02 https://github.com/veraPDF/veraPDF-library/releases/latest — veraPDF 1.30.2 with PDF/UA-1 and PDF/UA-2 rule fixes.
- Unverified as of 2026-10-02: ISO 14289-2:2024 publication details, PAC 2024, DAISY Ace, Office export option names.
