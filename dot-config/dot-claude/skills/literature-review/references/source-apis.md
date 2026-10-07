# Literature review: source APIs

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
