# Agent harness design: multi agent

Read when designing multi-agent orchestration (roles, handoffs, budgets) (moved from `agent-harness-design` SKILL.md).

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
