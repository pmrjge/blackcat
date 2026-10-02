---
name: mcp-ts-server
description: Use to write a TypeScript MCP server — SDK 2.x McpServer with zod schemas over stdio, error results, 1.x API differences.
---
# TypeScript MCP servers

Part of `mcp-server-craft` (tool design, security reference). stdio hygiene, startup and Inspector tests: `mcp-python-server` (same rules for Node: stdout is the protocol channel, logs on stderr). HTTP with `createMcpHandler`: `mcp-http-release`.
`@modelcontextprotocol/server` 2.2.0 is current; the example pins the tested 2.1.0 (Verified 2026-10-02 https://registry.npmjs.org/@modelcontextprotocol/server/latest).

## TypeScript server (SDK 2.x, Node >= 20; tested on Node 22)
```js
// server.mjs    npm i @modelcontextprotocol/server@2.1.0 zod@4   (pin exact versions + lockfile)
import { McpServer } from '@modelcontextprotocol/server';
import { StdioServerTransport } from '@modelcontextprotocol/server/stdio';
import * as z from 'zod/v4';
const server = new McpServer({ name: 'wordcount', version: '0.1.0' });
server.registerTool('word_count', {
  title: 'Word count',
  description: 'Count words in a text. Returns {words}.',
  inputSchema: z.object({ text: z.string().min(1).max(100000) }),
  outputSchema: z.object({ words: z.number().int() }),
  annotations: { readOnlyHint: true, idempotentHint: true },
}, async ({ text }) => {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return { content: [{ type: 'text', text: String(words) }], structuredContent: { words } };
});
console.error('wordcount: ready');                 // stderr only
await server.connect(new StdioServerTransport());
```
- Handler failures: return `{ content: [{ type: 'text', text: '...' }], isError: true }`; schema violations come
  back as `isError` automatically (tested).
- 1.x (`@modelcontextprotocol/sdk`): `McpServer` from `@modelcontextprotocol/sdk/server/mcp.js`,
  `StdioServerTransport` from `.../server/stdio.js`, `inputSchema` as a raw shape `{ a: z.number().int() }` (tested).

## Verify
- Exact pins plus a lockfile; `npx -y @modelcontextprotocol/inspector@2.8.0 --cli node server.mjs -- --method tools/list --strict` is clean (tested pin; 2.9.0 is current, not re-tested); a schema violation and a handler failure both come back as `isError`.
