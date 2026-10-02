# Literature review: BibTeX hygiene

- **Keys:** `lastnameYEARword` (e.g. `keshav2007read`), ASCII, unique, stable; never recycle a key.
- **Authors:** `Last, First and Last, First`, complete lists as published; diacritics as in the record.
- **Titles:** protect proper nouns and acronyms only — `{B}ayesian`, `{GPU}`, `{Lie} algebras`; never brace the
  whole title (it blocks style-driven case changes).
- **DOI:** bare (`doi = {10.1145/1273445.1273458}`); `url` only when there is no DOI.
- **arXiv:** biblatex `eprint = {2106.09685}, eprinttype = {arxiv}, eprintclass = {cs.LG}`; arXiv's own export
  uses `eprint`, `archivePrefix = {arXiv}`, `primaryClass` — whether a given `.bst` prints them varies, so check
  the typeset bibliography.
- **Entry types:** `@article` (+ `journal`), `@inproceedings` (+ `booktitle`), `@book`, `@incollection`,
  `@phdthesis`, `@misc`/`@online` for preprints and web pages, biblatex `@software`.
- **Journals:** full names or ISO 4 abbreviations, consistently (zbMATH and MR give both).
- **Encoding:** biber reads UTF-8; classic BibTeX needs `{\"o}`-style escapes.
- **Tools:** `npx bibtex-tidy refs.bib --duplicates=doi,key,citation --merge=combine --sort --modify` (its
  escaping of Unicode to LaTeX is on by default — turn it off for biber; see `--help`); `checkcites main.aux`
  or `checkcites --backend biber main.bcf` for unused/undefined keys; `biber --tool --validate-datamodel refs.bib`
  for fields the data model does not know.
- **Styles:** follow the venue — biblatex or `.bst` in LaTeX, CSL (Zotero style repository) with Pandoc
  `--citeproc`; numeric is usual in maths/CS venues, author–year in surveys meant for browsing.
