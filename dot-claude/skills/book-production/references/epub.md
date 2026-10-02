# Book production: manuscript → print PDF, DOCX, EPUB: epub

Read when producing or checking an EPUB (moved from `book-production` SKILL.md).

## 10. EPUB
- **Standard:** EPUB 3.3 (W3C Recommendation; 3.4 in progress). Container rules: `mimetype` first in the ZIP,
  stored uncompressed, content `application/epub+zip`; `META-INF/container.xml` points to the package document;
  required metadata `dc:identifier`, `dc:title`, `dc:language` and `meta property="dcterms:modified"`; an EPUB
  navigation document is mandatory (NCX only for legacy readers).
- **Pandoc:**
```bash
pandoc book.md --metadata-file=epub.yaml --epub-cover-image=cover.jpg --css=epub.css \
  --toc --split-level=1 --math-method=mathml -o book.epub
# mathml is Pandoc's default math method (--mathml is deprecated); --epub-chapter-level = old name of --split-level
```
  `epub.yaml`: `title`, `creator` (role), `identifier` (scheme `ISBN-13`), `lang`, `publisher`, `rights`, and the
  accessibility fields `accessModes`, `accessModeSufficient`, `accessibilityFeatures`, `accessibilityHazards`,
  `accessibilitySummary`. Embed fonts only if licensed (`--epub-embed-font`).
- **Accessibility:** alt text on every informative image, correct heading hierarchy, real tables, language set,
  MathML or described images for maths (test on target readers — MathML support varies). E-books sold in the EU
  fall under the European Accessibility Act (applying since 28 June 2025; microenterprises providing services are
  exempt). Check with DAISY Ace: `npx @daisy/ace -o ace-report book.epub`.
- **Validate:** `epubcheck book.epub` (Homebrew formula, 5.4.0) — zero errors before any upload. IngramSpark:
  EPUB 3, no image over 3.2 megapixels. KDP ebooks: EPUB, DOCX or KPF (Kindle Create); MOBI is no longer
  accepted for fixed-layout; preview in Kindle Previewer.
- Reflowable, not fixed-layout, for text books; fixed layout only for picture books/comics.
