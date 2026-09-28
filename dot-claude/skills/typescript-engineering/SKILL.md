---
name: typescript-engineering
description: Load before writing, reviewing, building or testing TypeScript or JavaScript — TS 7 vs 6 tooling, strict tsconfig, ESM/CJS, Node, pnpm, Vite/tsdown, ESLint/Biome, Vitest, zod.
---
# TypeScript engineering

## Scope and baseline
- Covers TS/JS for CLIs, libraries, Node servers and web front-ends. MCP server design is in `mcp-server-craft`; security review in `secure-coding`; interactive browser driving in `browser-automation`.
- Baseline (Sep 2026 — re-check with `npm view <pkg> version` before pinning):
  - **TypeScript 7.0** (native Go port, `typescript@7`, `tsc` ~10x faster) is `latest` since July 2026. It ships **no programmatic API** until 7.1, so tools that import `typescript` keep needing **TypeScript 6.0** (Mar 2026, the last JS-based line): typescript-eslint 8.x supports `>=4.8.4 <6.1.0`; Volar-based Vue/Svelte/Astro/MDX and Angular template checking stay on 6.
  - Node: 24 = active LTS (maintenance from 2026-10-20), 22 = maintenance LTS (EOL 2027-04-30), 26 = current (LTS from 2026-10-28), 20 = end of life. Target 24 for new work.
  - pnpm 12 / npm 12, Vite 8 (Rolldown-based), Vitest 5, ESLint 10 (flat config only; eslintrc removed), typescript-eslint 8, Biome 2, oxlint 1, tsdown (tsup is no longer maintained), zod 4, Playwright 1.63.

## TypeScript 6 vs 7
| Situation | Setup |
|---|---|
| App/library, no tool needs the TS API | `typescript@^7` only; lint with oxlint (type-aware via `oxlint-tsgolint`, requires TS 7) or Biome, or ESLint without typed rules |
| typescript-eslint typed rules | Side by side (verified): `"typescript": "npm:@typescript/typescript6@^6.0.2"` (API for tools, binary `tsc6`) + `"@typescript/native": "npm:typescript@^7.0.2"` (binary `tsc`) |
| Vue/Svelte/Astro/Angular/MDX | Stay on TS 6 until their tooling supports the 7.1 API |
| Editor support | TS 7 has a built-in language server (`tsc --lsp --stdio`); VS Code uses a dedicated TS 7 extension |
- Migrate by first compiling cleanly on 6.0 with its deprecations fixed (don't park them behind `"ignoreDeprecations": "6.0"`), then switch.
- 6.0/7.0 defaults: `strict: true`, `module: esnext`, `target` = latest stable ES, `types: []` (list globals explicitly, e.g. `"types": ["node"]`), `rootDir` = the tsconfig directory (set `"rootDir": "src"`), `noUncheckedSideEffectImports: true`.
- Removed in 7.0: `target: es5`, `downlevelIteration`, `moduleResolution: node`/`node10`/`classic`, `module: amd|umd|systemjs|none`, `baseUrl` (use `paths` with relative targets, or package.json `imports` with `#/` subpaths), `outFile`, and `esModuleInterop`/`allowSyntheticDefaultImports`/`alwaysStrict` set to `false`.

## tsconfig
Node ESM package (compiled and ran with TS 7.0.2 on Node 22):
```json
{
  "compilerOptions": {
    "target": "es2023",
    "module": "nodenext",
    "moduleResolution": "nodenext",
    "lib": ["es2023"],
    "types": ["node"],
    "rootDir": "src",
    "outDir": "dist",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "noPropertyAccessFromIndexSignature": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "erasableSyntaxOnly": true,
    "rewriteRelativeImportExtensions": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```
- `noUncheckedIndexedAccess`: `arr[i]` and `record[key]` become `T | undefined`. Worth it for application code; in hot numeric loops iterate with `for...of`/`entries()` instead of asserting.
- `exactOptionalPropertyTypes`: `{ a?: string }` no longer accepts `a: undefined` — correct where presence matters (PATCH payloads, option merging) but noisy against third-party types written loosely. Enable on new code bases; drop it when it only fights dependencies.
- `verbatimModuleSyntax` + `import type`, `isolatedModules`, `erasableSyntaxOnly` (no enums, namespaces with runtime code, parameter properties): code then runs under Node type stripping and any single-file transpiler.
- `module`: `nodenext` for code Node runs directly (honors `"type"` and `exports`); `"module": "esnext", "moduleResolution": "bundler", "noEmit": true` for Vite apps, plus `"lib": ["es2023", "dom", "dom.iterable"]`, `"types": ["vite/client"]`, `"jsx": "react-jsx"` when relevant.
- Libraries: emit declarations; `isolatedDeclarations` lets other tools generate `.d.ts` in parallel (requires explicit return types on exports).

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

## Build
| Target | Tool |
|---|---|
| Web app/SPA, assets, dev server | Vite 8: `vite`, `vite build`, `vite preview`; only `VITE_*` env vars reach client code — and they are public |
| Library or CLI bundle + `.d.ts` | tsdown (Rolldown-based successor to tsup), or plain `tsc` for unbundled libraries |
| Run TS directly in development | Node ≥ 22.18 strips types by default (stable since 24.12/25.2): explicit `.ts` extensions, `import type`, erasable syntax only, tsconfig `paths` not applied; `tsx` for full TS syntax |
| Custom pipelines | esbuild or Rolldown APIs |
Type checking is always a separate step (`tsc --noEmit`) — bundlers and type stripping never check types.

## Lint and format
| Need | Choice |
|---|---|
| typescript-eslint typed rules (`no-floating-promises`, `no-misused-promises`, `switch-exhaustiveness-check`, `strict-boolean-expressions`) | ESLint 10 + typescript-eslint (with the TS 6 alias under TS 7) |
| Speed, TS 7 | oxlint; `oxlint --type-aware` with `oxlint-tsgolint` covers most typed rules |
| One tool for lint + format | Biome 2 (`biome check --write`, `biome ci`) |
One formatter only (Prettier or Biome). Typed ESLint config (verified with ESLint 10 + typescript-eslint 8.70 + TS 6 alias):
```js
// eslint.config.js
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist/**"] },
  {
    files: ["**/*.ts"],
    extends: [js.configs.recommended, tseslint.configs.strictTypeChecked, tseslint.configs.stylisticTypeChecked],
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
  },
);
```

## Testing
- Vitest 5 (`vitest run`; runs on Node 22.12+, 24 and 26+): `describe`/`it.each`, `vi.fn`, `vi.mock`, `vi.useFakeTimers()`, `expectTypeOf` for type-level tests, coverage via `@vitest/coverage-v8` (`vitest run --coverage`), real-DOM tests via browser mode with the Playwright provider.
```ts
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["src/**/*.test.ts"], coverage: { provider: "v8" } } });
```
- Playwright Test for end-to-end: `npm init playwright@latest`, `npx playwright install --with-deps chromium`; role/label locators (`page.getByRole("button", { name: "Save" })`), web-first assertions (`await expect(locator).toBeVisible()`), no fixed sleeps, `webServer` in the config to start the app, `trace: "on-first-retry"`; accessibility scans with `@axe-core/playwright`.

## Runtime validation (zod 4)
- Validate at every boundary — HTTP bodies, env, files, `postMessage`, LLM/tool output — then pass typed values inward.
```ts
import { z } from "zod";                        // zod@4: the root export is the v4 API; "zod/mini" for small bundles
const Config = z.object({
  port: z.number().int().min(1).max(65535).default(8080),
  host: z.string().default("127.0.0.1"),
  tags: z.array(z.string()).optional(),
});
export type Config = z.infer<typeof Config>;
export function parseConfig(input: unknown): Config {
  const r = Config.safeParse(input);
  if (!r.success) throw new Error(z.prettifyError(r.error));
  return r.data;
}
```
- Parse `process.env` once at startup into a typed config and fail fast. Zod 4 has top-level string formats (`z.email()`, `z.url()`) and prefers the `error` option over `message`.

## Type patterns
```ts
type Shape = { kind: "circle"; r: number } | { kind: "rect"; w: number; h: number };
function area(s: Shape): number {
  switch (s.kind) {
    case "circle": return Math.PI * s.r ** 2;
    case "rect": return s.w * s.h;
    default: { const unreachable: never = s; throw new Error(`unhandled ${JSON.stringify(unreachable)}`); }
  }
}
declare const brand: unique symbol;
type Brand<T, B extends string> = T & { readonly [brand]: B };
type UserId = Brand<string, "UserId">;          // IDs and units can't be mixed up
const palette = { primary: "#0af" } satisfies Record<string, `#${string}`>; // checked, keeps literal types
```
- `unknown` instead of `any`; narrow with guards or schemas; `// @ts-expect-error <reason>` rather than `@ts-ignore`.
- Generics only when a type parameter links two positions (input ↔ output); constrain them; `NoInfer<T>` stops inference from a parameter; prefer unions or overloads for two or three cases.
- Replace enums with `as const` objects + union types (erasable). `readonly` arrays/tuples in parameters.
- Expected failures as result unions (`{ ok: true; value } | { ok: false; error }`); exceptions for bugs.

## Async and errors
- Every promise is awaited, returned or explicitly `void`-ed (lint rule). `Promise.all` fails fast; `Promise.allSettled` collects; cap concurrency with a small semaphore or `p-limit`.
- Cancellation/timeouts: thread an `AbortSignal` through APIs; `AbortSignal.timeout(ms)`; `AbortSignal.any([...])` to combine.
- `throw new Error("reading config", { cause: err })`; `catch (e: unknown)` and narrow (`e instanceof Error`); never throw strings.
- Node exits on unhandled rejections by default; handle `SIGINT`/`SIGTERM` for graceful shutdown; compose streams with `pipeline` from `node:stream/promises`.

## CLIs and MCP servers
- CLI: `#!/usr/bin/env node` + `"bin"` in package.json; parse with `node:util` `parseArgs` (no dependency) or commander; data to stdout, diagnostics to stderr, meaningful exit codes, respect `NO_COLOR`.
- MCP servers in TypeScript (`@modelcontextprotocol/sdk`): tool design, schemas, transports and testing are in `mcp-server-craft`; security of tool inputs in `secure-coding`.

## Web performance, accessibility, security pointers
- Performance: measure Core Web Vitals (LCP, INP, CLS) with Lighthouse/DevTools on a throttled profile; split by route (`import()`), ship less JavaScript, size images (`width`/`height`, `loading="lazy"`), preload critical fonts, avoid layout thrash.
- Accessibility: semantic HTML first, labelled controls, full keyboard operation with visible focus, WCAG AA contrast, ARIA only to fill gaps; automated axe scan plus a manual keyboard and VoiceOver pass.
- Security (`secure-coding`): no `innerHTML`/`dangerouslySetInnerHTML` with untrusted data, a Content Security Policy, dependency audit (`pnpm audit`/`npm audit`), no secrets in client bundles.

## Review checklist
- [ ] Lockfile committed and frozen installs pass; Node engine range and package manager pinned.
- [ ] `tsc --noEmit` clean under the strict config; no new `any`, `as` casts justified, `@ts-expect-error` has a reason.
- [ ] Boundaries validated with schemas; env parsed once; errors carry `cause`.
- [ ] No floating promises; cancellation/timeouts on network calls; concurrency bounded.
- [ ] ESM/CJS: correct `exports`/`types`, extensions in relative imports; libraries pass `publint` and `attw`.
- [ ] Tests cover new behavior; e2e for critical flows; accessibility scan clean or issues filed.
- [ ] No secrets or `VITE_*` values that must stay private; `secure-coding` checklist for untrusted input.

## Verify
```sh
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit                 # TS 7; also `pnpm exec tsc6 --noEmit` when the alias setup is used
pnpm exec eslint .                     # or: pnpm exec oxlint --type-aware / pnpm exec biome ci
pnpm exec vitest run --coverage
pnpm exec playwright test              # apps with e2e
pnpm exec publint && pnpm exec attw --pack   # libraries
```

## Deliverables / Report
- Files changed; commands run with their decisive output (type errors, lint count, tests passed, coverage %).
- TypeScript and Node versions targeted; TS 6/7 arrangement and why; new dependencies (version, license, reason).
- For front-ends: Web Vitals before/after on the same profile, accessibility scan results.
- Residual risks: untyped dependencies, skipped browsers, APIs not validated.
