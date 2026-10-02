# LightRAG and Microsoft GraphRAG

Part of `graph-rag`.

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
