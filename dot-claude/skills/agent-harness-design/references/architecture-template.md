# Agent harness design: architecture template

Read when writing the harness architecture document (moved from `agent-harness-design` SKILL.md).

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
