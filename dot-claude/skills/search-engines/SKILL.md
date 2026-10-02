---
name: search-engines
description: Use for full-text or hybrid search — Elasticsearch, OpenSearch, Meilisearch, Typesense, Tantivy, BM25, relevance.
---
# Search engines (full-text and hybrid)

## Scope
Keyword and hybrid search over documents, products or logs. Retrieval for LLMs (chunking, embeddings, reranking): `rag-agents`. Engine choice among databases: `db-design`.

## Choosing an engine
| Need | Start with |
|---|---|
| Search inside an existing Postgres app, modest scale | PostgreSQL full-text (`tsvector`, GIN) + `pg_trgm` for fuzzy matching (`postgresql`); pgvector for embeddings |
| Embedded or single-process search in Rust | Tantivy |
| Typo-tolerant instant search for apps and sites | Meilisearch or Typesense |
| Large-scale text, logs, aggregations, many shards | Elasticsearch or OpenSearch |
| SQLite apps | SQLite FTS5 (`sqlite`) |

Check each engine's licence for your deployment (Elasticsearch and OpenSearch differ; licence details unverified as of 2026-10-02).

## Indexing
- Define the schema explicitly (field types, which fields are searchable, filterable, sortable, facetable); don't rely on dynamic mapping in production.
- Analyzers per language: tokenizer, lowercasing, ASCII/accent folding (essential for Portuguese), stemming or lemmatization, stop words; keep an unstemmed field for exact matches and phrases.
- Synonyms and spelling variants as managed lists; edge n-grams or prefix queries for autocomplete; separate fields for identifiers (SKUs, codes) with keyword analysis.
- Reindex through an alias: build a new index, backfill, switch the alias atomically, keep the old one until verified.
- Keep the search index derived: the source of truth stays in the database; changes flow via change data capture or an outbox (`dist-systems`), with a full rebuild path.

## Ranking
- BM25 is the baseline for keyword relevance; boost fields (title > body), recency or popularity with explicit, tested functions.
- Hybrid: run keyword and vector retrieval, fuse with reciprocal rank fusion (RRF) or a learned combination; optionally rerank the top k with a cross-encoder (`rag-agents`).
- Filters (permissions, tenant, availability) are applied inside the engine query, never after fetching a page of results.

## Measuring relevance
- Build a judgment set: real queries (from logs) with graded relevant documents; include zero-result and ambiguous queries.
- Metrics: nDCG@10, recall@k, MRR; plus zero-result rate and click/conversion signals online. Compare configurations on the same judgments; A/B test online changes.

## Operations
- Monitor query latency percentiles, indexing lag, heap/memory, shard sizes; snapshot indices (or be able to rebuild from the source).
- Protect the cluster: query timeouts, result-window caps (deep pagination via search-after cursors), rate limits; never expose the engine directly to the internet.

## Verify
- [ ] Analyzer output checked on sample text (accents, plurals, codes) with the engine's analyze API.
- [ ] Relevance metrics on the judgment set before and after each ranking change.
- [ ] Permission filters tested with two users; a rebuild from the source of truth exercised once.

## Sources
- Verified 2026-10-02 https://github.com/elastic/elasticsearch/releases/latest — Elasticsearch 9.5.4; https://github.com/opensearch-project/OpenSearch/releases/latest — OpenSearch 3.9.0; https://github.com/meilisearch/meilisearch/releases/latest — Meilisearch 1.54.3; https://github.com/typesense/typesense/releases/latest — Typesense 30.2; https://crates.io/api/v1/crates/tantivy — Tantivy 0.26.2.
- Unverified as of 2026-10-02: Elasticsearch/OpenSearch licensing and governance; SQLite FTS5 and Postgres feature details (see the engine modules).
