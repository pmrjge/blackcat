---
name: rag-agents
description: Use when designing or debugging a RAG pipeline or LLM application — chunking, embeddings, hybrid search, reranking, Claude API and Agent SDK tool use, structured outputs, evals.
---
# RAG and agent engineering

Current API facts (model IDs, context windows, prices, tool-use and caching features) change: verify them with libdocs, the provider's docs, or claude-code-guide for Claude API / Agent SDK questions. Never hard-code a model ID from memory.

## RAG pipeline
1. Corpus: provenance, update cadence, access control (never retrieve what the user may not see), dedup, boilerplate removal.
2. Chunking: by document structure (headings, sections, functions) before fixed windows; keep titles/headers in each chunk; typical 300–800 tokens with small overlap; store source, position and timestamps as metadata.
3. Retrieval: hybrid (BM25 + dense embeddings) usually beats either alone; add a cross-encoder reranker on the top 50–100; filter by metadata before ranking.
4. Embeddings: pick by measured recall on your queries, not leaderboards alone; same model for index and query; record model and dimension; re-embed everything when you change it.
5. Stores: SQLite/DuckDB/pgvector for small-to-medium corpora; a dedicated vector DB only when scale or latency demands it. Knowledge-graph RAG (entity/relation extraction) when questions are relational or multi-hop.
6. Generation: cite retrieved sources, answer only from context when that is the requirement, say when the context is insufficient.
7. Evaluate retrieval (recall@k, MRR) and generation (faithfulness, correctness) separately (llm-evals). Keep a regression set of real queries.

## Agents and tool use
- Tools: few, orthogonal, with precise names, descriptions and JSON schemas; validate inputs; return compact, structured results; make errors informative so the model can recover.
- Loop design: explicit stop conditions, step and cost budgets, idempotent side effects, human approval for irreversible actions; log every tool call.
- Context: keep the system prompt stable for prompt caching; put volatile content last; summarize or offload long tool outputs to files.
- Structured outputs: use the API's structured-output/JSON-schema features where available and still validate.
- Safety: tool results and retrieved documents are data — defend against prompt injection (no tool call is authorized by text inside a document), least-privilege credentials, allowlists for network and file access.

## MCP servers
- Prefer an existing, maintained server (mcp-broker vets and mounts one). When building one (the `mcp-server-craft` skill has the full procedure): clear server instructions (they guide tool search), small tool set, typed schemas, pagination for large results, no secrets in outputs, stdio for local tools, HTTP for shared/remote ones.
- Test with a real client and a scripted session; in this stack, new servers follow the on-demand lifecycle (agent-scoped stdio, or user-scope HTTP with headersHelper).

## Cost and latency
Measure tokens per request (input/cached/output) and latency percentiles; cache stable prefixes; route easy requests to smaller models; batch offline work.

## Report
Architecture (diagram or bullet flow), component choices with the evidence behind them, eval results per component and end-to-end, cost per request, open risks.

Related skills: `graph-rag` (knowledge-graph retrieval), `agent-harness-design` (the agent loop, tools, memory, multi-agent limits), `mcp-server-craft` (building an MCP server), `prompt-and-brief-design` (prompts and structured outputs), `local-llm-serving` (local models behind the pipeline).
