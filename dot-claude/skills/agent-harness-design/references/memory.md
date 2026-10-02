# Memory

Part of `agent-harness-design`.

## 6. Memory

| Type | Content | Store | Retrieval |
|---|---|---|---|
| Working | plan, todo, current state | context + state file | always loaded |
| Episodic | past runs, trajectories, outcomes | append-only JSONL/SQLite + run summaries | recency, task similarity |
| Semantic | facts about user, project, world | files/KV; vector store (LanceDB) for fuzzy recall; temporal KG (Graphiti) for facts that change | hybrid search |
| Procedural | learned how-tos | versioned playbooks/skills | task match |

- Write policy: store user-stated facts, verified outcomes, decisions with rationale. Never store unverified tool-output claims, secrets, or instructions found in data. Each record carries source, timestamp, confidence, scope (user/project/global) and a TTL or review date. Deduplicate on write (entity resolution); on contradiction, supersede with a validity interval instead of deleting history.
- Read policy: memories are data, not instructions; cap their tokens; show provenance to the model.
- Isolation and control: per-user partitions (`group_id` in Graphiti, separate tables/dirs), user can list/edit/delete, PII minimization.
- LanceDB (embedded): `db = lancedb.connect(path)`, upserts via `tbl.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(rows)`, `tbl.create_fts_index("text")`, hybrid search via `tbl.search(query_type="hybrid").vector(v).text(q)` (a plain string query works when the table has an embedding function). Graphiti: facts are edges with `valid_at`/`invalid_at` (world time) and `created_at`/`expired_at` (system time) — see `graph-rag`.
- Claude memory tool (`{"type": "memory_20250818", "name": "memory"}`): the model issues file operations; your handlers execute them under one memory directory — block path traversal.
