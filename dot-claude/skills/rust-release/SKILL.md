---
name: rust-release
description: Use when preparing a Rust crate or binary for release — feature flags, MSRV, public API checks, release profiles, cross-compiling.
---
# Rust release builds and API policy

Part of `rust-engineering` (baseline, layout, lints). `.app` bundles, universal binaries and signing: `macos-app-distribution`. The 1.90 claims (LLD default on `x86_64-unknown-linux-gnu`, `x86_64-apple-darwin` Tier 2 with host tools): Verified 2026-10-02 https://blog.rust-lang.org/2025/09/18/Rust-1.90.0/. The 1.77 strip claim: unverified (checked when written, Sep 2026).

## Features, MSRV, public API
- **Features** are additive and unified across the graph: never mutually exclusive features; optional deps via `dep:` (`[features] serde = ["dep:serde"]`); keep library defaults small; depend on heavy crates with `default-features = false`; test combinations with `cargo hack check --each-feature --no-dev-deps`.
- **MSRV policy**: declare `rust-version`; raising it is at least a minor-version bump for libraries; CI job on the MSRV toolchain (`cargo +1.85 check --workspace`, or `cargo msrv verify`). Resolver 3 falls back to dependency versions compatible with `rust-version`.
- Public API: minimal surface, `pub(crate)` by default, re-export types that appear in public signatures, `#[non_exhaustive]` on enums/structs expected to grow. Libraries: `cargo-semver-checks` before a release.

## Release profiles
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

## Cross-compilation
| Target | How |
|---|---|
| `aarch64-apple-darwin` (Tier 1) | Native on the Mac. Minimum OS via `MACOSX_DEPLOYMENT_TARGET` (default 11.0) — must equal the app's `LSMinimumSystemVersion` |
| `x86_64-apple-darwin` (Tier 2 with host tools since 1.90) | `rustup target add x86_64-apple-darwin`, `cargo build --release --target x86_64-apple-darwin`; universal binary with `lipo` (see `macos-app-distribution`) |
| `x86_64-unknown-linux-gnu` | Native on the Linux laptop (LLD is the default linker since 1.90); from the Mac: `cargo zigbuild --release --target x86_64-unknown-linux-gnu.2.17` (needs `zig`; suffix = glibc floor); `cross` uses containers on Linux hosts |
| Static Linux CLI | `x86_64-unknown-linux-musl` (musl's allocator is slow — pair with mimalloc) |
| Linux → macOS | Don't: the macOS SDK is licensed for Apple hardware — build on the Mac or a macOS CI runner |

## Verify
- [ ] Features additive (`cargo hack --each-feature`); public API minimal, documented, `#[non_exhaustive]` where it will grow; the MSRV build passes.
```sh
cargo hack check --each-feature --no-dev-deps
cargo +1.85 check --workspace          # MSRV (rustup toolchain install 1.85 first)
cargo semver-checks                    # libraries, before a release
cargo build --release --locked --target <each shipped target>
```
