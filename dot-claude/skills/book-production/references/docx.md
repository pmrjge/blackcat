# Book production: manuscript → print PDF, DOCX, EPUB: docx

Read when producing DOCX through a reference document (moved from `book-production` SKILL.md).

## 9. DOCX via a reference document
```bash
pandoc -o custom-reference.docx --print-default-data-file reference.docx   # then edit styles in Word/LibreOffice
pandoc book.md --reference-doc=custom-reference.docx --toc --citeproc -o book.docx
```
Only restyle what Pandoc uses; page size, margins, headers and footers come from the reference document.
Paragraph styles: Normal, Body Text, First Paragraph, Compact, Title, Subtitle, Author, Date, Abstract,
AbstractTitle, Bibliography, Heading 1–9, Block Text, Footnote Block Text, Source Code, Footnote Text,
Definition Term, Definition, Caption, Table Caption, Image Caption, Figure, Captioned Figure, TOC Heading.
Character styles: Default Paragraph Font, Verbatim Char, Footnote Reference, Hyperlink, Section Number; table style
Table. Anything else via `::: {custom-style="Epigraph"}` / `[text]{custom-style="Term"}`. Math becomes native Word
equations; footnotes become Word footnotes. Fine Word edits: the `docx` skill.
