---
name: literature-review
description: Use for paper search, bibliographies and reviews — arXiv, Semantic Scholar, OpenAlex, BibTeX.
---
# Literature search and review — zero fabricated citations

## Scope and the one rule
- Covers scoping, sources and APIs, search and snowballing, screening, reference verification, reading and claim
  extraction, synthesis, BibTeX hygiene, writing the review, and the citation audit.
- Not here: general web-search mechanics and source grading (`web-research`); prose craft (`technical-writing`);
  LaTeX bibliography mechanics (`latex-typesetting`); pooling statistics (`data-analysis`); judging ML evidence
  (`ml-experiment`, `llm-evals`).
- **The rule.** A reference enters any output only after its identifier (DOI, arXiv ID, zbMATH/MR number, PMID,
  ISBN) has been resolved *in this session* and its title, authors, year and venue match an authoritative record.
  Recall, LLM-written BibTeX, search snippets and other papers' reference lists are leads, never evidence. What
  cannot be verified is dropped or visibly marked `[UNVERIFIED]` — never complete missing fields by guessing.

## 1. Scope the question
Write down before searching: the question (empirical: setting, method, comparison, outcome; mathematics: objects,
property, what counts as an answer); review type (quick scan of 10–20 papers, related-work section, narrative
survey, or systematic review with a protocol and PRISMA 2020 reporting — Page et al., BMJ 2021,
doi:10.1136/bmj.n71); inclusion/exclusion criteria (years, venues, languages, preprints allowed?, document
types); 2–5 seed papers (verify them first — they calibrate vocabulary and recall); a stop rule (saturation:
new queries return only known items, or a time budget).

## 2–3. Sources and search strategy
Read `references/sources-search.md` when choosing where to search (arXiv, Semantic Scholar, OpenAlex, zbMATH and others; access notes) and running the search (vocabulary from seeds, one query log, snowballing).

## 4. Screening
Title/abstract pass, then full-text pass, each decision with a reason code (off-topic, wrong setting, superseded
version, weak evidence, inaccessible). Keep an "excluded, with reason" list for papers a reader would expect to
see. Re-screen a random 10 % later to check your own consistency.

## 5. Verify every reference before citing it
1. **Resolve the identifier** — DOI via Crossref (or DataCite/content negotiation); arXiv via the abs page or API;
   mathematics via zbMATH/MR; biomedicine via PMID; books via ISBN at the publisher. No identifier yet → find one
   (Crossref `query.bibliographic`, S2 `/paper/search/match`, DBLP, zbMATH) or treat it as unverified.
2. **Compare** title, full author list (order, spelling, diacritics), year, venue, volume/issue/pages or article
   number with the authoritative record — not with an aggregator or your memory.
3. **Version** — cite the published version when it exists (optionally with the arXiv ID); if claims changed
   between versions, cite the version you used (`2106.09685v2`). Pitfall: `https://arxiv.org/bibtex/<id>` exports
   `@misc` with the year of the *latest* version — 1706.03762 comes out as `year={2023}`, key
   `vaswani2023attentionneed`, though v1 is from 2017 and the paper appeared at NeurIPS 2017.
4. **Status** — Crossref `updated-by` lists retractions, corrections and expressions of concern (`source`:
   `publisher` or `retraction-watch`; Retraction Watch data is also a public Crossref GitLab dataset);
   `filter=updates:<DOI>` finds the notices; OpenAlex `is_retracted`; journal page; PubPeer for serious concerns;
   arXiv withdrawn versions. A retracted paper is cited only as retracted.
5. **Claim check** — the statement you attribute is really there: record theorem/section/table/page.
6. **Ledger** — write the row (§8). Anything failing a step is fixed or dropped.

Batch check: read `references/verify-refs-script.md` when checking a whole `.bib` (tested `verify_refs.py`, run with uv; flags title/first-author/year mismatches, failed lookups and `updated-by` notices; how to read its `CHECK` and `LOOKUP FAILED` lines).

## 6. Read efficiently and extract claims
Read `references/reading.md` when reading papers (Keshav's three passes, the five Cs) and extracting claims.

## 7. Synthesis
- **Matrix:** rows = papers (or claims), columns = the dimensions of your question (setting, assumptions, method,
  guarantee or metric, data, result, limitation). Read down columns for patterns and holes.
- **Taxonomy:** split by the axis that best explains differences (problem setting, technique, guarantee type, data
  regime); each paper in exactly one leaf; name each category by what unifies it.
- **Timeline:** who introduced what and when — first preprint date vs publication date; attribute priority only
  after checking both.
- **Contested results:** present each side with its evidence; locate the disagreement (definitions, metrics,
  datasets, assumptions, compute, errors); note replications; say what would settle it. Never average conflicting
  claims into a vague consensus.
- **Pooling numbers** only for comparable designs with reported variances (`data-analysis`).

## 8. Ledger and BibTeX hygiene
Ledger (CSV/JSONL), one row per reference: key, title, authors, year, venue, type, doi, arxiv_id (+ version),
other ids (zbMATH, MR, PMID, ISBN), verified_against (URL of the record), verified_on (date), status
(published / preprint / corrected / retracted), claims supported (with pinpoints).
- BibTeX rules (keys, authors, titles, DOI, arXiv fields, entry types, journals, encoding, bibtex-tidy/checkcites/biber tools, styles): read `references/bibtex-hygiene.md` when writing or cleaning `.bib` entries.

## 9. Writing the review
- Structure: scope and method (sources, queries, dates, criteria — enough to reproduce) → background and
  definitions → body organized by the taxonomy, never paper-by-paper → comparison table → contested points →
  gaps and open problems stated precisely ("no bound is known for X without assumption Y") → conclusion.
- Represent each work fairly, with its own conditions; separate "prove/measure" from "argue/conjecture".
- Every factual sentence about the literature carries a citation, and every citation supports the sentence it is
  attached to. Cite what you read; if you rely on someone else's summary, say "as reported in".
- Flag preprints ("not peer-reviewed as of <date>"); date the review ("literature searched up to YYYY-MM-DD").
- Quotations rare, exact, with page; otherwise paraphrase with a pinpoint.

## 10. Final citation audit — must pass before delivery
- [ ] 100 % of cited keys are in the ledger with `verified_against` and date; no `[UNVERIFIED]` remains, or each
      one is flagged to the user explicitly.
- [ ] Every identifier resolves; title, authors, year, venue and entry type match the record.
- [ ] Preprint/published pairs resolved; versions pinned where claims differ; arXiv-export years corrected.
- [ ] Retraction/correction check done for every DOI; results recorded.
- [ ] Each cited claim checked at its pinpoint.
- [ ] No duplicates (one work under two keys; preprint and published listed separately by accident).
- [ ] `verify_refs.py` output reviewed; `checkcites` clean; bibliography compiles without warnings.
- [ ] Query log and inclusion/exclusion reasons complete.
- [ ] Spot re-verification: re-resolve a random 10 % (at least 5) from scratch; any failure → re-audit everything.

## Verify
Run the batch check on the final `.bib`; open each `CHECK`/`FAILED` item by hand; re-run the query log's most
important queries to confirm nothing major appeared since; have the audit list reproduced by a second pass or
session that did not build the bibliography.

## Deliverables / Report
The review text (or related-work section); `refs.bib`; the ledger (CSV); the query log; the synthesis matrix;
excluded-with-reason list; the audit results (script output + manual resolutions); an explicit list of anything
unverified or contested, with what would be needed to resolve it.
