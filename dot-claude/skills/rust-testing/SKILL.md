---
name: rust-testing
description: Use for Rust tests and benchmarks — nextest, doctests, proptest, insta, criterion, coverage, fuzzing.
---
# Rust testing

Part of `rust-engineering` (baseline, layout, lints). Property and stateful testing across languages: `formal-methods`.

## Tests
- Unit tests in `#[cfg(test)] mod tests` (private access); integration tests in `tests/*.rs` (public API; shared helpers in `tests/common/mod.rs`); doc examples double as tests.
- `cargo nextest run --workspace` (process per test, retries, better output) — nextest does not run doctests, so also run `cargo test --doc`.
- `proptest` for parsers, codecs, invariants (round-trips, idempotence); commit `proptest-regressions/`.
- `insta` snapshots: `assert_snapshot!`, `assert_debug_snapshot!`, `assert_json_snapshot!` (feature `json`); review with `cargo insta review`; in CI insta detects `CI` and fails on mismatches instead of writing (`INSTA_UPDATE=no` forces it).

## Benchmarks, coverage, fuzzing
- `criterion` 0.8 (0.8.2 latest; Verified 2026-10-02 https://crates.io/api/v1/crates/criterion): `benches/foo.rs` + `[[bench]] name = "foo" harness = false`; use `std::hint::black_box`; compare with `--save-baseline main` / `--baseline main`. `divan` is a lighter alternative.
- Coverage: `cargo llvm-cov` (`cargo llvm-cov nextest`). Fuzz parsers with `cargo fuzz` (nightly). Concurrency primitives: `loom`.

## Verify
- [ ] Tests cover new behavior (unit + integration + doc); property tests for parsers/invariants; snapshot diffs reviewed.
```sh
cargo nextest run --workspace --all-features --locked && cargo test --doc --workspace
cargo llvm-cov nextest --workspace        # when coverage is reported
```
