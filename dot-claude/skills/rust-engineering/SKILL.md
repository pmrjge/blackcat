---
name: rust-engineering
description: Use for any Rust work — workspaces, edition 2024, errors, async, unsafe, tests, clippy, releases.
---
# Rust engineering

## Scope
- Production Rust for libraries, CLIs and services: layout, errors, ownership, async, testing, linting, release builds, crate choice, review.
- Not here: GUI toolkits (`rust-native-gui`), editor internals (`editor-engineering`), `.app` packaging/signing (`macos-app-distribution`), profiling methodology (`cpu-performance`).
- Baseline: stable Rust 1.99.0 (2026-09-28; 6-week cadence — check `rustc -V`). Verified 2026-10-02 https://static.rust-lang.org/dist/channel-rust-stable.toml. **Edition 2024** is current (stable since 1.85; Verified 2026-10-02 https://blog.rust-lang.org/2025/02/20/Rust-1.85.0/); resolver `"3"` (MSRV-aware) is the edition-2024 default. Verify crate APIs on docs.rs or with `mcp__libdocs` before writing version-specific code.

## Modules (load the one the task touches)
| Module | Load for |
|---|---|
| `rust-errors-ownership`* | thiserror/anyhow, panics, borrow-checker patterns, compiler-error fixes, crate choice |
| `rust-async`* | tokio runtimes, blocking, cancellation and cancel-safe `select!`, JoinSet, channels, `Send` errors |
| `rust-unsafe-ffi`* | unsafe policy, SAFETY comments, edition-2024 unsafe rules, Miri, sanitizers, FFI |
| `rust-testing`* | unit/integration/doc tests, nextest, proptest, insta, criterion/divan, coverage, fuzzing, loom |
| `rust-release`* | MSRV, feature and public-API policy, release profiles, debuginfo, cross-compiling |

`*` = not in the skill listing: Read `__CLAUDE_DIR__/skills/<name>/SKILL.md` (the Skill tool won't load it).

- Read `references/performance.md` when optimizing allocation, hashing, parallelism or SIMD; `references/cli-serde-logging.md` when writing a CLI, tracing setup or serde formats.

## Workspace layout
```toml
# Cargo.toml (virtual manifest)
[workspace]
members = ["crates/*", "xtask"]
resolver = "3"                 # must be explicit in a virtual manifest (no package edition to infer it)

[workspace.package]
edition = "2024"
rust-version = "1.85"          # MSRV; clippy reads it too
license = "MIT OR Apache-2.0"

[workspace.dependencies]
anyhow = "1"
thiserror = "2"
serde = { version = "1", features = ["derive"] }
tokio = { version = "1", default-features = false }

[workspace.lints.rust]
unsafe_op_in_unsafe_fn = "deny"
[workspace.lints.clippy]
pedantic = { level = "warn", priority = -1 }   # groups need lower priority so single lints can override
module_name_repetitions = "allow"
missing_errors_doc = "allow"
```
Members use `edition.workspace = true`, `tokio = { workspace = true, features = ["rt-multi-thread", "macros"] }`, `[lints] workspace = true`.
- Split: `crates/core` (pure logic, no I/O, most tests), `crates/cli` or `crates/app` (I/O, config, wiring). `xtask` crate + `.cargo/config.toml` `[alias] xtask = "run --package xtask --"` for build/release scripts instead of shell glue.
- Commit `Cargo.lock` for every package (current Cargo guidance, libraries included); build CI with `--locked`.
- Apps pin the toolchain in `rust-toolchain.toml` (`[toolchain] channel = "1.99"`, `components = ["clippy", "rustfmt"]`); libraries test their MSRV instead (`rust-release`).

## Lints and formatting
- CI: `cargo fmt --all --check` and `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`.
- `[lints]` as in the workspace example; useful restriction lints: `unwrap_used`, `expect_used`, `dbg_macro`, `print_stdout` (libraries), `undocumented_unsafe_blocks`. Common pedantic allows: `module_name_repetitions`, `missing_errors_doc`, `missing_panics_doc`, `must_use_candidate`.
- Prefer `#[expect(clippy::lint, reason = "...")]` over `#[allow]` — it warns once the suppression is no longer needed.
- rustfmt: keep `rustfmt.toml` minimal; `imports_granularity`/`group_imports` are unstable (nightly rustfmt only).

## Review checklist
- [ ] Builds with `--locked`; fmt and clippy clean with `-D warnings`; edition/MSRV declared and checked.
- [ ] New dependencies justified; `cargo deny check` and `cargo audit` pass; no secrets in logs.
- [ ] Performance claims backed by a benchmark table (`cpu-performance`).
- [ ] Each loaded module's Verify items hold (errors, async, unsafe, tests, features/API).

## Verify
```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo deny check && cargo audit
```
Plus the Verify block of every module the change touched (tests: `rust-testing`; MSRV and features: `rust-release`; Miri: `rust-unsafe-ffi`).

## Deliverables / Report
- Files changed and why; the commands above with their decisive output lines (pass/fail counts, lint count).
- Edition, MSRV and toolchain; new dependencies with version, license and reason.
- For performance work: before/after benchmark table with the build profile used.
- Residual risks: untested feature combinations, unsafe not covered by Miri, platform-specific paths not exercised.
