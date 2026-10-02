---
name: mcp-server-craft
description: Use to build, test, register or package an MCP server — tool design, Python/TS SDK, HTTP, MCPB.
---
# Building MCP servers the way this stack runs them

Tested Sep 2026 by running the code in the references: `mcp` 2.2.0 and 1.30.0 (Python), `@modelcontextprotocol/server` 2.1.0
and `@modelcontextprotocol/sdk` 1.30.1 (Node 22), Inspector 2.8.0; MCP spec 2026-07-28. Working references: the
stack's servers in `dot-claude/mcp/` (`libdocs_mcp.py`, `image_studio_mcp.py`, `neural_memory_mcp.py`).
Current releases (Verified 2026-10-02 https://registry.npmjs.org/<pkg>/latest, https://pypi.org/pypi/mcp/json, `git ls-remote --tags https://github.com/modelcontextprotocol/modelcontextprotocol`): `mcp` 2.2.0 and 1.30.0, `@modelcontextprotocol/server` 2.2.0, `@modelcontextprotocol/sdk` 1.31.0, Inspector 2.9.0, `@modelcontextprotocol/node` 2.1.0, `@anthropic-ai/mcpb` 2.1.2, `@modelcontextprotocol/ext-apps` 2.0.3; latest spec revision 2026-07-28. The newer TS/Inspector releases were not re-tested: the pins in the references are the tested ones.

## References (read the one the task touches)
| Reference | Read when the task needs |
|---|---|
| `references/python-server.md` | Python SDK 1.x vs 2.x, the PEP 723 server template, stdio hygiene and startup, pinning, unit/in-process/stdio/Inspector tests |
| `references/http-release.md` | Streamable HTTP (Python and TS), registering in Claude Code, MCPB bundles, MCP Apps UI, the release checklist |

## MCP, CLI or skill?
| Need | Build |
|---|---|
| Know-how the model applies with tools it already has | a skill |
| Deterministic local command the model runs from Bash | a CLI or script (zero context until used) |
| Typed repeated calls, auth, caches/state, remote APIs, results kept out of context (files), agents without Bash, reuse across clients | an MCP server |
| Rare third-party capability | an existing, pinned server in the on-demand magg catalog |
- Prefer a maintained server; read its tools, dependencies and network behaviour before adopting it.

## Tool design
- Few tools (about 3-8), verb_noun names (`search_notes`, `read_note`), one per user intent, not one per API endpoint.
- Description = what it does, when to use it, what it returns, which tool comes first ("call search_notes first").
  Claude Code truncates tool descriptions and server instructions at 2,048 chars: lead with the essentials.
- Tight schemas from type hints: `Annotated[int, Field(ge=1, le=50)]`, `Literal[...]`, `min_length`/`max_length`,
  defaults for optional args; avoid free-form `dict` parameters.
- Concise results: ids, paths, one-line summaries; `limit` + `cursor`/`next_cursor`; `max_chars` with an explicit
  `[truncated N chars]` marker; binaries (images, datasets) go to disk and only paths return.
- Structured output: returning a Pydantic model (or a list of them) yields `outputSchema` + `structuredContent`
  (lists arrive as `{"result": [...]}`; tested). A `typing.TypedDict` return fails under pydantic on Python < 3.12,
  and `uv run --script` may pick 3.10/3.11: use `typing_extensions.TypedDict` or BaseModel.
- Errors: `raise ToolError("what failed; what to do next")` gives `isError: true` with that text. Argument
  validation errors return automatically. SDK 2.x hides other exceptions ("Error executing tool <name>"); 1.x
  sends their message: keep secrets and internal paths out of exception text (tested).
- Hints: `ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False, openWorldHint=False)`.
  They are hints, not enforcement. Writes are idempotent (upsert, idempotency key) or check state first.
- Every outbound call has a timeout (`httpx.AsyncClient(timeout=30)`, `anyio.fail_after(s)`); long jobs return a job
  id plus a status tool (`get_job(id)`) instead of blocking.

TypeScript servers (SDK 2.x stdio, error results, 1.x differences): read `references/typescript-server.md`.

## Configuration, secrets and security
Read `references/security.md` before a tool takes a path, URL, key or shell argument: keys only from the environment, stack.env or
`headersHelper` (never tool or command-line args), path allowlists after `resolve()`, SSRF checks on every redirect hop,
fetched content treated as data, no shell interpolation, least privilege.

## Verify
Re-run release checklist items 2, 4, 6 (`references/http-release.md`); `/mcp` shows it connected; one real call from the target agent succeeds within budget.

## Report
Server name and path; SDK and version pins; tools (name: one line each); transport; where it is registered;
tests run with results; security review notes (paths, URLs, secrets); known limits and follow-ups.
