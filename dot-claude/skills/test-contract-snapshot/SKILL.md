---
name: test-contract-snapshot
description: Use when testing API contracts between services or adding snapshot tests — Pact, Schemathesis.
---
# Contract and snapshot tests
Hub: `test-strategy`. Language-specific snapshot tools: syrupy and inline-snapshot (`python-engineering`), insta (`rust-engineering`), Vitest/Jest snapshots (`typescript-engineering`).

## 1. Consumer-driven contracts (Pact)
- Use when two services you own evolve separately: the consumer's tests record the requests it makes and the responses it relies on (the pact); the provider's CI replays the pact against the real provider.
- Write consumer expectations with matchers (type, regex, array-like) rather than literal values, and only for fields the consumer reads — over-specified pacts block harmless provider changes.
- Provider states (`given("user 42 exists")`) set up data through a provider-side hook, never by sharing a database.
- Share pacts through a Pact Broker (or PactFlow) and gate deploys with `can-i-deploy` (unverified CLI name and flags; check the broker docs).
- Python: pact-python 3 puts the Rust-core API in the top-level package (`from pact import Pact, Verifier, match`); the old API is the deprecated `pact.v2` (needs the `compat-v2` extra). The current specification version is V4.

## 2. Schema-driven API testing (Schemathesis)
- Generates requests from an OpenAPI (2.0–3.2) or GraphQL schema and checks responses for server errors, schema violations and status-code conformance: `schemathesis run <schema-url-or-file> --url <base-url>`.
- Run against a disposable local instance with test credentials; it sends many malformed requests. Fix the schema when it lies, fix the server when it 500s; pin each found case as a regression test.
- Python property tests and stateful API sequences build on hypothesis (`test-property-based`).

## 3. Snapshot and golden tests
- Good for outputs that are large, structured and reviewed by eye: rendered HTML/SVG, CLI output, serialized ASTs, compiler diagnostics, API response shapes. Bad for values with a simple oracle (assert the value) or for nondeterministic output.
- Make output deterministic first: sort keys, fix clocks, seeds and locale, redact ids and timestamps (most tools support redactions/matchers).
- Review every snapshot change like code: an update command (`pytest --snapshot-update` for syrupy, `cargo insta review`, `vitest -u`) is a decision, never a reflex to get green. In CI, missing or changed snapshots must fail, not be written.
- Keep snapshots small and close to the test (inline snapshots where the tool supports them) so the diff is readable in review.

## Verify
- [ ] Contract: the provider verification job runs against the real provider build and fails when a field the consumer reads is removed (try it).
- [ ] Schemathesis run log attached with the schema version and base URL (local), and each finding triaged.
- [ ] Snapshot: a deliberate output change shows a readable diff and fails CI until reviewed and updated.

## Sources
- Verified 2026-10-02 https://raw.githubusercontent.com/pact-foundation/pact-python/main/MIGRATION.md and https://pypi.org/pypi/pact-python/json — pact-python 3.4.1, top-level `pact` API, `pact.v2` deprecated with `compat-v2`; https://github.com/pact-foundation/pact-specification — V4 newest.
- Verified 2026-10-02 https://schemathesis.readthedocs.io/en/stable/ — `schemathesis run <schema> --url <base>`, OpenAPI 2.0–3.2 and GraphQL; https://pypi.org/pypi/schemathesis/json — 4.29.0.
- Verified 2026-10-02 https://insta.rs/docs/cli/ — `cargo insta review`, `cargo insta test`; https://15r10nk.github.io/inline-snapshot/latest/pytest/ — `--inline-snapshot` modes.
- Unverified as of 2026-10-02: syrupy `--snapshot-update`, Vitest `-u`.
