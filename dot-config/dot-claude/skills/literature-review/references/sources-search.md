# Sources and search strategy

Part of `literature-review`.

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

Read `references/source-apis.md` when querying a source directly — arXiv (query syntax, listings, RSS, IDs, the arxiv MCP server), Semantic Scholar, OpenAlex (budget), Crossref and DOI content negotiation, DBLP, zbMATH Open, MR Lookup, PubMed: endpoints, parameters, rate limits and keys.

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
