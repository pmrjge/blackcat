---
name: test-mutation
description: Use when checking that tests catch bugs — mutmut, cargo-mutants, StrykerJS, PIT.
---
# Mutation testing
Hub: `test-strategy`. A mutant is the code with one small change (`<` → `<=`, `+` → `-`, a return replaced, a call removed). A mutant the tests still pass on ("survived", "missed") is either a missing test or an equivalent mutant.

## When and how much
- Run on the code you changed and on critical modules, not on the whole repository at every commit: diff-scoped runs in CI, full runs nightly or before a release.
- Make the suite fast and deterministic first; mutation testing multiplies runtime by the number of mutants. Flaky tests show up as random kills and timeouts.
- Triage each surviving mutant: (a) write the missing assertion or case, (b) mark as equivalent with a one-line reason (no observable difference), or (c) accept with a reason (logging, defensive branch). Never chase 100% blindly.
- Report the score as killed / (total − equivalent − unviable), with the scope and tool version.

## Tools
- **Python — mutmut 3:** configure in `pyproject.toml` under `[tool.mutmut]` (`source_paths = ["src/"]`; also `only_mutate`, `do_not_mutate`, `also_copy`); run `mutmut run`, inspect and apply mutants with `mutmut browse` / `mutmut apply <id>`; `mutmut export-cicd-stats` for CI. Tests run with pytest.
- **Rust — cargo-mutants:** `cargo install cargo-mutants` (`--locked` recommended for reproducible installs), `cargo mutants` in the workspace; diff-scoped: `git diff origin/main.. > d.diff && cargo mutants --in-diff d.diff`; split across CI jobs with `--shard k/n` (k is 0-based: `0/8` … `7/8`; `--sharding slice|round-robin`). Results land in `mutants.out/` (outcome names unverified — read `mutants.out/` after a run). Mark intentional skips with `#[mutants::skip]` (unverified).
- **JS/TS — StrykerJS (major 10; Node ≥ 22):** initialize and run per the current docs (`npm init stryker@latest`, `npx stryker run` — unverified); configure the test runner plugin (Vitest, Jest, Mocha) and `mutate` globs; incremental mode for repeated runs (unverified flag name).
- **JVM — PIT (pitest):** Maven `mvn test-compile org.pitest:pitest-maven:mutationCoverage`; Gradle plugin `info.solidsoft.pitest` (unverified); `targetClasses`/`targetTests` to scope; `jvm-engineering` for the build side.
- **Seeded-bug check without a tool:** apply one hand-written mutation (flip a comparison in the function under test), run the new tests, confirm at least one fails, revert. Use this for every new test when no mutation tool is set up.

## Verify
- [ ] Scope, tool version, mutant counts (killed, survived, timeout, unviable, equivalent) and runtime reported.
- [ ] Every survivor in changed code triaged as new test / equivalent / accepted, with the reason.
- [ ] New tests kill the mutants they were written for (rerun the tool on that file).

## Sources
- Verified 2026-10-02 https://mutmut.readthedocs.io/en/latest/ — `mutmut run`, `mutmut browse`, `apply`, `export-cicd-stats`, `[tool.mutmut] source_paths`; https://pypi.org/pypi/mutmut/json — 3.8.0.
- Verified 2026-10-02 https://mutants.rs/in-diff.html and https://mutants.rs/shards.html — `--in-diff`, `--shard k/n` 0-based, `--sharding`; https://crates.io/api/v1/crates/cargo-mutants — 27.1.0.
- Verified 2026-10-02 https://registry.npmjs.org/@stryker-mutator/core/latest — StrykerJS 10.0.0, Node ≥ 22.
- Verified 2026-10-02 https://pitest.org/quickstart/maven/ — `mvn test-compile org.pitest:pitest-maven:mutationCoverage`.
