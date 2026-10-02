---
name: test-e2e-playwright
description: Use when writing or fixing browser end-to-end tests with Playwright Test — locators, traces.
---
# End-to-end tests with Playwright Test
Hub: `test-strategy`. Project setup and runner basics: `typescript-engineering` (Testing). Driving a browser for a task rather than a test suite: `browser-automation`. Accessibility rules: `web-accessibility` (audits: `a11y-audit`).

## What to cover
- Only the critical user journeys end to end (sign up, log in, the main create/edit/pay flow, the main error path). Everything else belongs in unit, component or API tests — e2e tests are slow and the most flake-prone level.
- Each test owns its data: create it through the API or a seeded fixture in `beforeEach`, never depend on another test's leftovers; tests run in parallel by default.
- Start the app from the config (`webServer`) so CI and local runs match; point tests at a disposable database.

## Writing stable tests
- Locators by role, label or text the user sees: `page.getByRole("button", { name: "Save" })`, `getByLabel`, `getByText`; `getByTestId` only where no accessible name exists (and then consider adding one). Never CSS chains tied to layout or generated class names.
- Web-first assertions that auto-wait: `await expect(locator).toBeVisible()`, `toHaveText`, `toHaveURL`, `toHaveCount`. No fixed sleeps (`waitForTimeout`); no manual polling of `isVisible()`.
- Network: wait on the response that matters (`page.waitForResponse`) or mock third parties with `page.route`; never call real payment, email or analytics services.
- Authentication once per worker with a stored state file (`storageState`) instead of logging in through the UI in every test.
- Time and randomness: freeze the clock (`page.clock`) for date-dependent UI; seed server-side randomness.

## Debugging and CI
- Traces: `trace: 'on-first-retry'` in the config, or `npx playwright test --trace on` locally; open the HTML report (`npx playwright show-report`) and the trace viewer from it.
- `retries` in CI (the generated config uses `process.env.CI ? 2 : 0`): a test that passes only on retry is flaky — it is reported as such; fix it, don't raise retries.
- Sharding across CI machines: `npx playwright test --shard=1/4` … `4/4` (1-based), then merge reports.
- Reproduce flakes locally with `--repeat-each=20` and `--workers` equal to CI's.

## Visual and accessibility checks
- `await expect(page).toHaveScreenshot()` compares to a committed baseline; update intentionally with `npx playwright test --update-snapshots` and review the image diff. Baselines are per browser and OS: generate them in the same container as CI; mask dynamic regions (`mask: [locator]`).
- Accessibility: `@axe-core/playwright` scans of each key state and ARIA snapshots (`toMatchAriaSnapshot`) — code in `a11y-audit`.

## Verify
- [ ] The suite passes three times in a row locally with CI's worker count (`--repeat-each=3`), and in CI.
- [ ] A seeded UI bug (wrong label, broken handler) makes the relevant test fail with a readable message.
- [ ] No `waitForTimeout`, no layout-bound CSS selectors, no real third-party calls (grep the test directory).
- [ ] Traces or reports attached for any failure reported.

## Sources
- Verified 2026-10-02 https://playwright.dev/docs/trace-viewer-intro, https://playwright.dev/docs/test-snapshots, https://playwright.dev/docs/test-sharding — `--trace on`, `trace: 'on-first-retry'`, `retries`, `toHaveScreenshot()`, `--update-snapshots`, `--shard=1/4` (1-based), `show-report`; https://registry.npmjs.org/@playwright/test/latest — Playwright 1.63.0 (Node ≥ 20).
- Unverified as of 2026-10-02: `page.clock`, `storageState`, `--repeat-each`, `mask` option names (long-standing Playwright APIs; re-check in the docs for the installed version).
