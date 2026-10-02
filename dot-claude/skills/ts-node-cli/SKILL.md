---
name: ts-node-cli
description: Load for Node packages and CLIs — ESM/CJS, exports maps, Node version managers, pnpm/npm.
---
# Node packages, package managers and CLIs

Part of `typescript-engineering` (baseline versions, async rules). Feature-since Node and pnpm versions below: unverified (checked when written, Sep 2026).

## ESM and CJS
- New packages are ESM-only: `"type": "module"`, an `exports` map with the `types` condition first, `"files"` whitelist, `"engines": { "node": ">=22.12" }`.
- `nodenext` needs file extensions in relative imports: write `./util.js` (or `./util.ts` with `rewriteRelativeImportExtensions`).
- `require(esm)` works without flags since Node 22.12/20.19 (stable in 25.4) unless the graph uses top-level `await` (`ERR_REQUIRE_ASYNC_MODULE`), so CJS consumers can load ESM-only packages.
- ESM has no `__dirname`/`__filename`: use `import.meta.dirname` / `import.meta.filename`. JSON: `import data from "./data.json" with { type: "json" };`.
- Named imports from CJS rely on static analysis and can fail at runtime → default-import and destructure.
- Avoid dual ESM/CJS builds (dual-package hazard: two module instances). If unavoidable, build with tsdown and check with `publint` and `attw --pack` (`@arethetypeswrong/cli`).

## Node versions and package managers
- Version managers: `fnm` or `mise` (Volta is unmaintained). Pin with `.node-version`/`.nvmrc` and `engines`. fish shell: `fnm env --use-on-cd --shell fish | source` or `mise activate fish | source` in `config.fish`.
- Corepack is no longer bundled from Node 25 (`npm i -g corepack` if a workflow needs it); declare `"packageManager": "pnpm@<version>"` either way.
- **pnpm** (default for new repos): strict `node_modules`, content-addressed store. Dependency lifecycle scripts don't run unless allowed — pnpm 11+ uses `allowBuilds` in `pnpm-workspace.yaml` (pnpm 10 used `onlyBuiltDependencies`) and `pnpm approve-builds`; pnpm 11+ reads its settings only from `pnpm-workspace.yaml` or the global `config.yaml` (`.npmrc` keeps registry/auth) and delays brand-new releases with `minimumReleaseAge` (1 day by default). CI: `pnpm install --frozen-lockfile`.
- npm: `npm ci` in CI. Commit exactly one lockfile; never mix managers in one repo.

## CLIs and MCP servers
- CLI: `#!/usr/bin/env node` + `"bin"` in package.json; parse with `node:util` `parseArgs` (no dependency) or commander; data to stdout, diagnostics to stderr, meaningful exit codes, respect `NO_COLOR`.
- MCP servers in TypeScript (`@modelcontextprotocol/sdk`): tool design, schemas, transports and testing are in `mcp-server-craft`; security of tool inputs in `secure-coding`.

## Verify
- [ ] ESM/CJS: correct `exports`/`types`, extensions in relative imports; libraries pass `publint` and `attw`.
```sh
pnpm exec publint && pnpm exec attw --pack   # libraries
```
