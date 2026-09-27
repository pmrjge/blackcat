---
name: graph-rag
description: Use when retrieval or agent memory needs relations, multi-hop answers, facts that change over time or corpus-wide summaries — LLM entity/relation extraction with provenance and entity resolution, temporal graphs (Graphiti), FalkorDB/Neo4j with parameterized Cypher, LightRAG and Microsoft GraphRAG, hybrid vector+keyword+graph retrieval, updates, evaluation, cost and local setups.
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

## 3. Temporal knowledge graphs (Graphiti)
- Episodes are the unit of ingestion (`EpisodeType.message` "speaker: text", `.text`, `.json`) with a `reference_time`. Graphiti extracts entity nodes and entity edges; an edge is a fact (`fact`, `name`, `episodes` = provenance) that is bi-temporal: `valid_at`/`invalid_at` say when it held in the world, `created_at`/`expired_at` when the system learned or retired it. A contradicting episode invalidates the old edge instead of deleting it, so point-in-time questions stay answerable (`SearchFilters` on `valid_at`/`invalid_at`/`created_at`/`expired_at`).
- Partition tenants or projects with `group_id`; custom `entity_types`/`edge_types` (Pydantic models) and `edge_type_map` constrain extraction; `custom_extraction_instructions` adds domain rules; sagas chain ordered episodes.
```python
import asyncio
from datetime import datetime, timezone
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.driver.falkordb_driver import FalkorDriver

async def main():
    g = Graphiti(graph_driver=FalkorDriver(host="localhost", port=6379))  # default LLM/embedder: OpenAI
    await g.build_indices_and_constraints()                               # once per database
    await g.add_episode(name="notes-0926", episode_body="Ana moved from team A to team B.",
                        source=EpisodeType.text, source_description="meeting notes",
                        reference_time=datetime(2026, 9, 26, tzinfo=timezone.utc), group_id="proj-x")
    for e in await g.search("Which team is Ana on?", group_ids=["proj-x"], num_results=5):
        print(e.fact, e.valid_at, e.invalid_at)
    await g.close()

asyncio.run(main())
```
- `search()` is hybrid (BM25 + embeddings, RRF; node-distance rerank with `center_node_uuid`); `search_(query, config=...)` takes recipes such as `COMBINED_HYBRID_SEARCH_CROSS_ENCODER` or `NODE_HYBRID_SEARCH_RRF` from `graphiti_core.search.search_config_recipes`. Also `add_episode_bulk` (batch ingestion; in 0.30 it also runs date extraction and edge invalidation, which older releases skipped — read the docstring of the installed version), `remove_episode`, `build_communities`.
- Local models: `OpenAIGenericClient(config=LLMConfig(api_key=..., model=..., small_model=..., base_url="http://127.0.0.1:8080/v1"))`, `OpenAIEmbedder(config=OpenAIEmbedderConfig(api_key=..., embedding_model=..., embedding_dim=..., base_url=...))`, reranker `OpenAIRerankerClient(client=llm_client, config=llm_config)`. Extraction depends on structured output: use the most capable model you can run; switch `structured_output_mode` to `"json_object"` when a server accepts `json_schema` without enforcing it; keep `SEMAPHORE_LIMIT` (default 20 concurrent operations in the 0.30 code, though its README says 10) low for local servers. Telemetry is opt-out: `GRAPHITI_TELEMETRY_ENABLED=false`.

## 4. Graph databases and safe Cypher

| | FalkorDB | Neo4j |
|---|---|---|
| Run locally | `docker run -p 6379:6379 -p 3000:3000 -v falkordb_data:/data -e REDIS_ARGS="--requirepass $PW --appendonly yes" falkordb/falkordb:<tag>` (UI on 3000; `falkordb/falkordb-server` = no UI) | `docker run -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/$PW -v neo4j_data:/data neo4j:<tag>` (password ≥ 8 chars; APOC via `NEO4J_PLUGINS='["apoc"]'`) |
| Python | `FalkorDB(host=, port=, password=).select_graph("kg")`; `.query(q, params)`, `.ro_query(q, params)` | `GraphDatabase.driver(uri, auth=...)`; `driver.execute_query(q, params, routing_=RoutingControl.READ, database_=...)` |
| Vector index | `CREATE VECTOR INDEX FOR (c:Chunk) ON (c.embedding) OPTIONS {dimension:1024, similarityFunction:'cosine'}`; query `CALL db.idx.vector.queryNodes('Chunk','embedding',10,vecf32($v)) YIELD node, score` | ``CREATE VECTOR INDEX chunk_emb FOR (c:Chunk) ON (c.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}``; ``CALL db.index.vector.queryNodes('chunk_emb', 10, $v) YIELD node, score`` |

Pin image tags; bind ports to 127.0.0.1 (`-p 127.0.0.1:6379:6379`) unless the database must be reachable from elsewhere.
```python
driver.execute_query(
    "MATCH (e:Entity {id: $id})-[r:RELATES]->(n:Entity) WHERE r.invalid_at IS NULL "
    "RETURN n.name AS name, r.fact AS fact LIMIT $k",
    {"id": entity_id, "k": 20}, routing_=RoutingControl.READ, database_="neo4j")
```
- Every value is a parameter (`$id`), never string-formatted — entity names come from documents and LLMs and can carry Cypher.
- Labels, relationship types and property keys cannot be ordinary parameters: validate them against the schema allowlist, then interpolate with backticks.
- LLM-written Cypher (text-to-Cypher): read-only execution (`ro_query`, READ routing, a read-only database user), an `EXPLAIN` pass first (`graph.explain(q)` in FalkorDB), forced `LIMIT`, a query timeout (`timeout=` ms on FalkorDB queries), and preferably a small set of parameterized query templates the model only fills in.
- Traversal hygiene: cap hops (1–2), cap degree per hop (supernodes such as "company" or "user" swamp results), filter by relation type and validity.

## 5. LightRAG and Microsoft GraphRAG
**LightRAG** (`lightrag-hku`): LLM extraction of entities and relations per chunk, stored in KV + vector + graph backends (defaults JSON/NanoVectorDB/NetworkX; Neo4j, Memgraph, PostgreSQL, Mongo, Redis, Milvus, Qdrant, Faiss available). Query modes via `QueryParam(mode=...)`: `local` (entity-centric), `global` (relationship/theme-centric), `hybrid` (both), `naive` (chunk vectors only), `mix` (graph + chunks, the default), `bypass`. Incremental inserts are native.
```python
rag = LightRAG(working_dir="./rag", llm_model_func=llm_fn, embedding_func=embed_fn)
await rag.initialize_storages()                      # forgetting this is the classic failure
await rag.ainsert(texts, ids=doc_ids, file_paths=paths)
answer = await rag.aquery("question", param=QueryParam(mode="mix"))
data = await rag.aquery_data("question", param=QueryParam(mode="mix"))   # retrieval only: for evals
```
`adelete_by_doc_id`, `merge_entities`, `edit_entity`, `export_data` support maintenance; `lightrag-server` adds a Web UI and REST API. Fix the embedding model before indexing: changing it means re-embedding everything.

**Microsoft GraphRAG** (`graphrag` 3.x): text units → LLM entity/relationship (and optional claim) extraction → graph → hierarchical Leiden communities → LLM community reports → embeddings (LanceDB by default); outputs are Parquet tables.
```bash
graphrag init --root ./proj                  # settings.yaml (completion_models / embedding_models, key via ${GRAPHRAG_API_KEY} in .env), prompts/
graphrag prompt-tune --root ./proj           # adapt extraction prompts to the domain
graphrag index --root ./proj --method standard   # or fast: NLP noun-phrase graph + LLM summaries, much cheaper
graphrag update --root ./proj                # incremental
graphrag query "What are the main themes?" --root ./proj --method global --community-level 2
```
Methods: `local` (entities near the query + neighbours, relations, text units, reports), `global` (map-reduce over community reports at a level; default; expensive — `--dynamic-community-selection` prunes irrelevant communities), `drift` (local search primed with community context), `basic` (vector RAG over text units). Models go through a LiteLLM-based layer: `model_provider`, `model`, and `api_base` for OpenAI-compatible local servers. The LLM cache makes re-runs after a crash cheap; keep it.

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
