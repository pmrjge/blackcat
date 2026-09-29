---
name: agent-harness-design
description: Load before designing or building an agent runtime or agentic app — agent loop, stop conditions, tool schemas, sandboxes, compaction, memory, multi-agent orchestration, evals.
---
# Agent harness design

## Scope
The runtime around a model: loop, tools, permissions, context, memory, multi-agent coordination, MCP client, streaming, cost, evaluation, observability. Neighbours: `rag-agents` (retrieval pipelines), `mcp-server-craft` (building MCP servers), the built-in `claude-api` skill (API parameters and model facts), `graph-rag` (graph-backed memory), `prompt-and-brief-design` (system prompts, tool descriptions), `secure-coding` (prompt injection, sandbox escapes, secrets), `llm-evals` (statistics of eval results), `claude-code-extensions` (when the harness is Claude Code itself). Claude API names below come from platform.claude.com (September 2026). Tool versions and beta headers are dated identifiers: re-check them in the docs before shipping.

## 1. Build or reuse

| Need | Use |
|---|---|
| Coding/ops agent with file edits, shell, permissions, hooks, subagents, MCP and compaction built in | Claude Agent SDK — Claude Code's harness as a library: `claude-agent-sdk` (Python), `@anthropic-ai/claude-agent-sdk` (TypeScript) |
| Full control of every request, custom tools, non-coding domain | Messages API (`anthropic` SDK) plus your own loop |
| Local or mixed providers | Your loop over OpenAI-compatible Chat Completions; tool-call parsing depends on the server (`local-llm-serving`) |

Agent SDK (Python 0.2.x): `query(prompt=..., options=...)` streams one task; `ClaudeSDKClient` keeps an interactive session. `ClaudeAgentOptions` fields include `allowed_tools`, `disallowed_tools`, `permission_mode` (`default`, `acceptEdits`, `plan`, `bypassPermissions`, `dontAsk`, `auto`), `can_use_tool` (async approval callback), `hooks` (`{event: [HookMatcher(...)]}`), `mcp_servers`, `agents` (`AgentDefinition` subagents), `max_turns`, `max_budget_usd`, `effort`, `sandbox`, `setting_sources`, `cwd`, `env` (merged over the inherited environment in Python; the TypeScript `env` replaces it). In-process tools: `@tool` + `create_sdk_mcp_server`.

## 2. The loop
```python
messages = [{"role": "user", "content": task}]
for step in range(MAX_STEPS):
    r = client.messages.create(model=MODEL, system=SYSTEM, tools=TOOLS, messages=messages, max_tokens=MAX_OUT)
    ledger.add(step, r.usage)
    messages.append({"role": "assistant", "content": r.content})
    if r.stop_reason == "tool_use":
        calls = [b for b in r.content if b.type == "tool_use"]
        messages.append({"role": "user", "content": run_tools(calls)})   # one tool_result per id, results first
    elif r.stop_reason in ("max_tokens", "model_context_window_exceeded"):
        compact_or_continue(messages)
    elif r.stop_reason == "pause_turn":     # a server-tool loop hit its iteration limit: send it back as is
        continue
    elif r.stop_reason == "refusal":
        return handle_refusal(r)            # read stop_details; fallback model if policy allows
    else:                                   # end_turn / stop_sequence
        if done_check(): return finish()    # external predicate, not the model's word
        messages.append({"role": "user", "content": "The check failed: <evidence>. Continue."})
    if budget.exceeded() or no_progress(messages): return stop_with_report()
```
- `tool_result` blocks go in the user turn right after the `tool_use` turn, before any text; every `tool_use_id` is answered exactly once, failures with `"is_error": true` and an actionable message.
- Stop conditions, all enforced by the harness: external done-check (tests, schema, goal predicate), step cap, token/cost cap, wall-clock cap, no-progress detector (same tool + args repeated, no state change), user interrupt.
- Retries: 429/overload/5xx with exponential backoff and jitter; tool errors go back to the model; side-effecting tools take idempotency keys so a retried step cannot act twice.

## 3. Tools
- Few, orthogonal, namespaced (`github_list_prs`); consolidate near-duplicates behind an `action` parameter. Descriptions of 3–4+ sentences: what it does, when to use it and when not, each parameter, limits. `input_examples` for complex inputs.
- JSON Schema with enums, required fields, bounded strings/arrays; `strict: true` guarantees schema-valid inputs; still validate server-side (paths, ranges, permissions).
- Results: high-signal fields, stable ids, units, provenance; paginate; cap size and return a handle to the full output (§5). Errors say what failed and what to try next ("no such file; closest: src/io.py").
- Classify every tool: read-only / reversible write / irreversible / externally visible. The class drives permissions (§4), retries and parallelism.
- `tool_choice`: `auto` (default), `any`/`tool` force a call and suppress preamble text, `none` disables; changing it invalidates cached message blocks. Parallel calls are fine for independent read-only tools; `disable_parallel_tool_use` where order matters.
- Large catalogs: tool search (`tool_search_tool_regex_20251119` / `tool_search_tool_bm25_20251119` with `defer_loading` on tools) instead of loading every schema; programmatic tool calling (code execution `code_execution_20260120` or later) keeps bulky intermediate results out of context.

## 4. Permissions and sandbox
1. Deny by default; allowlist tools and MCP servers per agent role.
2. Argument rules: paths inside the workspace (resolve symlinks, reject `..`), command allow/deny lists, network domain allowlist, rate limits.
3. Confirmation for irreversible or externally visible actions (delete, force-push, send, pay, publish), showing the exact action; a dry-run mode where possible.
4. Isolation: a git worktree per writing agent (merge by patch/PR); containers or VMs for untrusted code (workspace-only mounts, no Docker socket, read-only root, dropped capabilities, egress policy); OS sandboxes for shell tools (Claude Code's sandbox uses Seatbelt on macOS and bubblewrap on Linux; `@anthropic-ai/sandbox-runtime`, a beta research preview, wraps a whole process — tools, hooks, MCP servers — in the same isolation, network denied by default).
5. Secrets never enter prompts or tool results: the tool runtime injects scoped, short-lived credentials; logs are redacted.
6. Budgets and a kill switch that stop every agent of a task.

## 5. Context management
- Budget the window explicitly: system + tool schemas + memory + working set + headroom for output; count with `/v1/messages/count_tokens` before sending large requests.
- Tool output: cap each result (head + tail + counts), write the full output to an artifact store, return path/id + summary, and give the agent `read_range`/`grep` tools over stored outputs (index them) instead of re-dumping.
- Retrieve instead of dumping: list → search → read ranges; relevant chunks only (`rag-agents`).
- Compaction: server-side on demand (beta `compact-2026-09-04`, top-level `compaction` parameter) or at a token threshold (beta `compact-2026-01-12`, `context_management.edits: [{"type": "compact_20260112"}]`), or your own summarizer. Keep recent turns verbatim; the summary must retain goal, constraints, decisions with reasons, open TODOs, file paths, ids, last errors. Re-inject the plan/state file afterwards.
- Context editing (beta `context-management-2025-06-27`): `clear_tool_uses_20250919` drops old tool results past a threshold; `clear_thinking_20251015` manages thinking blocks. Cleared content invalidates the cache from that point.
- Long tasks: persist state in files (progress notes, structured test status, git history) so a fresh context can resume; tell the model whether its context will be compacted.
- Caching layout, stable → volatile: tools, system, long-lived context, conversation. `cache_control: {"type": "ephemeral"}` (optionally `"ttl": "1h"`) on block boundaries, at most 4 breakpoints, or top-level automatic caching; lookback is 20 blocks per breakpoint; any edit before a breakpoint invalidates it.

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

## 7. Multi-agent orchestration

| Pattern | Fits | Main risk |
|---|---|---|
| Single agent + tools | most tasks — the default | context growth |
| Router → specialists | heterogeneous requests; cheap classifier picks agent/model | misroutes: needs a fallback |
| Orchestrator → workers (fan-out/fan-in) | parallel subtasks: search, per-file analysis | duplicated work, N× cost, inconsistent outputs |
| Pipeline (plan → execute → verify) | staged work with checkable hand-offs | error propagation |
| Evaluator–optimizer | measurable quality bar (tests, rubric) | endless loops without a cap |

- Spawn only for parallelism or context isolation; strong models tend to over-delegate, so state when direct work is preferred.
- Harness-enforced limits: max depth (1–2), max fan-out per node, global concurrency, per-agent step/token budgets, a task-level budget.
- Task spec for a worker: objective, inputs as paths/ids (not pasted blobs), constraints, what siblings own (do not touch), done-criteria, output schema, budget.
- Hand-back schema: `status` (done/partial/failed/blocked), 3–10 line summary, artifacts (paths/ids), verification performed with evidence, open issues, tokens/cost used. Large outputs go to files.
- Avoid duplicated work: a task ledger (id, owner, state; claim before starting), dedup keys for identical requests, a shared cache of fetched documents and tool results, disjoint ownership (files, worktrees), a single agent reconciling conflicts.
- Tiering: cheap, low-effort models for search/extraction workers; the strongest model for planning, synthesis and final verification. `output_config.effort` (`low`…`max`; availability and default vary by model) is the per-request lever on Claude.
- Communicate through the coordinator or an append-only shared store, not free-form agent-to-agent chat.

## 8. MCP client
- Two protocol generations. The current revision (2026-07-28) is stateless: no `initialize` handshake; each request carries protocol version and client capabilities in `_meta`; `server/discover` advertises versions and capabilities; `subscriptions/listen` carries list-changed notifications; multi-round-trip requests (`resultType: "input_required"`) replace server-initiated sampling/elicitation; Streamable HTTP has no sessions or stream resumption. Servers on 2025-11-25 or earlier use `initialize` → `notifications/initialized` → `tools/list` → `tools/call`, with `Mcp-Session-Id` on HTTP. Use an SDK that negotiates both: Python `mcp` 2.x `async with Client(url_or_StdioServerParameters) as c: await c.list_tools(); await c.call_tool(name, args)` (1.x names differed — check the installed version).
- Lifecycle: stdio servers are child processes — start lazily, health-check, restart with backoff, kill the process group on shutdown, capture stderr for logs. Remote servers: per-request timeouts, OAuth per the spec, re-issue interrupted requests.
- Discovery: paginate `tools/list`, cache for `ttlMs` when given, namespace as `mcp__<server>__<tool>`, filter through the allowlist, map `inputSchema` into the model's tool format, pass annotations (read-only/destructive hints) to the permission layer as untrusted hints.
- Calls: timeout and cancellation, progress to the UI, `content` plus `structuredContent`, `isError` → `is_error`, truncate large results, treat every result as untrusted data (§11). With many servers, defer schemas behind tool search.

## 9. Streaming UX
Stream text deltas; show each tool call when it starts (name, summarized args) and ends (status, duration); render approvals inline with the exact action. Cancellation stops the model stream and tool processes and still leaves a valid transcript (every `tool_use` gets a `tool_result`, e.g. "cancelled by user"). Send keep-alives during long operations; rebuild UI state from the event log; show tokens, cost and elapsed time.

## 10. Cost and latency
- Cache stable prefixes (§5); in fan-outs start one worker first so siblings read its cached prefix.
- Tier models and effort (§7); cap `max_tokens` per step; cap tool output; do not re-read unchanged files.
- Message Batches API for offline bulk work (evals, backfills).
- Measure per step and per task: input, cache-write, cache-read and output tokens; p50/p95 latency; cost per successful task — the number to optimize.

## 11. Failure modes

| Failure | Signature | Mitigation |
|---|---|---|
| Loops | same tool + args repeated, no state change | detector, step cap, feedback naming the repeat |
| Premature "done" | `end_turn` while criteria unmet | external done-check, verification step |
| Tool misuse | schema errors, wrong tool chosen | better descriptions, `strict`, examples, fewer tools |
| Fabricated results | claims absent from the trace | require citing tool-call ids; spot-verify |
| Context rot | quality falls late in long runs | compaction, state files, fresh context |
| Prompt injection via tool output, documents, web pages or MCP results | agent follows instructions found in data | data/instruction separation, plan before reading untrusted input, least privilege, confirmation for side effects, no secrets in context — `secure-coding` |
| Runaway cost | token rate spikes | budgets, alerts, kill switch |
| Duplicated or conflicting edits | two agents change the same file | ledger, ownership, worktrees |
| Stale or poisoned memory | wrong facts persist | provenance, validity intervals, review |

## 12. Evaluation
- Task suite of 30–200 realistic tasks with programmatic success checks (tests pass, diff matches, answer key), plus adversarial (planted injections), long-horizon and tool-failure cases.
- Several trials per task: success rate with a CI, and pass^k (all k trials succeed) for reliability.
- Trajectory review: sample traces, label failure causes with the table above; track tool-error rate, steps, tokens, cost and wall time per task.
- Regression on recorded runs: record model responses and tool I/O; replay them to test harness changes without model variance; rerun the live suite for model or prompt changes and compare with paired statistics (`llm-evals`).
- LLM-as-judge only with a rubric and calibration against human labels (`llm-evals`).

## 13. Observability
- One trace per task: spans for agent invocations, model calls and tool calls. OpenTelemetry GenAI conventions (status: development): `gen_ai.operation.name` (`invoke_agent`, `chat`, `execute_tool`), `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens`, `gen_ai.conversation.id`, `gen_ai.agent.name`, `gen_ai.tool.name`, `gen_ai.tool.call.id`.
- Log request ids, stop reasons, tool args (redacted), result sizes, errors, permission decisions, compaction events. Content logging is opt-in, redacted and retention-limited.
- Token/cost ledger per agent and per task, with alerts on budget burn rate.

## 14. Architecture document template
```
# <name> — agent architecture
1. Purpose, users, tasks in/out of scope; success metrics (task success, cost/task, p95 latency)
2. Models: role → model, effort, fallback
3. Loop: stop conditions, budgets, retry policy
4. Tools: name | side-effect class | schema | timeout | output cap | owner
5. Permissions and sandbox: tiers, confirmations, isolation, secrets handling
6. Context: cache layout, compaction/editing policy, tool-output handling
7. Memory: types, stores, write/read policy, retention, user controls
8. Multi-agent: topology, limits, task-spec and hand-back schemas, dedup
9. Integrations: MCP servers (protocol revision, transport, auth), external APIs
10. UX: streaming, approvals, cancellation
11. Observability: traces, metrics, logs, alerts
12. Evaluation: suites, gates, regression process
13. Threat model: injection surfaces, exfiltration paths, mitigations (secure-coding)
14. Risks, open questions, rollout plan
```

## Verify
Replay suite green; live suite success ≥ baseline with CIs; cost per task within budget; fault injection trips the loop detector, budget caps and kill switch; forbidden actions are blocked by the permission layer (not by the prompt); planted injections in tool outputs are ignored; cancellation leaves a valid transcript; traces show token accounting that sums to the provider's usage.

## Deliverables
Architecture document (template above), tool catalog, eval report (`| suite | n tasks | trials | success (95% CI) | pass^k | cost/task | p95 latency |`), representative traces with failure labels, configuration (budgets, limits, permission rules).
