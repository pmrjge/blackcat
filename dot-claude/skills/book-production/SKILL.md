---
name: book-production
description: Load before turning a manuscript into a print-ready PDF, DOCX or EPUB, or uploading to KDP/IngramSpark — trim, margins, bleed, Pandoc/LaTeX/Typst, cover and spine, ISBN.
---
# Book production: manuscript → print PDF, DOCX, EPUB

## Scope
- From a finished manuscript to files printers and retailers accept: planning, interior layout, bleed, matter
  order, toolchains, fonts/PDF/X, images, cover, ISBN and legal deposit, DOCX, EPUB, proofs, release.
- Not here: LaTeX internals (`latex-typesetting`); prose and copy-editing (`technical-writing`,
  `portuguese-pt-writing`); ICC profiles and RGB→CMYK conversion (`color-management`); generic PDF/X preflight
  (`print-production`); diagrams (`diagrams-as-code`); cover artwork generation (`image-prompting`).
- Printer numbers below were checked in September 2026 against KDP help pages and IngramSpark's *File Creation
  Guide*. Specs change: re-read the current pages and use the printer's own calculator/template before export.

## 1. Plan before layout
| Decision | Guidance |
|---|---|
| Printer(s) | KDP (Amazon channels; free KDP ISBN usable only on KDP), IngramSpark (bookshops/libraries; PDF/X required), local digital/offset printer (short runs, special stock). KDP + IngramSpark together → own ISBN. |
| Trim size | US trade default 6 × 9 in. KDP paperback sizes include 5 × 8, 5.06 × 7.81, 5.25 × 8, 5.5 × 8.5, 6 × 9, 6.14 × 9.21, 6.69 × 9.61, 7 × 10, 7.44 × 9.69, 7.5 × 9.25, 8 × 10, 8.25 × 6, 8.25 × 8.25, 8.5 × 8.5, 8.5 × 11, 8.27 × 11.69 (A4). UK/European trade formats: B-format 129 × 198 mm (≈ 5.06 × 7.81), Demy 138 × 216 mm (≈ 5.5 × 8.5), Royal 156 × 234 mm (= 6.14 × 9.21), A5 148 × 210 mm — confirm each against the printer's list. |
| Page count | KDP paperback 24–828 (black ink, white paper, most sizes; less for large formats and cream/groundwood), standard colour 72–600; KDP hardcover 75–550. IngramSpark processes an even page count and prints its manufacturing information on the last page, which must be blank (it adds pages if needed). |
| Paper | Cream for fiction/long reading (thicker: wider spine), white for non-fiction, maths, images. |
| Interior ink | Black & white (grayscale images) ≪ standard colour ≪ premium colour in cost; colour only if the content needs it. |
| Formats and ISBNs | Each format (paperback, hardcover, EPUB) is a separate product with its own ISBN (§8). |

## 2. Interior layout
**KDP minimum margins** (measured from the trim edge):
| Page count | Inside (gutter) | Outside, top, bottom — no bleed | — with bleed |
|---|---|---|---|
| 24–150 | 0.375 in (9.6 mm) | ≥ 0.25 in (6.4 mm) | ≥ 0.375 in (9.6 mm) |
| 151–300 | 0.5 in (12.7 mm) | ≥ 0.25 in | ≥ 0.375 in |
| 301–500 | 0.625 in (15.9 mm) | ≥ 0.25 in | ≥ 0.375 in |
| 501–700 | 0.75 in (19.1 mm) | ≥ 0.25 in | ≥ 0.375 in |
| 701–828 | 0.875 in (22.3 mm) | ≥ 0.25 in | ≥ 0.375 in |
IngramSpark recommends ≥ 0.5 in (13 mm) on all sides for text, headers, footers and folios. These are minima, not
design targets: comfortable books use ~0.625–0.875 in outer margins and a gutter above the minimum for thick books.
- **Type:** 10–12 pt text face with real italics and small caps (e.g. Libertinus Serif, STIX Two Text, EB Garamond,
  Source Serif); leading ~120–145 % (11/14 pt); measure 45–75 characters (≈ 66 ideal); justified with hyphenation
  in the book's language, or ragged-right for technical books with much code. Choosing and pairing faces,
  OpenType features and licences: `typography`.
- **Running heads and folios:** verso = book or part title, recto = chapter title; none on chapter openers,
  part pages or blank pages; folios in the outer corner or centred in the foot. Front matter in lowercase roman
  (i, ii, …); main matter restarts at arabic 1 on a recto; blank versos completely blank.
- **Chapter openings:** recto (`openright`) in formal books; `openany` saves pages in long technical books.
- **Widows/orphans:** LaTeX `\widowpenalty=10000 \clubpenalty=10000` (memoir: `\sloppybottom` helps);
  `\flushbottom` for aligned facing pages; never leave a heading at the foot of a page (`\needspace`).
- **Check facing spreads**, not single pages: a PDF viewer's two-page view with "show cover page", so odd pages sit
  on the right as in the printed book.
- **KDP interior rules:** single pages (no spreads), even page numbers on left pages, no crop/trim marks, comments,
  annotations or bookmarks, flattened transparency, embedded fonts, images ≥ 300 DPI; grey backgrounds at least
  10 % fill on black-ink interiors. For LaTeX print builds use `\usepackage[draft]{hyperref}` (keeps `\ref`/`\cref`,
  drops links and bookmarks) or `hidelinks` plus `bookmarks=false`.

memoir set-up for a 6 × 9 in, 151–300-page book without bleed:
```latex
\documentclass[11pt,twoside,openright]{memoir}
\setstocksize{9in}{6in}
\settrimmedsize{\stockheight}{\stockwidth}{*}
\setlrmarginsandblock{0.75in}{0.625in}{*}   % spine (gutter), fore-edge
\setulmarginsandblock{0.75in}{0.875in}{*}   % upper, lower
\checkandfixthelayout
```
KOMA-Script equivalent: `\documentclass[paper=6in:9in, twoside, BCOR=…, DIV=calc]{scrbook}` — then measure
the resulting inner margin against the table above. Do not combine `geometry` with memoir.

## 3. Bleed (only if something prints to the edge)
Text-only interiors: page size = trim size, no bleed. If any image or tint touches the trim edge:
- KDP: 0.125 in (3.2 mm) on top, bottom and outside — page width = trim width + 0.125 in, page height = trim
  height + 0.25 in; applies to the whole interior; outside margins ≥ 0.375 in from the trim.
- IngramSpark: 0.125 in (3 mm) on the three trim edges, never on the bind (gutter) edge.
- In a two-sided LaTeX layout the outside edge alternates, so add the bleed to outer, top and bottom margins and let
  `twoside` swap sides (6 × 9 in trim, 300 pages, KDP):
```latex
\usepackage[paperwidth=6.125in, paperheight=9.25in, twoside,
            inner=0.625in,            % gutter, no bleed on the spine side
            outer=0.75in,             % 0.625in margin + 0.125in bleed
            top=0.875in, bottom=0.875in]{geometry}   % 0.75in + 0.125in bleed each
```
  Full-bleed images extend to the paper edge (e.g. a TikZ `remember picture, overlay` node at
  `current page.north west`). Check boxes with `pdfinfo -box -f 1 -l 4 book.pdf`.

## 4. Front and back matter (conventional order, cf. *Chicago Manual of Style* ch. 1)
Front (roman folios, many pages unnumbered): half title → series page or frontispiece (verso) → title page →
copyright page (verso: © line, edition, ISBN per format, publisher/imprint, printing, credits, licences,
legal-deposit number if any) → dedication → epigraph → contents → lists of figures/tables → foreword (by someone
else) → preface (by the author) → acknowledgments → introduction (if not part of the text) → abbreviations /
notation.
Back (arabic continues): appendices → notes (endnotes) → glossary → bibliography/references → list of
contributors → illustration credits → index(es). Major divisions start on a recto.

## 5. Toolchains
| Route | Best for | Notes |
|---|---|---|
| Pandoc → LaTeX (memoir or KOMA `scrbook`) → LuaLaTeX | long, math-heavy books; best microtypography | custom template: `pandoc book.md --template=book.latex --top-level-division=chapter --pdf-engine=lualatex -o book.pdf`; layout lives in the template, not in `-V geometry` |
| Pandoc → Typst → PDF | fast iteration, simpler styling | `pandoc book.md -t typst -o book.typ` then `typst compile book.typ`, or `--pdf-engine=typst`; no PDF/X export — convert and preflight downstream |
| HTML + CSS Paged Media → PDF | CSS-based design; one source for web/EPUB | WeasyPrint 70 (`--pdf-variant pdf/x-1a`, `pdf/x-3`, `pdf/x-4`, `pdf/a-…`, `pdf/ua-…`), Vivliostyle CLI 11 (active); Paged.js still works but its last npm release is 0.4.3 (2023) |
| DOCX for a publisher/editor | when the house works in Word | Pandoc + reference document (§9) |
Keep one source of truth (Markdown + YAML metadata + bibliography + images); every output is generated.

## 6. Fonts and PDF for print
Read `references/fonts-pdf.md` when embedding fonts or exporting the print PDF.

## 7. Images
- Resolution at final printed size: ≥ 300 ppi for photos and greyscale (both printers); 600 ppi for 1-bit line
  art (IngramSpark). Check with `pdfimages -list book.pdf` (x-ppi / y-ppi columns) — never upsample to cheat.
- Black-and-white interiors: submit 8-bit greyscale (IngramSpark converts RGB/CMYK itself, with possible shifts).
  Convert deliberately and re-tone: midtones darken on uncoated paper (dot gain), so lighten and add contrast;
  keep tints ≥ 10 %. ImageMagick: `magick in.png -colorspace Gray out.png`; whole PDF with Ghostscript:
  `gs -o gray.pdf -sDEVICE=pdfwrite -sColorConversionStrategy=Gray -dProcessColorModel=/DeviceGray in.pdf`, then
  verify the `color` column of `pdfimages -list` shows `gray`. Profiles and rendering intents: `color-management`.
- Colour interiors and covers for IngramSpark: CMYK, total ink ≤ 240 % (their rich black: 60/40/40/100).
- Vector art as PDF with fonts outlined or embedded; no hairlines under 0.125 pt.
- Rights: every image licensed for print and ebook distribution; credit lines in captions or credits page.

## 8. Cover, spine, barcode, ISBN, legal deposit
Read `references/cover-isbn.md` when making the cover, spine or barcode, or handling ISBN and legal deposit.

## 9. DOCX via a reference document
Read `references/docx.md` when producing DOCX through a reference document.

## 10. EPUB
Read `references/epub.md` when producing or checking an EPUB.

## 11. Proofs and release checklist
- [ ] Trim, page count, paper, ink, binding recorded; margins meet the printer table; spreads checked.
- [ ] Front/back matter complete; copyright page has the right ISBN per format; TOC and page numbers correct.
- [ ] No widows/orphans at page tops, no headings at page bottoms, no overfull lines, blank versos blank.
- [ ] Fonts embedded, no Type 3; images ≥ 300 ppi (line art 600); B/W interior truly grey.
- [ ] Bleed only if needed and correctly sized; `pdfinfo -box` sane; PDF/X preflight passed where required.
- [ ] Cover built from the current calculator/template for the final page count and paper; barcode scans.
- [ ] EPUB passes epubcheck with zero errors; Ace report reviewed; metadata and cover correct.
- [ ] DOCX opens cleanly; styles mapped; math and footnotes survive.
- [ ] Printed proof ordered and read: colour, gutter readability, spine alignment, trim, image quality.
- [ ] Legal: ISBNs registered to the right imprint, legal deposit handled, rights/licences documented,
      AI-generated content disclosed where required.

## Verify
`pdffonts`, `pdfimages -list`, `pdfinfo -box`, `qpdf --check book.pdf`, page count vs cover spine calculation,
epubcheck + Ace, a printed proof — screen previews do not show gutter loss, dot gain or trimming drift.

## Deliverables / Report
Interior PDF (named per printer, e.g. `<isbn>_txt.pdf` for IngramSpark), cover PDF, EPUB, DOCX as requested;
build commands and source; a spec sheet (trim, pages, paper, ink, spine width, bleed yes/no, PDF standard, ISBN per
format); validation outputs (pdffonts, epubcheck, Ace, preflight summary); open issues and anything the user must
do on the printer's site (template request, ISBN assignment, AI disclosure, proof approval).
