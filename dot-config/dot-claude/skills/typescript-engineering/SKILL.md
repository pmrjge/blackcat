---
name: typescript-engineering
description: Use for TypeScript or JavaScript — TS 7 vs 6, tsconfig, ESM/CJS, Node, pnpm, Vite, linting, tests, zod.
---
# TypeScript engineering

## Scope and baseline
- Covers TS/JS for CLIs, libraries, Node servers and web front-ends. MCP server design is in `mcp-server-dev:build-mcp-server`; security review in `secure-coding`; interactive browser driving in `browser-automation`.
- Baseline (re-check with `npm view <pkg> version` before pinning):
  - **TypeScript 7.0** (native Go port, `typescript@7`, `tsc` ~10x faster) is `latest` since July 2026 (7.0.2, 2026-07-08). It ships **no programmatic API** until 7.1, so tools that import `typescript` keep needing **TypeScript 6.0** (Mar 2026, the last JS-based line): typescript-eslint 8.x supports `>=4.8.4 <6.1.0`; Volar-based Vue/Svelte/Astro/MDX and Angular template checking stay on 6.
  - Node: 24 = active LTS (maintenance from 2026-10-20), 22 = maintenance LTS (EOL 2027-04-30), 26 = current (LTS from 2026-10-28), 20 = end of life (2026-04-30). Target 24 for new work.
  - pnpm 12 / npm 12, Vite 8 (Rolldown-based), Vitest 5, ESLint 10 (flat config only; eslintrc removed), typescript-eslint 8, Biome 2, oxlint 1, tsdown (tsup is no longer maintained; its last release, 8.5.1, is from 2025-11), zod 4, Playwright 1.63.
  - Verified 2026-10-02 https://registry.npmjs.org/<pkg>/latest (typescript 7.0.2, @typescript/typescript6 6.0.2, pnpm 12.8.1, npm 12.2.0, vite 8.3.2, vitest 5.0.3, eslint 10.11.0, typescript-eslint 8.71.0 with peer `typescript >=4.8.4 <6.1.0`, @biomejs/biome 2.5.15, oxlint 1.86.0, tsdown 0.23.0, zod 4.6.5, @playwright/test 1.63.0) and https://raw.githubusercontent.com/nodejs/Release/main/schedule.json. Node feature-since versions in the modules: unverified (checked when written, Sep 2026).

## Modules (load the one the task touches)
| Module | Load for |
|---|---|
| `ts-tooling`* | TS 6 vs 7, tsconfig, builds (Vite, tsdown, type stripping), ESLint/oxlint/Biome |
| `ts-node-cli`* | ESM/CJS packaging, Node versions, pnpm/npm, CLIs |
| `ts-types-validation`* | zod schemas at boundaries, discriminated unions, brands, generics |
| `ts-testing`* | Vitest, type-level tests, coverage (end to end: `test-e2e-playwright`*) |

`*` = not in the skill listing: Read `__CLAUDE_DIR__/skills/<name>/SKILL.md` (the Skill tool won't load it).

## Async and errors
- Every promise is awaited, returned or explicitly `void`-ed (lint rule). `Promise.all` fails fast; `Promise.allSettled` collects; cap concurrency with a small semaphore or `p-limit`.
- Cancellation/timeouts: thread an `AbortSignal` through APIs; `AbortSignal.timeout(ms)`; `AbortSignal.any([...])` to combine.
- `throw new Error("reading config", { cause: err })`; `catch (e: unknown)` and narrow (`e instanceof Error`); never throw strings.
- Node exits on unhandled rejections by default; handle `SIGINT`/`SIGTERM` for graceful shutdown; compose streams with `pipeline` from `node:stream/promises`.

## Web performance, accessibility, security pointers
- Frameworks (React/Next.js/Svelte/Vue/Astro, Tailwind) and Core Web Vitals: `frontend-frameworks`.
- Accessibility (WCAG 2.2 AA, keyboard, screen readers, axe): `web-accessibility`.
- Security (`secure-coding`): no `innerHTML`/`dangerouslySetInnerHTML` with untrusted data, a Content Security Policy, dependency audit (`pnpm audit`/`npm audit`), no secrets in client bundles.

## Review checklist
- [ ] Lockfile committed and frozen installs pass; Node engine range and package manager pinned.
- [ ] No floating promises; cancellation/timeouts on network calls; concurrency bounded.
- [ ] No secrets or `VITE_*` values that must stay private; `secure-coding` checklist for untrusted input.
- [ ] Each loaded module's Verify items hold (types, ESM/CJS, tests).

## Verify
```sh
pnpm install --frozen-lockfile
```
Plus the Verify block of every module the change touched (type check and lint: `ts-tooling`; tests: `ts-testing`; packages: `ts-node-cli`).

## Deliverables / Report
- Files changed; commands run with their decisive output (type errors, lint count, tests passed, coverage %).
- TypeScript and Node versions targeted; TS 6/7 arrangement and why; new dependencies (version, license, reason).
- For front-ends: Web Vitals before/after on the same profile, accessibility scan results.
- Residual risks: untyped dependencies, skipped browsers, APIs not validated.
