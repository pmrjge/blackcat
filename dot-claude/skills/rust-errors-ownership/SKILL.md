---
name: rust-errors-ownership
description: Use for Rust error types (thiserror, anyhow), panics and borrow-checker fights — ownership patterns; async code is in rust-async.
---
# Rust errors and ownership

Part of `rust-engineering` (baseline, layout, lints). Read `references/compiler-errors.md` when a rustc error code (E0382, E0502, E0277, …) or an edition-2024 migration error needs a fix; `references/crates.md` when choosing or adding a crate.

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

## Verify
- [ ] No `unwrap`/`expect`/`panic` in library paths except documented invariants (`cargo clippy --workspace -- -D clippy::unwrap_used -D clippy::expect_used` on library crates); errors carry context; public error types are matchable.
- [ ] Every new crate passes the checks in `references/crates.md` (maintenance, license, `cargo tree -e normal`, std alternative).
