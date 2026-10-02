# Rust crate selection (well-established choices)

Crate versions in the Rust skills are from crates.io at the time of writing. Verified 2026-10-02 https://crates.io/api/v1/crates/<name>: thiserror 2.0.21, tokio 1.53.1, clap 4.6.7, criterion 0.8.2, rand 0.10.3 (the 0.9+ API note below predates 0.10 — unverified for 0.10).

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
