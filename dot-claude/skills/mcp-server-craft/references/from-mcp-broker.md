# mcp-broker procedures (moved from its prompt)

## Vetting a server before mounting
- An official or well-maintained repository, minimal permissions, no install scripts you can't read.
- Prefer remote HTTP or pinned `npx -y` / `uvx` packages; record the pinned version.
- Database servers (mongodb, postgres, duckdb) run read-only; a write needs the user's consent and a catalog edit.

## Making a server permanent (only after the user's consent through ASK USER)
Edit the stack repo (`__STACK_REPO__`), never installed copies, per the lifecycle in `claude-code-extensions`:
- a local stdio server for one agent → inline in that agent's `mcpServers` plus `mcp__<name>` on its `tools` line;
- a remote server for many agents → user scope with the stack's `headersHelper` (key mapping in `dot-claude/bin/mcp-headers`) and `mcp__<name>` on the agents that need it;
- a rare server → a disabled entry with a pinned version in `dot-claude/magg/config.json`.
Remove with the reverse edit. The user re-runs `./install.sh` there; OAuth servers need `/mcp` once. Keys stay in `__CLAUDE_DIR__/stack.env`, referenced by variable name.

## Audit
List servers and tool counts (`claude mcp list`, `magg_status`, the proxy list); flag unused servers, huge tool sets, user-scope servers that should be agent-scoped, and any plaintext key in `~/.claude.json` (it should be a headersHelper).
