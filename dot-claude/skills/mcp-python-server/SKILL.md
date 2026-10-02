---
name: mcp-python-server
description: Load to write or test a Python MCP server — SDK 1.x/2.x, PEP 723 template, stdio, pinning, tests.
---
# Python MCP servers (uv, PEP 723)

Part of `mcp-server-craft` (MCP vs CLI vs skill, tool design, security reference). HTTP transport and registration: `mcp-http-release`.

## Python server as a PEP 723 script
| | SDK 1.x (`mcp>=1.10,<2`) | SDK 2.x (`mcp>=2.2,<3`) |
|---|---|---|
| Status | still maintained (1.30.0, Sep 2026); the stack's servers and tests use it | current line since 2026-07-28; implements MCP 2026-07-28 |
| Server import | `from mcp.server.fastmcp import FastMCP, Context` | `from mcp.server.mcpserver import MCPServer, Context` |
| ToolError | `mcp.server.fastmcp.exceptions` | `mcp.server.mcpserver.exceptions` |
| HTTP options | on the constructor (`host`, `port`, `stateless_http`, `json_response`) | on `run(transport="streamable-http", ...)` |
| Client result fields | `isError`, `structuredContent`, `inputSchema` | `is_error`, `structured_content`, `input_schema` (wire JSON unchanged) |
- 2.x servers still serve 1.x clients over stdio (tested with the Python and TypeScript 1.30 clients). Decorators
  (`@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`) are unchanged. For 1.x, change the pin, the two imports and
  `MCPServer(` to `FastMCP(`; everything else below is identical (tested).
```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.2,<3"]
# ///
"""notes: search and read Markdown notes under NOTES_DIR."""
from __future__ import annotations

import logging, os, sys
from pathlib import Path
from typing import Annotated

from pydantic import Field
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)   # stdout is the protocol channel
ROOT = Path(os.environ.get("NOTES_DIR", "~/notes")).expanduser().resolve()
mcp = MCPServer("notes", instructions="Search and read the user's Markdown notes.", log_level="WARNING")

def _inside_root(rel: str) -> Path:
    p = (ROOT / rel).resolve()                       # resolves symlinks and ..
    if not p.is_relative_to(ROOT):
        raise ToolError(f"path escapes the notes root: {rel!r}")
    return p

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
def search_notes(query: Annotated[str, Field(min_length=2, max_length=200)],
                 limit: Annotated[int, Field(ge=1, le=50)] = 10, cursor: int = 0) -> dict:
    """Find notes containing `query` (case-insensitive): paths and first matching line; page with next_cursor."""
    hits = []
    for f in sorted(ROOT.rglob("*.md")):
        line = next((l for l in f.read_text(errors="replace").splitlines() if query.lower() in l.lower()), None)
        if line is not None:
            hits.append({"path": str(f.relative_to(ROOT)), "line": line[:200]})
    nxt = cursor + limit if cursor + limit < len(hits) else None
    return {"results": hits[cursor:cursor + limit], "next_cursor": nxt, "total": len(hits)}

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def read_note(path: str, max_chars: Annotated[int, Field(ge=100, le=20000)] = 4000) -> str:
    """Read one note by the relative path search_notes returned; truncated to max_chars."""
    p = _inside_root(path)
    if not p.is_file():
        raise ToolError(f"no such note: {path!r}; call search_notes first")
    text = p.read_text(errors="replace")
    return text[:max_chars] + (f"\n[truncated {len(text) - max_chars} chars]" if len(text) > max_chars else "")

if __name__ == "__main__":
    mcp.run()                                        # stdio
```
- Docstring = tool description; `Field(description=...)` documents a parameter. `ctx: Context` as a parameter gives
  `await ctx.report_progress(done, total)` and `await ctx.info(...)` (2.x delivers log messages only to clients that opt in).
  Sync tools are fine (2.x runs them in worker threads); use async for I/O-bound tools.

## stdio hygiene and startup
- The spec: the server MUST NOT write anything but MCP messages to stdout. No `print()`; logs to stderr; silence
  chatty libraries (`logging.getLogger("httpx").setLevel(logging.WARNING)`); child processes get
  `stdout=subprocess.PIPE` or `DEVNULL`, never the inherited stdout. A stray print broke a 2.x client in testing.
- Exit when stdin closes (the SDKs do). Claude Code does not auto-reconnect a crashed stdio server.
- Startup must beat `MCP_TIMEOUT` (60 s in this stack): no network or heavy work at import; import numpy/torch/pandas
  inside the tool that needs them; open clients and databases lazily and cache them in module globals.
- The first `uv run --script` downloads dependencies: prefetch once with `uv run --quiet --script server.py </dev/null`
  (the installer does this for the stack's servers).
- Probe stdout cleanliness and startup time (tested; warm starts took 1-1.5 s, cold about 3 s):
  ```bash
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
    | uv run --quiet --script server.py | head -c 200     # must start with {"jsonrpc"
  ```

## Pinning
- Script dependencies: bounded ranges (`"mcp>=2.2,<3"`); `uv add --script server.py 'httpx>=0.28,<1'`;
  `uv lock --script server.py` writes `server.py.lock` (run with `uv run --locked --script`); or a date freeze with
  `# [tool.uv]` / `# exclude-newer = "2026-09-01T00:00:00Z"` inside the script block (tested: it hid a later
  release); `uv tree --script server.py` shows the resolution.
- SDK 2.x brings `httpx2`, not `httpx`: declare `httpx` if the server uses it.
- Third-party servers: exact versions (`pkg@x.y.z` for npx, `pkg==x.y.z` for uvx), bumped deliberately in every
  place the stack names them (agent files, magg catalog, installer prefetch).

## Testing
1. Unit-test tool functions directly: load the script with `importlib.util.spec_from_file_location`, call the
   functions (async ones via `asyncio.run`); fake the network with `httpx.MockTransport` through a module-level
   `_TRANSPORT`, isolate `HOME` and `STACK_ENV_FILE` with pytest's `tmp_path`/`monkeypatch` (as
   `tests/test_image_studio_mcp.py` does). Run with the server's SDK major:
   `uv run --with pytest --with httpx --with "mcp>=1.10,<2" pytest -q tests/test_<name>.py`.
2. In-process protocol test (tested): 2.x `async with Client(srv.mcp) as c: r = await c.call_tool(...)`
   (`from mcp import Client`); 1.x `from mcp.shared.memory import create_connected_server_and_client_session`,
   `async with create_connected_server_and_client_session(srv.mcp) as s: r = await s.call_tool(...)`.
3. End to end over stdio, launched the way the client launches it (tested on 1.x and 2.x):
   ```python
   import asyncio, os
   from mcp import ClientSession, StdioServerParameters
   from mcp.client.stdio import stdio_client
   async def main():
       params = StdioServerParameters(command="uv", args=["run", "--quiet", "--script", "server.py"],
                                      env={**os.environ, "NOTES_DIR": "/tmp/notes"})
       async with stdio_client(params) as (read, write):
           async with ClientSession(read, write) as session:
               await session.initialize()
               assert [t.name for t in (await session.list_tools()).tools] == ["search_notes", "read_note"]
               ok = await session.call_tool("search_notes", {"query": "beta", "limit": 1})
               bad = await session.call_tool("read_note", {"path": "../secret.txt"})
               print(ok.content[0].text[:200], bad.content[0].text)   # bad: isError / is_error is true
   asyncio.run(main())
   ```
   Cover: tool list and schemas, a happy path, an `isError` path, a schema violation, output size under budget.
4. Inspector 2.x (Node >= 22.19): target first, Inspector options after `--` (tested):
   `npx -y @modelcontextprotocol/inspector@2.8.0 --cli uv run --quiet --script server.py -- --method tools/list --strict`
   and `... -- -e NOTES_DIR=/tmp/notes --method tools/call --tool-name read_note --tool-args-json '{"path":"a.md"}' --format json`.
   It starts the server with a minimal environment: pass variables with `-e KEY=VALUE` (exported shell variables
   did not reach the server in testing). Exit 5 = the tool returned `isError`; `--strict` reports schema
   portability problems. Without an OS keychain the Inspector stores stdio `env:` values in plaintext
   (`~/.mcp-inspector/secrets.json`): use test keys.

## Verify
- The initialize probe starts with `{"jsonrpc"`; unit, in-process and stdio tests pass on the pinned SDK major; Inspector `--strict` is clean.
