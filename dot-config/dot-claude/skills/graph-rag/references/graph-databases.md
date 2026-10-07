# Graph databases and safe Cypher

Part of `graph-rag`.

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
