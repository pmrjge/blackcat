---
name: typography
description: Load before choosing, setting or specifying type for print or screen — pairing, scales, measure, leading, kerning, OpenType, Portuguese conventions, web fonts, licensing, QA.
---
# Typography

## Scope
Choosing, pairing and setting type for print, screen, UI and data; variable and web fonts; language
conventions (Portuguese in detail); math; licensing; accessibility; QA. Not here: contrast math
(`color-management`), logotype construction (`brand-identity`), slide type sizes per app
(`presentation-design`).

Tools: fontTools (`uv run --with fonttools --with brotli …`: `pyftsubset`, `fonttools varLib.instancer`,
`TTFont`), `fc-list`/`fc-query`, `pdffonts` (poppler); Illustrator MCP: `list_fonts` (exact names;
`create_text_frame` rejects anything else), `list_text_frames`, `get_text_frame_detail`, `list_text_styles`,
`apply_text_style`, `check_text_consistency`, `convert_to_outlines`.

## 1. Choose typefaces
| Role | Look for | Avoid |
|---|---|---|
| Long reading, print | Moderate contrast, open apertures, even color, true italic, oldstyle and lining figures, small caps | Display cuts at text size; hairlines on uncoated stock |
| Long reading, screen | Generous x-height, sturdy strokes, good rendering at 14–20 px, optical-size axis | Weights below 300 at text sizes |
| UI | Tabular figures, distinct I l 1 and O 0, compact width, several weights | Families without full Latin diacritics |
| Tables, data | Tabular lining figures, slashed/dotted zero, condensed widths | Proportional oldstyle figures in columns |
| Display, posters, logos | Character; spacing and accents that hold at size | The same cut at 8 pt |
| Signage | Open apertures, large x-height, distinct forms | Condensed, tightly spaced faces |

Per candidate check: coverage for every language (snippet in §6, `references/opentype-variable.md`), weights with true italics, figure sets,
small caps, optical sizes, hinting for Windows, formats (OTF/TTF/WOFF2/variable), a license for every
medium (§11, `references/licensing.md`). Classification vocabulary for reasoning about pairs: humanist/old-style, transitional,
didone, slab, grotesque, neo-grotesque, geometric, humanist sans, mono.

Pairing: a superfamily (serif + sans drawn together) is the safe default. Otherwise match proportions
(x-height, width) and contrast construction (humanist sans + old-style serif share a calligraphic skeleton;
geometric sans + didone for display). Give each family a role (display, text, UI, data); two families plus
a mono at most. Test with real copy at real sizes, including Portuguese accents and long compounds.

## 2. Scale and hierarchy
- Modular scale: sizeₙ = base × rⁿ. Ratios: 1.125 (major second), 1.2 (minor third), 1.25 (major third),
  1.333 (perfect fourth), 1.414 (augmented fourth), 1.5 (perfect fifth), 1.618 (golden). Dense UI
  1.125–1.2; editorial 1.25–1.333; posters ≥ 1.5.
- `uv run python -c "print([round(16*1.25**n, 1) for n in range(-2, 6)])"` → 10.2, 12.8, 16, 20, 25, 31.2, 39.1,
  48.8. Round to whole px or half points and correct by eye (x-heights differ between families).
- Fluid web type: `font-size: clamp(1rem, 0.9rem + 0.5vw, 1.25rem)`; keep a rem term so zoom still works.
- Hierarchy through size, weight, case, color and space: change one or two variables per level, three or
  four levels per page.

## 3. Measure, leading, spacing
- Measure: 45–75 characters, 66 ideal, in one column; 40–50 in multi-column work (Bringhurst). WCAG 1.4.8
  (AAA) caps blocks at 80. CSS `max-width: 66ch` approximates it (`ch` = width of "0").
- Leading: screen text 1.4–1.6; print text about 120–145 % of the size; longer lines need more; headings
  1.0–1.2; negative leading only for display caps without descenders.
- Paragraphs: first-line indent (1 em) or space between, never both; no indent after a heading.
- WCAG 1.4.12 (AA): layouts must survive user overrides of line-height 1.5, paragraph spacing 2 em,
  letter spacing 0.12 em, word spacing 0.16 em: no fixed-height text boxes, no clipped overflow.
- Multi-column print: baseline grid, cross-heads aligned to it.

## 4. Kerning, tracking, word space
- Kerning is pair-specific. Adobe offers Metrics (the font's kerning; right for well-made fonts) and
  Optical (algorithmic; for poorly kerned fonts, mixed fonts, caps display). Kern display lines and
  logotypes by eye at final size.
- Tracking is uniform, in 1/1000 em in Adobe apps. All caps and small caps +50 to +100; very small text
  slightly positive; large display often −10 to −30. Never track body text to copyfit: edit or reflow.
- Extra letter spacing without matching word spacing slows reading (Galliussi et al. 2020); the British
  Dyslexia Association asks for word spacing ≥ 3.5× letter spacing.
- CSS: `letter-spacing` in `em`; `font-kerning: normal` where an engine disables kerning.

## 5. Alignment, rag, breaks
- Flush left, ragged right: default for screen, narrow columns and accessibility. Justify only with
  hyphenation, an adequate measure and Adobe Every-line Composer; look for rivers.
- Rag: no deep steps or shapes; fix with soft returns, never spaces. Headings: `text-wrap: balance`
  (applied up to 6 lines in Chromium, 10 in Firefox); paragraphs: `text-wrap: pretty` as an enhancement.
- Orphan: a paragraph's first line alone at the foot of a column; widow: its last line alone at the head of
  the next (Bringhurst); runt: a very short last line. CSS `orphans`/`widows` apply in paged and
  multicolumn contexts; in Adobe apps fix by rewriting, re-breaking or tracking one paragraph ±5–10.
- Hyphenation: `hyphens: auto` needs a correct `lang` (`lang="pt-PT"`); Adobe apps take the language from the
  Character panel (Show Options). At most 2–3 consecutive hyphens; never split names or numbers.
  Portuguese: when a compound breaks at its own hyphen, the hyphen is repeated at the start of the next line
  (segunda-/-feira, EU PT style guide). Adobe apps don't do this: prevent the break (non-breaking hyphen
  U+2011 or No Break) or set it by hand.
- Non-breaking spaces (U+00A0; narrow U+202F): number + unit (5 mm), "n.º 3", "p. 12", initials, digit
  groups (300 000).

## 7. Language, punctuation, Portuguese
- Real characters: “ ” ‘ ’ (the apostrophe is ’), en dash –, em dash —, minus −, ellipsis …, ×, primes
  ′ ″. Straight quotes and double hyphens are typing artefacts: replace them.
- European Portuguese (EU Interinstitutional Style Guide, PT edition): quotes nest « » → “ ” → ‘ ’, with no
  inner spaces; the full stop goes inside the closing quote only when the whole sentence is quoted;
  travessão (—) for dialogue, parenthetical pairs and emphasis; spans of whole years with a hyphen
  (1993-1996), split years with a slash (1996/1997); ordinals 1.º and 1.ª with the ordinal indicators º ª
  (U+00BA, U+00AA), never the degree sign ° (U+00B0); quantities grouped with a protected space (300 000),
  years and page numbers ungrouped (1961, p. 2064); decimal comma (13,6); the ellipsis as one character.
  House styles vary and Ciberdúvidas stresses consistency over any single choice: confirm one, apply it.
  Spelling, grammar and wider pt-PT writing rules: `portuguese-pt-writing`.
- English house styles: en dash for ranges (10–12), em dash (or spaced en dash) for breaks.
- Display type and logos: check Ã Õ Ç É Ê Í Ó Ô Ú at size; capital accents collide with the line above at
  tight leading and may need redrawn, flatter forms.
- Declare the language (`lang`, Character panel) for hyphenation, spell-check and screen readers.

## 12. Accessibility
- WCAG has no minimum font size. It requires resize to 200 % (1.4.4), reflow at 320 CSS px (1.4.10),
  surviving text-spacing overrides (1.4.12), contrast 4.5:1 or 3:1 for large text = 18 pt or 14 pt bold
  (1.4.3; computation in `color-management`), and real text instead of images of text.
- Practical floors: web body ≥ 16 px; print body 9–12 pt depending on x-height; no weights below 300 at
  text sizes; no light text on tints.
- British Dyslexia Association style guide (2023): sans serif, 12–14 pt (16–19 px), line spacing 1.5, left
  aligned and not justified, no italics, underlining or long runs of capitals, headings ≥ 20 % larger,
  cream or off-white backgrounds, matt paper, 60–70 characters per line.
- Myths: "dyslexia fonts" (OpenDyslexic, Dyslexie) did not improve reading speed or accuracy in controlled
  studies (Wery & Diliberto 2017; Kuster et al. 2018), and dyslexia-oriented letterforms showed no effect
  (Galliussi et al. 2020); spacing and layout matter more. Never sell a font as an accessibility fix.

## 13. QA checklist
- Characters: quotes, apostrophes, dashes, minus, ellipsis, º vs °, × vs x; no double spaces or
  space-aligned columns.
- Language set; hyphenation sane; Portuguese compound breaks handled; non-breaking spaces in units and
  numbers.
- Widows, orphans, runts, rivers, rag shape; no heading stranded at a column foot; no overset text.
- No faux bold, italic or small caps; no substituted fonts (`list_text_frames`; `pdffonts out.pdf` lists
  every font with `emb yes`, subsets prefixed `ABCDEF+`).
- Styles consistent (`get_text_frame_detail`, `list_text_styles`); `check_text_consistency` finds leftover
  placeholder text and notation variants.
- Tables: tabular lining figures, aligned decimals, units in headers.
- Sizes, leading and contrast meet the floors; caps tracked; display kerning checked at final size.
- A license on record for every font and medium.

## References
- `references/opentype-variable.md` — read when using OpenType features, figure styles or variable-font axes.
- `references/web-fonts.md` — read when loading and subsetting fonts for the web.
- `references/math.md` — read when setting mathematics.
- `references/licensing.md` — read when checking whether a font licence covers the use (web, app, embedding, logo).

## Verify
- Read a page at 100 % in its real medium (printed proof, or the target device); check the smallest size.
- Run the fontTools snippet on every font: glyphs, features and `fsType` fit the delivery.
- `pdffonts` on every PDF; load web fonts on a throttled connection (flash of fallback text, layout shift)
  and confirm subsets still hold the glyphs and features in use.

## Deliverables / Report
- Type specification: families, styles, sources and licenses; scale per role (size, leading, tracking) for
  print and screen; OpenType features per role; language settings; CSS (`@font-face`, tokens) or the
  paragraph/character style list.
- Font files only when the license allows; otherwise purchase/download links.
- QA notes: what was found and fixed, and remaining risks (missing glyphs, license limits, fallbacks).
