---
name: test-strategy
description: Load before deciding what and how to test or repairing a weak suite — test levels, oracles, flakiness, seeded-bug checks; tools in test-*.
---
# Test strategy (hub)

## Scope
- Choosing test levels and techniques, writing tests that can fail, keeping a suite fast and trustworthy. Runner mechanics per language: `python-engineering`, `typescript-engineering`, `rust-engineering` (and their testing modules), `cpp-engineering`, `jvm-engineering`, `haskell-engineering`, `julia-engineering`. Machine-checked proofs and model checking: `formal-methods`. Numerical verification: `numerical-methods` §9.

## Baseline rules
- A test earns its place by failing on a plausible bug. Before trusting a new test, break the code on purpose (seeded bug, mutant) and watch it fail; then restore.
- Test behavior through the public interface; private helpers are covered through their callers. Assert on outcomes, not on call sequences, unless the call is the behavior (sent an email, wrote a row).
- Pick the oracle first: exact expected value, reference implementation, round trip, invariant, metamorphic relation, schema, snapshot. No oracle → no test.
- Level by cost of the bug and speed of feedback: many fast unit/property tests, fewer integration tests against real dependencies (a real database in a container, not a mock of it), few end-to-end flows on the critical paths.
- Every fixed bug gets a regression test that failed before the fix. Every counterexample from a property test or fuzzer becomes a pinned test.
- Never weaken, skip or delete a test to get green; if a test is wrong, say why and fix it in its own change.
- Determinism: seeded randomness, frozen clocks, no network to third parties, no order dependence; tests runnable alone and in parallel.
- Flaky test: reproduce with repetition (`--count`, `--repeat-each`, loops), find the cause (time, order, shared state, async waits), fix or quarantine with an issue and an owner; never retry-until-green silently.
- A regression with a known good version: bisect it and minimize the input first (`debug-bisect-minimize`); native crashes: `debug-native`.
- Coverage is a map of what was never executed, not a quality score; mutation score is the closer measure of whether tests check anything.

## Modules
| Module | Load when |
|---|---|
| `test-property-based` | invariants, round trips, model-based/stateful tests (hypothesis, proptest, fast-check) |
| `test-fuzzing` | parsers, decoders or anything reading untrusted bytes (cargo-fuzz, atheris, AFL++, Go fuzzing) |
| `test-mutation` | checking that a suite catches bugs (mutmut, cargo-mutants, StrykerJS, PIT) |
| `test-e2e-playwright` | browser end-to-end flows, visual and accessibility checks with Playwright Test |
| `test-contract-snapshot` | API contracts between services (Pact, Schemathesis) and snapshot/golden tests |

## Verify
- [ ] Each new test was seen failing (seeded bug, mutant or pre-fix run) and passing.
- [ ] Full suite green twice in a row, once in random order or parallel where the runner supports it.
- [ ] Report: tests added (file::name), what bug each catches, how its failure was demonstrated, runtime of the suite before and after.
