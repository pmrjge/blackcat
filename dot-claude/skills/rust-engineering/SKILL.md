---
name: rust-engineering
description: Load before writing, reviewing, testing or releasing Rust code — workspaces, edition 2024 and MSRV, features, errors (thiserror/anyhow), ownership patterns, tokio async and cancellation, performance basics, unsafe policy, nextest/proptest/insta/criterion, clippy, tracing, clap, serde, release profiles, cross-compiling for macOS and Linux, crate choices, compiler-error fixes.
---
# Rust engineering

## Scope
- Covers production Rust for libraries, CLIs and services: layout, errors, ownership, async, testing, linting, release builds, crate choice, review.
- Not here: GUI toolkits (`rust-native-gui`), editor internals (`editor-engineering`), `.app` packaging/signing (`macos-app-distribution`), profiling methodology (`cpu-performance`).
- Baseline (Sep 2026): stable Rust 1.98 (6-week cadence — check `rustc -V`); **edition 2024** is current (stable since 1.85); resolver `"3"` (MSRV-aware) is the edition-2024 default. Verify crate APIs on docs.rs or with `mcp__libdocs` before writing version-specific code; crate versions below are from crates.io at the time of writing.

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
- Apps pin the toolchain in `rust-toolchain.toml` (`[toolchain] channel = "1.98"`, `components = ["clippy", "rustfmt"]`); libraries test their MSRV instead.
- **Features** are additive and unified across the graph: never mutually exclusive features; optional deps via `dep:` (`[features] serde = ["dep:serde"]`); keep library defaults small; depend on heavy crates with `default-features = false`; test combinations with `cargo hack check --each-feature --no-dev-deps`.
- **MSRV policy**: declare `rust-version`; raising it is at least a minor-version bump for libraries; CI job on the MSRV toolchain (`cargo +1.85 check --workspace`, or `cargo msrv verify`). Resolver 3 falls back to dependency versions compatible with `rust-version`.
- Public API: minimal surface, `pub(crate)` by default, re-export types that appear in public signatures, `#[non_exhaustive]` on enums/structs expected to grow.

## Error handling
| Code | Use | Pattern |
|---|---|---|
| Library | `thiserror` 2 | One error enum per domain; variants carry context (path, id); `#[from]` only for unambiguous conversions |
| Binary | `anyhow` (or `eyre`/`color-eyre` for rich reports) | `main() -> anyhow::Result<()>`, `.context("reading config")`, `bail!`, `ensure!` |
```rust
#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("config file {path} not found")]
    NotFound { path: PathBuf },
    #[error("invalid config at {path}")]
    Parse { path: PathBuf, #[source] source: serde_json::Error },
    #[error(transparent)]
    Io(#[from] std::io::Error),
}
```
- No `unwrap()`/`expect()`/`panic!` in library code except provable invariants: `expect("index checked above")` states why it holds. Enforce with clippy `unwrap_used`/`expect_used`, plus `allow-unwrap-in-tests = true` and `allow-expect-in-tests = true` in `clippy.toml`.
- Put the source either in the message (`{0}`) or in `#[source]`, not both — otherwise report chains print it twice. Messages: lowercase, no trailing period.
- Don't erase library errors into `Box<dyn Error>`/`anyhow` at API boundaries; callers need to match.
- Panics are for bugs. With `panic = "abort"` there is no unwinding: the process aborts before `catch_unwind` can catch anything, and destructors don't run.

## Ownership patterns that avoid borrow-checker fights
| Situation | Pattern |
|---|---|
| Graphs, trees with parent links, ASTs | Arena + typed indices (`Vec<Node>` + `struct NodeId(u32)`); `slotmap` when nodes are removed (generational keys). Avoid `Rc<RefCell<_>>` graphs |
| Mutate two elements of one collection | `split_at_mut`, `get_disjoint_mut` (slices, `HashMap`), or index-based updates |
| Mutating while iterating | Two phases (collect keys/indices, then apply), `retain`/`retain_mut`, `extract_if` |
| Sometimes-borrowed, sometimes-owned text | `Cow<'_, str>` |
| Shared read-mostly config/state | `Arc<T>`; hot-swappable snapshot: `arc-swap` |
| Shared mutable state across threads | Prefer one owning task/thread + channel (actor); else `Arc<Mutex<T>>` with short critical sections |
| Single-thread interior mutability | `Cell` (Copy types), `RefCell` (runtime-checked, panics on double borrow), `OnceCell` |
| Lazy globals | `std::sync::LazyLock`/`OnceLock` (no `lazy_static`/`once_cell` in new code) |
| Struct that stores data and a reference into it | Restructure: store ranges/indices into owned data |
| Lifetimes spreading through APIs | Long-lived structs own their data; functions borrow (`&str`, `&[T]`, `impl AsRef<Path>`) |
| Borrowed data in threads | `std::thread::scope` instead of `'static` + clones |
`Rc` is not `Send`; `Arc` costs an atomic increment per clone — clone handles outside hot loops.

## Async with tokio
- Runtime: `#[tokio::main]` (multi-thread) for servers; `#[tokio::main(flavor = "current_thread")]` for CLIs and simple tools; `#[tokio::test]` is current-thread by default. Enable only the features used (`rt-multi-thread`, `macros`, `sync`, `time`, `io-util`, `net`, `process`, `fs`, `signal`). Never create or `block_on` a runtime inside async code ("Cannot start a runtime from within a runtime").
- Blocking: no blocking I/O, `std::thread::sleep` or long CPU work between `.await`s (rule of thumb: ≤ 10–100 µs). Use `tokio::task::spawn_blocking` (can't be aborted — pass a flag/token into the closure) or rayon + a `oneshot` for CPU-parallel work.
- Cancellation: dropping a future cancels it at its current `.await`. `select!` drops the losing branches, so in loops use cancel-safe operations only: `mpsc`/`broadcast` `recv`, `watch::changed`, `AsyncReadExt::read`, `AsyncWriteExt::write`, `StreamExt::next`, `accept`. Not cancel-safe: `read_exact`, `read_to_end`, `read_to_string`, `write_all` (data loss); `Mutex::lock`, `RwLock::read`/`write`, `Semaphore::acquire`, `Notify::notified` (lose their queue position).
- Structured concurrency: `JoinSet` (aborts its tasks on drop), `tokio_util::sync::CancellationToken` (`child_token()` per subtask), `tokio_util::task::TaskTracker` to await shutdown. No fire-and-forget `tokio::spawn` without a handle; surface `JoinError` (panic/abort).
```rust
let cancel = CancellationToken::new();
let mut set = JoinSet::new();
for id in 0..n { set.spawn(job(id, cancel.child_token())); }
let deadline = tokio::time::sleep(Duration::from_secs(30)); // created once, outside the loop
tokio::pin!(deadline);
let ctrl_c = tokio::signal::ctrl_c();
tokio::pin!(ctrl_c);
loop {
    tokio::select! {
        // guards: re-polling a completed future panics ("resumed after completion")
        _ = &mut ctrl_c, if !cancel.is_cancelled() => cancel.cancel(),
        () = &mut deadline, if !cancel.is_cancelled() => cancel.cancel(),
        next = set.join_next() => match next {
            Some(Ok(Ok(id))) => tracing::info!(id, "done"),
            Some(Ok(Err(e))) => tracing::warn!(error = %e, "job failed"),
            Some(Err(join_err)) => return Err(join_err.into()),
            None => break,
        },
    }
}
```
- Channels: `mpsc` bounded (backpressure; unbounded only when the producer rate is bounded), `oneshot` (request/reply), `broadcast` (fan-out; slow receivers get `Lagged`), `watch` (latest value), `Semaphore` (concurrency limit), `Notify`.
- Locks: a `std::sync::Mutex` guard must not live across `.await` (clippy `await_holding_lock`); use `tokio::sync::Mutex` only when holding across `.await` is unavoidable. Timeouts: `tokio::time::timeout`.
- `async fn` in traits is stable but not dyn-compatible; for `dyn` use the `async-trait` crate or return boxed futures. "future cannot be sent between threads safely" = a `!Send` value (`Rc`, `RefCell` borrow, std `MutexGuard`) lives across an `.await` — scope it in a block that ends before the await.
- Diagnose stalls with `tokio-console` (`console-subscriber`, build with `RUSTFLAGS="--cfg tokio_unstable"`).

## Performance basics
Measure first (criterion/divan, `--release`); deep profiling workflow is in `cpu-performance`.
- Allocation: `Vec::with_capacity`, reuse buffers (`clear()`), borrow slices instead of cloning in hot paths, `SmallVec` for small bounded sizes, `bumpalo` for per-frame/per-request arenas.
- Iterators compile to tight loops; `chunks_exact` and slice iteration remove bounds checks and help auto-vectorization.
- Hashing: std `HashMap` uses DoS-resistant SipHash; for trusted keys use `rustc-hash` (`FxHashMap`) or `foldhash` (hashbrown's default).
- Parallelism: rayon `par_iter()` for data-parallel CPU work; don't run rayon on tokio worker threads directly.
- SIMD: check auto-vectorization first; `std::arch` intrinsics with runtime detection (`is_x86_feature_detected!`, `std::arch::is_aarch64_feature_detected!`); portable wrappers `wide`, `pulp`; `multiversion` for per-CPU clones; `std::simd` is nightly-only. `-C target-cpu=native` only for binaries that run on the build machine.
- Global allocator: `mimalloc` or `tikv-jemallocator` for allocation-heavy multithreaded code — keep only if a benchmark shows a win.

## Unsafe policy
- Default `unsafe_code = "forbid"` in `[lints.rust]` for crates that need none. Otherwise isolate unsafe in small modules behind safe APIs.
- Every `unsafe` block gets a `// SAFETY:` comment naming the invariant; every `unsafe fn` gets a `# Safety` doc section (clippy `undocumented_unsafe_blocks`, `missing_safety_doc`).
- Edition 2024: `unsafe_op_in_unsafe_fn` warns (set it to deny), `extern` blocks must be `unsafe extern`, `#[unsafe(no_mangle)]`/`#[unsafe(export_name = ..)]`, references to `static mut` are denied (`static_mut_refs`) — use atomics, `Mutex`, `&raw const`/`&raw mut`.
- Miri: `rustup +nightly component add miri`, then `cargo +nightly miri test -p <crate>` — catches out-of-bounds, use-after-free, aliasing violations, data races, uninitialized reads; it can't run FFI and is slow, so target the unsafe modules. Sanitizers (`-Zsanitizer=address|thread`) are nightly-only.
- FFI: `#[repr(C)]`, bindgen/cbindgen, never unwind across `extern "C"` (use `extern "C-unwind"` when unwinding is intended), document ownership of every pointer.

## Testing
- Unit tests in `#[cfg(test)] mod tests` (private access); integration tests in `tests/*.rs` (public API; shared helpers in `tests/common/mod.rs`); doc examples double as tests.
- `cargo nextest run --workspace` (process per test, retries, better output) — nextest does not run doctests, so also run `cargo test --doc`.
- `proptest` for parsers, codecs, invariants (round-trips, idempotence); commit `proptest-regressions/`.
- `insta` snapshots: `assert_snapshot!`, `assert_debug_snapshot!`, `assert_json_snapshot!` (feature `json`); review with `cargo insta review`; in CI insta detects `CI` and fails on mismatches instead of writing (`INSTA_UPDATE=no` forces it).
- `criterion` 0.8: `benches/foo.rs` + `[[bench]] name = "foo" harness = false`; use `std::hint::black_box`; compare with `--save-baseline main` / `--baseline main`. `divan` is a lighter alternative.
- Coverage: `cargo llvm-cov` (`cargo llvm-cov nextest`). Fuzz parsers with `cargo fuzz` (nightly). Concurrency primitives: `loom`.

## Lints and formatting
- CI: `cargo fmt --all --check` and `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`.
- `[lints]` as in the workspace example; useful restriction lints: `unwrap_used`, `expect_used`, `dbg_macro`, `print_stdout` (libraries), `undocumented_unsafe_blocks`. Common pedantic allows: `module_name_repetitions`, `missing_errors_doc`, `missing_panics_doc`, `must_use_candidate`.
- Prefer `#[expect(clippy::lint, reason = "...")]` over `#[allow]` — it warns once the suppression is no longer needed.
- rustfmt: keep `rustfmt.toml` minimal; `imports_granularity`/`group_imports` are unstable (nightly rustfmt only).

## Logging and tracing
- Libraries emit `tracing` events/spans and never install a subscriber. Binaries: `tracing_subscriber::fmt().with_env_filter(EnvFilter::from_default_env()).init()` (feature `env-filter`), `RUST_LOG=info,my_crate=debug`; `.json()` needs feature `json`; file rotation via `tracing-appender`.
- `#[tracing::instrument(skip(large_arg), fields(user = %id), err)]` on I/O boundaries; structured fields (`%` Display, `?` Debug). Never log secrets or full request bodies.

## CLI and serialization
- clap 4 derive: `#[derive(Parser)] #[command(version, about)]`, doc comments become help, `#[arg(short, long, env = "APP_X")]` (feature `env`), `#[derive(Subcommand)]`, `#[derive(ValueEnum)]`; completions via `clap_complete`. Data to stdout, logs to stderr; return `std::process::ExitCode`; decide colors with `std::io::IsTerminal`. Rust ignores SIGPIPE, so `println!` panics when piped into `head` — write through a locked `stdout` and treat `ErrorKind::BrokenPipe` as success.
- serde: `#[serde(rename_all = "camelCase")]`, `deny_unknown_fields` for config, `default`, `skip_serializing_if = "Option::is_none"`, `#[serde(tag = "type")]` for tagged enums (`untagged` gives poor errors). Version persisted formats explicitly.
- Formats: `serde_json`, `toml`, `csv`, `postcard` (compact, stable wire format), `rkyv` (zero-copy). Avoid: `bincode` 3.0 (a deliberate `compile_error!` tombstone — the project stopped), `serde_yaml` (deprecated; if YAML is unavoidable, check the currently maintained option — `serde-saphyr` is the active one at the time of writing).

## Release profiles and cross-compilation
```toml
[profile.release]
lto = "thin"            # "fat"/true: slower link, sometimes faster code
codegen-units = 1       # better optimization, slower build
panic = "abort"         # smaller/faster; no unwinding (tests ignore this setting)
strip = true            # all symbols; since 1.77 profiles without debuginfo already strip debuginfo
[profile.profiling]     # cargo build --profile profiling
inherits = "release"
debug = "line-tables-only"
strip = false
[profile.dev.package."*"]
opt-level = 2           # faster dev builds of heavy dependencies
```
Keep symbols for crash reports: `split-debuginfo = "packed"` plus `debug = "line-tables-only"` or higher (a `.dSYM` on macOS; with no debuginfo none is written) and archive it per release. Size-critical: `opt-level = "z"`.
| Target | How |
|---|---|
| `aarch64-apple-darwin` (Tier 1) | Native on the Mac. Minimum OS via `MACOSX_DEPLOYMENT_TARGET` (default 11.0) — must equal the app's `LSMinimumSystemVersion` |
| `x86_64-apple-darwin` (Tier 2 with host tools since 1.90) | `rustup target add x86_64-apple-darwin`, `cargo build --release --target x86_64-apple-darwin`; universal binary with `lipo` (see `macos-app-distribution`) |
| `x86_64-unknown-linux-gnu` | Native on the Linux laptop (LLD is the default linker since 1.90); from the Mac: `cargo zigbuild --release --target x86_64-unknown-linux-gnu.2.17` (needs `zig`; suffix = glibc floor); `cross` uses containers on Linux hosts |
| Static Linux CLI | `x86_64-unknown-linux-musl` (musl's allocator is slow — pair with mimalloc) |
| Linux → macOS | Don't: the macOS SDK is licensed for Apple hardware — build on the Mac or a macOS CI runner |

## Crate selection (well-established choices)
| Need | Crate |
|---|---|
| Errors | `thiserror` (lib), `anyhow` / `color-eyre` (bin) |
| Async, HTTP | `tokio`, `tokio-util`, `futures`; client `reqwest`; server `axum` (on `hyper` 1) |
| CLI, terminal UX | `clap`, `indicatif`, `dialoguer`, `ratatui`/`crossterm` |
| Logging | `tracing`, `tracing-subscriber`, `tracing-appender` |
| Data parallel, channels | `rayon`; `crossbeam-channel` (sync), `tokio::sync` (async) |
| Concurrency state | std `Mutex`/`RwLock` (`parking_lot` optional), `dashmap`, `arc-swap` |
| Collections, hashing | `indexmap`, `smallvec`, `slotmap`, `hashbrown`, `rustc-hash`, `foldhash` |
| Text/bytes | `regex`, `memchr`, `aho-corasick`, `bytes`, `bstr`, `compact_str` |
| Time, IDs, random | `jiff` (tz-aware) or `chrono`/`time`; `uuid`; `rand` (0.9+ API: `rand::rng()`, `random()`) |
| Files | `walkdir`, `ignore` (gitignore-aware), `tempfile`, `notify`, `memmap2`, `camino`, `directories` |
| Databases | `rusqlite` (SQLite), `sqlx` (async, compile-time checked SQL) |
| Test/bench | `proptest`, `insta`, `criterion`/`divan`, `cargo-nextest`, `cargo-llvm-cov` |
| Supply chain | `cargo-deny` (licenses, advisories, bans, sources), `cargo-audit`, `cargo-semver-checks` (libs), `cargo-machete`, `cargo-hack` |
Before adding any crate: maintenance (recent releases, open advisories on RustSec), license compatible with the project, transitive dependency count (`cargo tree -e normal`), and whether std already covers it (`LazyLock`, `IsTerminal`, `std::thread::scope`).

## Compiler errors → idiomatic fixes
| Error | Fix |
|---|---|
| E0382 use of moved value | Borrow (`&x`, `for x in &v`), clone deliberately, or restructure ownership |
| E0499 / E0502 conflicting borrows | Shorten the borrow, split borrows (disjoint fields, `split_at_mut`, `get_disjoint_mut`), indices, two-phase update |
| E0505 move while borrowed | End the borrow first; clone only the part needed |
| E0507 move out of borrowed content | `clone()`, `std::mem::take`/`replace`, `Option::take`, match on `&self.x`, `as_ref()`/`as_deref()` |
| E0597 / E0716 does not live long enough / temporary dropped | Bind the temporary with `let`; return owned data; widen the owner's scope |
| E0106 missing lifetime | Return owned, or tie output to one input: `fn f<'a>(s: &'a str) -> &'a str` |
| E0373 closure may outlive borrowed value | `move` + `Arc`/clone, or `std::thread::scope` |
| E0277 not `Send`/`Sync`, "future cannot be sent" | `Arc`/`Mutex` instead of `Rc`/`RefCell`; drop `!Send` values before `.await`; current-thread runtime/`spawn_local` |
| E0308 mismatched types | `as_deref()`, `as_ref()`, `&*s`, `.into()`; check `&String` vs `&str`, `Option<&T>` vs `&Option<T>` |
| E0599 method not found | Import the trait (`std::io::Write`, `futures::StreamExt`), add the trait bound, enable the crate feature |
| E0038 trait not dyn compatible | `where Self: Sized` on generic methods, enum dispatch, or generics instead of `dyn` |
| Edition 2024 migration | `cargo fix --edition`; `gen` is reserved (`r#gen`); RPIT captures all in-scope lifetimes — narrow with `+ use<'a, T>` |

## Review checklist
- [ ] Builds with `--locked`; fmt and clippy clean with `-D warnings`; edition/MSRV declared and checked.
- [ ] No `unwrap`/`expect`/`panic` in library paths except documented invariants; errors carry context; public error types are matchable.
- [ ] Features additive (`cargo hack --each-feature`); public API minimal, documented, `#[non_exhaustive]` where it will grow.
- [ ] Async: no blocking between awaits, no std lock guards across awaits, cancel-safe `select!`, every spawned task joined or tracked, shutdown path tested.
- [ ] Unsafe minimal, each block justified with SAFETY, Miri run on the affected tests.
- [ ] Tests cover new behavior (unit + integration + doc); property tests for parsers/invariants; snapshot diffs reviewed.
- [ ] New dependencies justified; `cargo deny check` and `cargo audit` pass; no secrets in logs.
- [ ] Performance claims backed by a benchmark table (`cpu-performance`).

## Verify
```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo nextest run --workspace --all-features --locked && cargo test --doc --workspace
cargo hack check --each-feature --no-dev-deps
cargo +1.85 check --workspace          # MSRV (rustup toolchain install 1.85 first)
cargo deny check && cargo audit
cargo +nightly miri test -p <crate-with-unsafe>
```

## Deliverables / Report
- Files changed and why; the commands above with their decisive output lines (pass/fail counts, lint count).
- Edition, MSRV and toolchain; new dependencies with version, license and reason.
- For performance work: before/after benchmark table with the build profile used.
- Residual risks: untested feature combinations, unsafe not covered by Miri, platform-specific paths not exercised.
