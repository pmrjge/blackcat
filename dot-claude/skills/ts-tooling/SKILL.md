---
name: ts-tooling
description: Use for TypeScript project tooling — TS 6 vs 7, strict tsconfig, Vite/tsdown builds, linting and formatting with ESLint, oxlint or Biome.
---
# TypeScript tooling

Part of `typescript-engineering` (baseline versions, async rules). Versions verified there.

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

## Verify
- [ ] `tsc --noEmit` clean under the strict config; lint clean with the repo's one linter and one formatter.
```sh
pnpm exec tsc --noEmit                 # TS 7; also `pnpm exec tsc6 --noEmit` when the alias setup is used
pnpm exec eslint .                     # or: pnpm exec oxlint --type-aware / pnpm exec biome ci
```
