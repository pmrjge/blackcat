---
name: mcp-http-release
description: Load to serve an MCP server over HTTP, register it in Claude Code, or ship it — MCPB, MCP Apps.
---
# MCP over HTTP, registration and release

Part of `mcp-server-craft` (tool design, security reference). Server code: `mcp-python-server`, `mcp-ts-server`.

## Streamable HTTP (remote or shared servers)
- 2.x: `mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, stateless_http=True, json_response=True)`
  serves `http://127.0.0.1:8765/mcp` (tested with `Client("http://127.0.0.1:8765/mcp")`). 1.x: the same options on
  `FastMCP(...)`, then `mcp.run(transport="streamable-http")`.
- Bound to localhost, the Python SDK turns on DNS-rebinding protection: a foreign `Host` gets 421, a foreign `Origin`
  403 (tested). Other binds: `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`
  from `mcp.server.transport_security`.
- Never an unauthenticated endpoint on a routable interface: keep it on localhost behind `tailscale serve` or a TLS
  proxy, and require a bearer token (SDK `token_verifier`/OAuth or your own middleware). MCP 2026-07-28 is stateless:
  cross-request state lives behind random handles bound to the authenticated user, never a guessable id.
- A plain GET on `/mcp` opens an SSE stream and hangs; probe with POST and `Accept: application/json, text/event-stream`.
- TypeScript 2.x HTTP: `createMcpHandler(() => makeServer())` from `@modelcontextprotocol/server` (the factory must return a
  fresh `McpServer` per request; a shared instance stalled concurrent requests in testing) + `toNodeHandler` from `@modelcontextprotocol/node`; that
  handler checks neither Host nor Origin, so mount `localhostHostValidation()` and `localhostOriginValidation()`
  in front (the SDK's serving guide).

## Registering in Claude Code (this stack)
| Server | Where | Effect |
|---|---|---|
| Local stdio for one agent | inline `mcpServers` in that agent's frontmatter + `mcp__<name>` in its `tools:` | starts with the agent, stops when it ends |
| Remote HTTP for several agents | user scope via `claude mcp add-json -s user`, key through `headersHelper`; `mcp__<name>` in each agent's `tools:` | connects on first use; schemas deferred by tool search |
| Rarely needed | disabled entry in `dot-claude/magg/config.json` | nothing loaded until mounted |
```yaml
mcpServers:                        # agent frontmatter; the installer renders the absolute uv path
  - notes:
      type: stdio
      command: "/absolute/path/to/uv"
      args: ["run", "--quiet", "--script", "__CLAUDE_DIR__/mcp/notes_mcp.py"]
```
```bash
claude mcp add-json -s user notes '{"type":"http","url":"https://notes.<tailnet>.ts.net/mcp","headersHelper":"\"/absolute/python3\" \"__CLAUDE_DIR__/bin/mcp-headers\""}'
```
- Tool names and every server's `instructions` load into each session or agent that has the server, even with
  tool search deferring the schemas: 1-3 sentences (what it is for, when to search for its tools). The stack cut
  neural-memory's ~560-token instructions to a few lines for this reason.
- Entries accept `timeout` (ms, hard limit per tool call) and `alwaysLoad`; `CLAUDE_PROJECT_DIR` is set in a stdio
  server's environment. Claude Code negotiates MCP 2026-07-28 with stdio servers only when
  `MCP_PROTOCOL_NEGOTIATION=auto`; SDK 2.x servers handle both handshakes.
- Output: warning above 10,000 tokens; `MAX_MCP_OUTPUT_TOKENS` (25000 here) caps it; a larger non-image result
  is saved to a file and replaced by its path. Aim for 2-5k tokens per call.
- Check: `/mcp` in a session, `claude mcp list`, `claude mcp get <name>`; `uv run tests/lint_agents.py` in the repo.

## Distribution outside this stack (checked 2026-09-29)
- **Remote first**: a server that only calls cloud APIs ships as a Streamable HTTP endpoint (see above) with OAuth or authless access; a static bearer token suits private deployments only; directory listing has its own requirements (claude.com/docs/connectors, unverified here).
- **MCPB bundles** (`.mcpb`, formerly DXT; spec and CLI at github.com/modelcontextprotocol/mcpb, `@anthropic-ai/mcpb` 2.1.x): a zip with `manifest.json` + server code that Claude Desktop installs in one click. Use it only when the server must run on the user's machine (local files, desktop apps, localhost services).
  - `mcpb init` drafts the manifest, `mcpb pack` validates and zips it. Required fields are `manifest_version`, `name`, `version`, `description`, `author` and `server`.
  - `server.type` is `node`, `python`, `binary` or **`uv`** (manifest 0.4+). With `uv`, the host installs the dependencies from `pyproject.toml` with uv, which fits this stack's Python servers and keeps the bundle around 100 KB.
  - `server.mcp_config` sets the command, args (`${__dirname}` for bundle paths) and `env` (`${user_config.<key>}`, with no auto-prefix).
  - `user_config` entries can be `sensitive: true` (stored in the OS keychain) or `type: "directory"` (a folder picker).
  - There is no sandbox: the path/URL guards (`references/security.md` in `mcp-server-craft`) are the only protection, so prefer the client's `roots` over a hard-coded root.
- **MCP Apps** (interactive UI, extension spec 2026-01-26 at github.com/modelcontextprotocol/ext-apps, npm `@modelcontextprotocol/ext-apps` 2.0.x): a tool declares `_meta.ui.resourceUri: "ui://…"`, a separately registered resource serves the HTML (`mimeType: "text/html;profile=mcp-app"`), and the host renders it in a sandboxed iframe and passes the tool result to it; the UI can call tools back through the host. CSP defaults to block-all (declare `connectDomains`/`resourceDomains`); `_meta.ui.visibility: ["app"]` hides widget-only helper tools from the model. Use a widget only for large pickers, visual previews, charts/maps or live progress; confirmations and flat forms use spec-native **elicitation** instead. Test in claude.ai as a custom connector (local dev through a tunnel).

## Release checklist
1. Tool set small; names, descriptions and schemas reviewed; errors actionable; pagination and truncation present.
2. Initialize probe starts with `{"jsonrpc"`; logs only on stderr; warm start within seconds; dependencies prefetched.
3. Secrets only from env, stack.env or headersHelper; none in args, results, errors or logs.
4. Path and URL guards unit-tested (traversal, symlink escape, private and encoded IPs, redirect to a private IP, oversize).
5. Versions pinned: SDK major bounded plus a lock or `exclude-newer`; third-party servers exact.
6. Unit, in-process and stdio tests pass; Inspector `--strict` clean.
7. Registered per the table with `mcp__<name>` in `tools:`; instructions within 3 sentences; lint passes.
8. For a stack server: README server table and the installer's prefetch list updated.

## Verify
- HTTP: a POST probe with `Accept: application/json, text/event-stream` answers; a foreign `Host`/`Origin` is refused; no unauthenticated routable endpoint.
- `claude mcp get <name>` and `/mcp` show the server connected; `uv run tests/lint_agents.py` passes for stack servers.
