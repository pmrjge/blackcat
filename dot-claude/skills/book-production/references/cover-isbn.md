# Book production: manuscript → print PDF, DOCX, EPUB: cover isbn

Read when making the cover, spine or barcode, or handling ISBN and legal deposit (moved from `book-production` SKILL.md).

## 8. Cover, spine, barcode, ISBN, legal deposit
- **Full wrap (paperback):** width = bleed + back + spine + front + bleed; height = bleed + trim height + bleed;
  bleed 0.125 in (3.2 mm KDP; 3 mm IngramSpark). **KDP spine** = pages × 0.002252 in (white paper; standard
  colour), × 0.0025 in (cream), × 0.002347 in (premium colour). Example: 6 × 9 in, 300 pages, white →
  spine 0.6756 in; cover 12.926 × 9.25 in. **IngramSpark:** always build on the template from its Cover Template
  Generator (dashboard → My Tools); spine width depends on the chosen paper, page count must be even.
- **Safe zones:** text ≥ 0.125 in (3 mm) inside trim and spine folds. KDP spine text only with more than 79 pages and
  0.0625 in (1.6 mm) clearance each side; IngramSpark spine safety 0.0625 in (2 mm) for spines ≥ 0.35 in,
  0.03125 in (1 mm) below, and no spine text under 48 pages (perfect bound).
- **Barcode:** EAN-13 of the ISBN-13, 100 % black on a white box. KDP places one automatically if you leave the
  area free; IngramSpark requires one (template barcode may be moved, never resized; otherwise leave
  1.75 × 1 in for it). US retail often adds a 5-digit price add-on (90000 = no price).
- **Files:** KDP cover = single PDF, ≥ 300 DPI images, ≤ 40 MB recommended (650 MB max); IngramSpark cover PDF on its template (remove the
  template's pink/blue guide areas if exporting from the PDF template). Ebook cover image is separate (IngramSpark:
  RGB JPEG, ≥ 1600 px on the short side and ≥ 1873 px on the long side).
- **ISBN:** Portugal — APEL's Agência Nacional de ISBN (isbn.apel.pt), also for self-publishers (*edição de autor*);
  print and ebook need distinct ISBNs; an unchanged reprint keeps its ISBN, a revised edition gets a new one;
  APEL can supply the barcode (fees listed in its FAQ). USA — Bowker; UK/Ireland — Nielsen; Brazil — Câmara
  Brasileira do Livro (since 2020); elsewhere — the International ISBN Agency directory. KDP's free ISBN only works
  on KDP and shows "Independently published"; with your own ISBN the imprint name must match the ISBN
  registration exactly; KDP ebooks need no ISBN.
- **Legal deposit (Portugal, Decreto-Lei n.º 74/82):** the printer requests the free depósito-legal number about a
  week before printing; for works printed abroad by a publisher domiciled in Portugal, the publisher deposits;
  the Biblioteca Nacional's default is 11 copies with reductions (e.g. one copy for runs of up to 100) — check BNP's
  current rules.
- **Guardrails:** fonts licensed for the use; no third-party logos or trademarks on covers without permission;
  public-domain texts need real added value on KDP; KDP requires disclosing AI-generated text, images or
  translations (AI-assisted editing need not be disclosed).
