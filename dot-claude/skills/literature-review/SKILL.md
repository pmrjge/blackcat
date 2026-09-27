---
name: literature-review
description: Load before searching for papers, building a bibliography, or writing a literature review or related-work section — scoping, search via arXiv, Semantic Scholar, OpenAlex, Crossref, DBLP, zbMATH Open, MathSciNet, PubMed and Google Scholar, snowballing, screening, verifying every reference (zero fabricated citations), efficient reading, synthesis, BibTeX hygiene and a final citation audit.
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

## 2. Sources
| Source | Best for | Access (verified Sept 2026) |
|---|---|---|
| arXiv | preprints in math, physics, CS, stats, q-bio, econ | API `https://export.arxiv.org/api/query` (Atom; `http://` now 301-redirects); listings; RSS; arxiv MCP server |
| Semantic Scholar | cross-field search, citation graph with contexts | `https://api.semanticscholar.org/graph/v1` |
| OpenAlex | open metadata, filters, citation links, retraction flag | `https://api.openalex.org` (budgeted, see below) |
| Crossref | authoritative publisher metadata for DOIs, updates/retractions | `https://api.crossref.org` |
| DBLP | CS venues and author pages | `https://dblp.org/search/publ/api` |
| zbMATH Open | mathematics (free), MSC classification, reviews | `https://api.zbmath.org/v1` |
| MathSciNet | mathematics reviews (subscription); free MR Lookup for citations | `https://mathscinet.ams.org/mrlookup` |
| PubMed | biomedicine | E-utilities `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/` |
| Google Scholar | coverage check, "Cited by" | no API — WebSearch/browser only; do not scrape |
| OpenReview | ML reviews and decisions | web |

**arXiv.** `search_query` with prefixes `ti`, `au`, `abs`, `co`, `jr`, `cat`, `rn`, `all`; `AND`, `OR`, `ANDNOT`;
`sortBy=relevance|lastUpdatedDate|submittedDate`; `start`, `max_results` (≤ 2000 per call, 30 000 total); wait
3 s between calls. Date filter: `submittedDate:[202501010000+TO+202512312359]`. Example:
`https://export.arxiv.org/api/query?search_query=cat:math.PR+AND+abs:%22random+walk%22&sortBy=submittedDate&sortOrder=descending&max_results=200`.
Listings by category: `https://arxiv.org/list/<cat>/new` (new submissions, cross-lists, replacements),
`/recent`, `/pastweek`, and months as `https://arxiv.org/list/<cat>/YYYY-MM?skip=0&show=2000`. RSS/Atom:
`https://rss.arxiv.org/rss/<cat>` (join categories with `+`, e.g. `cs.LG+stat.ML`), updated daily.
IDs: `YYMM.NNNNN` (5 digits since 1501; 4 digits 0704–1412), version suffix `vN`; old style `math.GT/0107001`.
Every paper has a DataCite DOI `10.48550/arXiv.<id>`.
**arxiv MCP server** (on-demand from the magg catalog, prefix `arxiv`): `search_papers` (query, categories,
date_from/date_to, sort_by), `get_abstract`, `download_paper`, `read_paper`, `get_paper_outline`,
`read_paper_section`, `search_paper_text`, `get_paper_latex`/`get_paper_latex_section`, `citation_graph`
(Semantic Scholar backed), `export_citations` (BibTeX from arXiv metadata), `watch_topic`/`check_alerts`.
`mcp__jina` `search_arxiv` suffices for quick lookups.

**Semantic Scholar.** `/paper/search?query=…&fields=title,year,authors,venue,externalIds,citationCount`
(plain text only; hyphenated terms return nothing — replace hyphens with spaces; `limit` ≤ 100, at most 1000
ranked results; filters `year=2019-2025`, `fieldsOfStudy=Mathematics`, `venue=`, `publicationTypes=`,
`minCitationCount=`, `openAccessPdf`); `/paper/search/bulk` (boolean query, up to 1000 per call with a
continuation `token`); `/paper/search/match?query=<exact title>`; `/paper/<id>` where id is a S2 hash or
`DOI:…`, `ARXIV:…`, `CorpusId:…`, `PMID:…`, `PMCID:…`, `ACL:…`, `MAG:…`, `URL:…`; `/paper/<id>/references` and
`/paper/<id>/citations` (`limit` ≤ 1000; fields such as `contexts`, `intents`, `isInfluential`);
`/snippet/search` for full-text passages; `POST /paper/batch` for many ids. API key in header `x-api-key`
(introductory rate 1 request/s); without a key requests share a throttled pool — back off on HTTP 429.

**OpenAlex.** Singleton lookups are free: `/works/doi:10.1145/1273445.1273458`, `/works/W2108933707`.
Lists cost budget: `/works?search=…` ($1 per 1000 calls) and `/works?filter=…` ($0.10 per 1000): e.g.
`filter=cites:W2108933707` (works citing it), `filter=cited_by:W…` (its references; also the `referenced_works`
field), `related_to:W…`, `publication_year:2020-2025`, `type:article`; combine with `,` (AND), `|` (OR), `!`
(NOT); `per_page` ≤ 100; the `is_retracted` field. Without a key the daily budget ($0.10) is shared by everyone on
the same IP and is often exhausted on shared networks (HTTP 429 "Insufficient budget"); a free key
(`api_key=…` or `Authorization: Bearer …`) gives $1/day; hard limit 100 requests/s.

**Crossref.** `https://api.crossref.org/works/<DOI>` is the ground truth for DOI metadata (title, authors,
container, volume/issue/pages, dates, licence, `updated-by`). Resolve messy references with
`/works?query.bibliographic=<whole reference string>&rows=5` and compare fields — the top hit can be wrong.
Also `select=`, `filter=`, `rows` ≤ 1000, `cursor=*` for deep paging. Add `mailto=you@example.org` (or a
User-Agent with contact) for the polite pool; limits come back in `x-rate-limit-limit`, `x-rate-limit-interval`,
`x-concurrency-limit` (observed: public 5/s with 1 concurrent, polite 10/s with 3).
**DOI content negotiation** (Crossref, DataCite — including arXiv DOIs — and mEDRA):
`curl -sLH "Accept: application/x-bibtex" https://doi.org/<DOI>`; CSL-JSON with
`application/vnd.citationstyles.csl+json`; formatted text with `text/x-bibliography; style=apa`.

**DBLP.** `https://dblp.org/search/publ/api?q=<query>&format=json&h=100&f=0` (`h` ≤ 1000); BibTeX at
`https://dblp.org/rec/<key>.bib`. From cloud IPs DBLP may answer with an HTML bot-check page instead of
JSON/BibTeX — detect `content-type: text/html` and fall back to WebFetch, a browser, or other sources.
**zbMATH Open.**
```bash
curl -sG https://api.zbmath.org/v1/document/_search --data-urlencode 'page=0' \
  --data-urlencode 'results_per_page=20' \
  --data-urlencode 'search_string=au:Wigderson & ti:expander & py:2006'
```
Fields `au`, `ti`, `py` (ranges `py:2020-2021`), `cc` (MSC code, e.g. `cc:05C48`), `so` (source); results carry
DOI and arXiv links, MSC codes and reviews. **MR Lookup** (free) returns MathSciNet BibTeX for a known paper:
`https://mathscinet.ams.org/mrlookup?ti=<title words>&au=<author>&format=bibtex`.
**PubMed.** `esearch.fcgi?db=pubmed&term=…&retmode=json` → `esummary`/`efetch`; 3 requests/s without key, 10 with
`api_key`; send `tool` and `email`.

## 3. Search strategy
1. **Vocabulary from seeds:** terms, synonyms, notation variants, older and field-specific names; classification
   codes (arXiv categories, MSC 2020, ACM CCS).
2. **One query log** (CSV): source, query string, filters, date run, hits, new relevant items. Needed for
   reproducibility and for PRISMA counts.
3. **Recent work:** sweep arXiv listings or RSS of 1–3 categories for the last months (titles first).
4. **Snowballing** (Wohlin, EASE 2014, doi:10.1145/2601248.2601268): backward (references of every included paper)
   and forward (papers citing it: S2 `/citations`, OpenAlex `cites:`, Google Scholar "Cited by"); iterate until
   a round adds nothing. Citation `contexts`/`intents` show *how* a paper is used — support, contrast, method.
5. **Authors and venues:** key authors' recent output (DBLP/zbMATH/S2 author pages); last 2–3 years of key venues.
6. **Grey literature** when relevant (theses, technical reports, standards) — labelled as such.
7. **Deduplicate:** lowercase DOIs, strip arXiv versions, casefold titles without punctuation; link preprint ↔
   published version (S2 `externalIds`, the arXiv journal-ref/DOI fields, Crossref relations).

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

Batch check (tested): flags title/first-author/year mismatches, failed lookups and `updated-by` notices.
```python
# verify_refs.py — run: uv run --with 'bibtexparser<2' python verify_refs.py refs.bib you@example.org
import json, re, sys, time, unicodedata, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
import bibtexparser

def norm(s):
    s = unicodedata.normalize("NFKD", re.sub(r"[{}\\]", "", s or ""))
    return re.sub(r"[^a-z0-9]+", " ", s.encode("ascii", "ignore").decode().lower()).strip()

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"verify-refs (mailto:{sys.argv[2]})"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

ATOM = "{http://www.w3.org/2005/Atom}"
for e in bibtexparser.load(open(sys.argv[1], encoding="utf-8")).entries:
    key, title, year = e["ID"], norm(e.get("title")), e.get("year", "")
    first = norm(e.get("author", "").split(" and ")[0].split(",")[0])
    try:
        if "doi" in e:
            m = json.loads(get("https://api.crossref.org/works/" + urllib.parse.quote(e["doi"])))["message"]
            t, y = norm((m.get("title") or [""])[0]), str(m.get("issued", {}).get("date-parts", [[None]])[0][0])
            a = norm((m.get("author") or [{}])[0].get("family", ""))
            flags = [u.get("type") for u in m.get("updated-by", [])]
        elif "eprint" in e:
            ent = ET.fromstring(get("https://export.arxiv.org/api/query?id_list=" + e["eprint"])).find(ATOM + "entry")
            t, y = norm(ent.findtext(ATOM + "title")), ent.findtext(ATOM + "published")[:4]   # v1 year
            a = norm(ent.find(ATOM + "author").findtext(ATOM + "name").split()[-1])
            flags = []
            time.sleep(3)                                       # arXiv: 3 s between calls
        else:
            print(f"{key}: NO IDENTIFIER — resolve manually"); continue
    except Exception as exc:                                   # an unresolvable id is itself a finding
        print(f"{key}: LOOKUP FAILED ({exc})"); continue
    author_ok = bool(a and first) and (a in first or first in a)
    problems = [n for n, ok in (("title", t == title), ("first-author", author_ok), ("year", y == year)) if not ok]
    if flags: problems.append("UPDATED-BY:" + ",".join(flags))
    print(f"{key}: {'OK' if not problems else 'CHECK ' + ' '.join(problems)}")
```
Every `CHECK` needs a human look (a published version legitimately has a different year than v1; retracted
titles gain a "RETRACTED:" prefix); `LOOKUP FAILED` on a DOI usually means a fabricated or mistyped DOI.

## 6. Read efficiently and extract claims
Keshav's three passes (ACM SIGCOMM CCR 37(3), 2007, doi:10.1145/1273445.1273458): (1) 5–10 min — title,
abstract, introduction, headings, conclusions, glance at references; answer the five Cs: Category, Context,
Correctness, Contributions, Clarity; drop or continue. (2) Up to an hour — figures, tables, theorem statements,
experimental set-up; mark references to snowball. (3) Several hours — re-derive or virtually re-implement;
hunt hidden assumptions.
- Mathematics: read definitions and hypotheses exactly and compare them with your setting; note the proof technique;
  check whether the result was later strengthened, corrected, refuted or formalized (e.g. in Lean/mathlib).
- Extraction row per claim: claim (verbatim or exact paraphrase) | pinpoint | type (theorem, empirical,
  conjecture, survey statement) | evidence | strength | caveats.
- **Evidence strength.** Mathematics: refereed journal proof > refereed conference with full proof > preprint with
  full proof (weigh follow-ups and known errata) > sketch/announcement; a formal proof certifies exactly the
  formalized statement. Empirical/ML: independent replication > several datasets, tuned strong baselines, ≥ 3 seeds
  with variance, ablations, released code and data > single run or dataset without variance > anecdote; check
  leakage, contamination and compute parity. Surveys orient; cite primary sources for specific claims. Citation
  counts measure attention, not correctness.

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
