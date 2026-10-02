# Streaming UX, cost and latency, observability

Part of `agent-harness-design`.

## 9. Streaming UX
Stream text deltas; show each tool call when it starts (name, summarized args) and ends (status, duration); render approvals inline with the exact action. Cancellation stops the model stream and tool processes and still leaves a valid transcript (every `tool_use` gets a `tool_result`, e.g. "cancelled by user"). Send keep-alives during long operations; rebuild UI state from the event log; show tokens, cost and elapsed time.

## 10. Cost and latency
- Cache stable prefixes (§5); in fan-outs start one worker first so siblings read its cached prefix.
- Tier models and effort (§7); cap `max_tokens` per step; cap tool output; do not re-read unchanged files.
- Message Batches API for offline bulk work (evals, backfills).
- Measure per step and per task: input, cache-write, cache-read and output tokens; p50/p95 latency; cost per successful task — the number to optimize.

## 13. Observability
- One trace per task: spans for agent invocations, model calls and tool calls. OpenTelemetry GenAI conventions (status: development): `gen_ai.operation.name` (`invoke_agent`, `chat`, `execute_tool`), `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens`, `gen_ai.conversation.id`, `gen_ai.agent.name`, `gen_ai.tool.name`, `gen_ai.tool.call.id`.
- Log request ids, stop reasons, tool args (redacted), result sizes, errors, permission decisions, compaction events. Content logging is opt-in, redacted and retention-limited.
- Token/cost ledger per agent and per task, with alerts on budget burn rate.
