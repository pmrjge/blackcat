# Interior layout

Part of `book-production`.

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
