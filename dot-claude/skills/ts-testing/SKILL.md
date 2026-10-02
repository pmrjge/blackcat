---
name: ts-testing
description: Use for TypeScript/JavaScript tests — Vitest unit and integration tests, mocks, type tests, coverage, Playwright Test end to end.
---
# TypeScript testing

Part of `typescript-engineering` (baseline versions, async rules). Vitest 5.0.3 needs Node `^22.12.0 || ^24.0.0 || >=26.0.0`; Playwright 1.63.0 (Verified 2026-10-02 https://registry.npmjs.org/vitest/latest, https://registry.npmjs.org/@playwright/test/latest).

## Unit and integration (Vitest)
- Vitest 5 (`vitest run`; runs on Node 22.12+, 24 and 26+): `describe`/`it.each`, `vi.fn`, `vi.mock`, `vi.useFakeTimers()`, `expectTypeOf` for type-level tests, coverage via `@vitest/coverage-v8` (`vitest run --coverage`), real-DOM tests via browser mode with the Playwright provider.
```ts
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["src/**/*.test.ts"], coverage: { provider: "v8" } } });
```

## End to end (Playwright Test)
- `npm init playwright@latest`, `npx playwright install --with-deps chromium`; role/label locators (`page.getByRole("button", { name: "Save" })`), web-first assertions (`await expect(locator).toBeVisible()`), no fixed sleeps, `webServer` in the config to start the app, `trace: "on-first-retry"`; accessibility scans with `@axe-core/playwright`.

## Verify
- [ ] Tests cover new behavior; e2e for critical flows; accessibility scan clean or issues filed.
```sh
pnpm exec vitest run --coverage
pnpm exec playwright test              # apps with e2e
```
