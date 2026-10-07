---
name: ts-testing
description: Use for TS/JS tests — Vitest, mocks, type tests, coverage.
---
# TypeScript testing

Part of `typescript-engineering` (baseline versions, async rules). Vitest 5.0.3 needs Node `^22.12.0 || ^24.0.0 || >=26.0.0`; Playwright 1.63.0 (Verified 2026-10-02 https://registry.npmjs.org/vitest/latest, https://registry.npmjs.org/@playwright/test/latest).

## Unit and integration (Vitest)
- Vitest 5 (`vitest run`; runs on Node 22.12+, 24 and 26+): `describe`/`it.each`, `vi.fn`, `vi.mock`, `vi.useFakeTimers()`, `expectTypeOf` for type-level tests, coverage via `@vitest/coverage-v8` (`vitest run --coverage`), real-DOM tests via browser mode with the Playwright provider.
```ts
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["src/**/*.test.ts"], coverage: { provider: "v8" } } });
```

E2E: see `test-e2e-playwright`*.

## Verify
- [ ] Tests cover new behavior; e2e for critical flows; accessibility scan clean or issues filed.
```sh
pnpm exec vitest run --coverage
pnpm exec playwright test              # apps with e2e
```
