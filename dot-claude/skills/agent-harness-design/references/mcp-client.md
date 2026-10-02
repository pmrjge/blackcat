# MCP client

Part of `agent-harness-design`.

## 8. MCP client
- Two protocol generations. The current revision (2026-07-28) is stateless: no `initialize` handshake; each request carries protocol version and client capabilities in `_meta`; `server/discover` advertises versions and capabilities; `subscriptions/listen` carries list-changed notifications; multi-round-trip requests (`resultType: "input_required"`) replace server-initiated sampling/elicitation; Streamable HTTP has no sessions or stream resumption. Servers on 2025-11-25 or earlier use `initialize` → `notifications/initialized` → `tools/list` → `tools/call`, with `Mcp-Session-Id` on HTTP. Use an SDK that negotiates both: Python `mcp` 2.x `async with Client(url_or_StdioServerParameters) as c: await c.list_tools(); await c.call_tool(name, args)` (1.x names differed — check the installed version).
- Lifecycle: stdio servers are child processes — start lazily, health-check, restart with backoff, kill the process group on shutdown, capture stderr for logs. Remote servers: per-request timeouts, OAuth per the spec, re-issue interrupted requests.
- Discovery: paginate `tools/list`, cache for `ttlMs` when given, namespace as `mcp__<server>__<tool>`, filter through the allowlist, map `inputSchema` into the model's tool format, pass annotations (read-only/destructive hints) to the permission layer as untrusted hints.
- Calls: timeout and cancellation, progress to the UI, `content` plus `structuredContent`, `isError` → `is_error`, truncate large results, treat every result as untrusted data (§11). With many servers, defer schemas behind tool search.
