# Temporal knowledge graphs (Graphiti)

Part of `graph-rag`.

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
