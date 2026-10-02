---
name: graph-rag
description: Use when retrieval needs relations or multi-hop facts — Graphiti, Neo4j, LightRAG, GraphRAG.
---
# Graph RAG and knowledge-graph memory

## Scope
Building, querying, maintaining and evaluating knowledge graphs for RAG and agent memory. Chunk RAG, embeddings and rerankers → `rag-agents`; metrics and statistics → `llm-evals`; local model servers → `local-llm-serving`; memory write policies inside an agent → `agent-harness-design`. Library facts below were checked against graphiti-core 0.30, lightrag-hku 1.5, graphrag 3.2, falkordb 1.7 and neo4j 6.x (September 2026); these move fast — confirm signatures in the installed version (libdocs or the package source).

## 1. Graph or plain vector RAG?

| Question shape | Better fit |
|---|---|
| One fact stated in one passage | hybrid chunk RAG (`rag-agents`) |
| Multi-hop ("suppliers of X's competitors") | graph traversal, or iterative retrieval over chunks |
| Corpus-wide themes ("main risks across all reports") | community summaries (GraphRAG global search) or map-reduce over chunks |
| Facts that change ("current owner", "as of March") | temporal KG with validity intervals |
| Entity-centric lookups with many aliases | KG with entity resolution |
| Exact filters, counts, joins over structured fields | SQL/DuckDB, not an LLM-built graph |

A graph costs one or more LLM calls per chunk at ingest, adds extraction errors and needs schema upkeep. Build the hybrid-chunk baseline first; adopt the graph only when the labeled evaluation (§8) shows a gain on the questions that matter.

## 2. Extraction pipeline
1. Schema: 5–20 entity types with attributes, relation types with allowed (source type, target type) pairs, a generic fallback type; version it. A domain schema beats open extraction for precision; open extraction finds what you did not anticipate — run it on a sample to design the schema.
2. Chunk by structure (sections, messages), ~300–1000 tokens, carrying doc id, title, date, author, URL.
3. Extract per chunk with structured output (JSON schema or strict tool): entities (name, type, attributes, one-line description), relations (source, type, target, a self-contained fact sentence, time qualifiers), each with the supporting quote. Instruct "only what the text states"; no inference across chunks at this stage.
4. Validate before loading: schema check; relation type allowed for the endpoint types; the quote occurs in the chunk (normalized string match) — reject otherwise; drop self-loops and empty names.
5. Entity resolution: normalize (NFKC, case, punctuation, honorifics, legal suffixes); block candidates (same type + shared tokens or name-embedding kNN); score pairs (string similarity, embedding cosine, attribute agreement, co-occurring neighbours); send only the ambiguous band to an LLM judge; merge into a canonical node with an alias list and a reversible merge log.
6. Provenance on every node and edge: source chunk ids, doc ids, extractor model + prompt version, ingested_at, document date. Nothing without provenance enters the graph.
7. Load with `MERGE` on stable canonical ids, never on raw names; attach chunks as nodes (`(:Chunk)-[:MENTIONS]->(:Entity)`) so answers can cite text.
- Cost check first: extract a 1% sample, measure tokens per chunk and precision on 50 hand-checked facts, extrapolate. Use a fast non-thinking model for extraction and a stronger one for answering (LightRAG's own guidance).

## 3. Temporal knowledge graphs
Read `references/graphiti.md` when facts change over time (Graphiti episodes, bi-temporal edges, invalidation).

## 4. Graph databases
Read `references/graph-databases.md` when choosing Neo4j or FalkorDB or writing Cypher (parameters, read-only access, LIMIT).

## 5. LightRAG and Microsoft GraphRAG
Read `references/lightrag-graphrag.md` when using LightRAG or GraphRAG (indexing, query modes, community summaries).

## 6. Hybrid retrieval and context assembly
1. Seed: embed the query → top-k chunks, entity descriptions and fact embeddings; BM25/keyword for names, ids and rare terms; exact match on known aliases.
2. Expand: 1–2 hops from seed entities, filtered by relation type, validity at the question's time, and degree caps.
3. Fuse lists with reciprocal rank fusion (score = Σ 1/(60 + rank)), then rerank the top 50–100 with a cross-encoder against the question.
4. Assemble: facts with their validity intervals, short entity summaries, the supporting chunks, each tagged with a citation id; dedupe; order by relevance; stay within a token budget.
5. Answer with citations; say when the graph has no support. For "current state" questions filter `invalid_at IS NULL` (or its equivalent); for historical ones pass the date.

## 7. Updates and maintenance
- Incremental ingest keyed by document content hash: skip unchanged docs, re-extract changed ones, and delete facts whose only provenance was the old version (reference-count provenance).
- Contradictions: temporal graphs invalidate with timestamps; static graphs flag conflicts for review — never silently overwrite.
- Decay: rank by recency or last confirmation; expire facts with TTLs where the domain demands (prices, statuses).
- Periodic jobs: re-run entity resolution with new aliases, recompute communities/reports (GraphRAG `update`, Graphiti `build_communities`), remove orphans, check constraint violations, migrate the schema with versioned scripts.
- Keep an ingest log per document (hash, model, prompt version, counts, failures) to reproduce or roll back a batch.

## 8. Evaluation
- Labeled set of 50–200 real questions with gold answers and gold supporting facts/passages, stratified by type (single-hop, multi-hop, temporal, global). Freeze it before tuning.
- Retrieval: recall@k and precision@k of gold supporting facts/chunks, per stratum; compare graph vs hybrid baseline vs combined on the same questions (paired).
- Answers: correctness against gold, faithfulness (every claim supported by retrieved context), citation accuracy; LLM-as-judge with rubric and position-swapped pairwise comparison for global questions (comprehensiveness, diversity) — calibrate on a human-labeled subset (`llm-evals`).
- Extraction quality: precision/recall of entities and relations on 20–50 hand-annotated chunks; duplicate-entity rate after resolution; provenance coverage (should be 100%).
- Cost and latency: ingest tokens and $ per 1k documents, query p50/p95, tokens per answer.

## 9. Cost control
Small non-thinking extraction model; Batch API or local models for bulk extraction; cache every LLM call keyed by (model, prompt version, chunk hash); larger chunks mean fewer calls but lower relation recall — measure; skip boilerplate and near-duplicate docs before extraction (`dataset-curation`); GraphRAG `--method fast` or LightRAG for cheaper indexing; global search scales with the number of community reports — use dynamic selection or a coarser level.

## 10. Running locally
Graph DB in Docker (§4); LLM and embeddings from a local OpenAI-compatible server (`local-llm-serving`: oMLX and llama-server also serve `/v1/embeddings`; `llama-server --embedding` with an embedding GGUF); on the Mac, MLX embedding models through oMLX or `mlx-embeddings`. Keep extraction concurrency at what the server sustains; confirm the embedding dimension matches the index before bulk loads. Long-lived database containers (pinned digests, volumes, backups) → `self-hosting-ops`.

## 11. Pitfalls

| Pitfall | Signature | Fix |
|---|---|---|
| Entity explosion | many near-identical nodes, low degree | normalization + resolution pass, alias lists |
| Hallucinated relations | facts with no matching quote | quote validation, extraction precision audit |
| Supernodes | every query returns the same hubs | degree caps, relation-type filters, drop generic entities |
| Stale facts | answers cite outdated states | temporal edges, TTLs, validity filters |
| Cypher injection | query errors or odd writes from entity text | parameters, allowlisted labels, read-only execution |
| Embedding model swap | recall collapses after an upgrade | re-embed all vectors; record model and dimension |
| Tenant leakage | results from another user/project | `group_id`/partition filter on every query, tested |
| "Works on demos" | no labeled set | §8 before and after every change |

## Verify
Labeled-set retrieval and answer metrics beat the hybrid baseline where the graph was meant to help (report CIs); a random sample of 30 edges each has a quote in its source chunk; duplicate-entity rate below the agreed threshold; a re-ingested unchanged document creates no new nodes; a contradicting document invalidates (not deletes) the old fact; every query path is parameterized and tenant-filtered; costs extrapolated from the sample matched the full run within 20%.

## Deliverables
Schema (versioned), pipeline code and config (models, prompts, chunking), ingest log, eval report (`| system | stratum | recall@k | precision@k | answer correct | faithful | n | p95 latency | cost/query |`), cost sheet (ingest and per query), and a runbook (Docker commands, backups, maintenance jobs).
