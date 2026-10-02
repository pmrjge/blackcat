---
name: fm-rust-kani-miri
description: Use for showing Rust free of panics, overflow or UB — Kani bounded proofs, Miri, loom, sanitizers.
---
# Rust: Kani, Miri, loom
Hub: `formal-methods` (tool choice, what each result guarantees — §7, report table). Tool versions and commands were checked earlier without recorded URLs: unverified as of 2026-10-02 unless a Sources line says otherwise.

Kani (bounded model checking, CBMC backend). Install: `cargo install --locked kani-verifier && cargo kani setup` (Linux x86-64, macOS Intel and Apple Silicon).
```rust
pub fn midpoint(lo: u32, hi: u32) -> u32 { lo + (hi - lo) / 2 }

#[cfg(kani)]
mod proofs {
    use super::*;
    #[kani::proof]
    fn midpoint_in_range() {
        let (lo, hi): (u32, u32) = (kani::any(), kani::any());
        kani::assume(lo <= hi);
        let m = midpoint(lo, hi);
        assert!(lo <= m && m <= hi);
    }
}
```
- Run `cargo kani` (all harnesses) or `cargo kani --harness midpoint_in_range`; loops need `#[kani::unwind(N)]` or `--default-unwind N` — unwinding assertions fail loudly when N is too small; `-Z concrete-playback --concrete-playback=print` turns a counterexample into a unit test; defaults go in `[package.metadata.kani.flags]`.
- Checked automatically: panics (assert, unwrap, expect, indexing), arithmetic overflow, division by zero, oversized shifts, invalid pointer dereferences. Limits: bounded inputs and loops, heavy heap/large arrays get slow, no concurrency; contracts, stubbing and loop invariants are experimental (see `cargo kani --help` for the unstable flags).
- Plain `cargo build` warns `unexpected cfg condition name: kani` (likewise `loom`); declare them: `[lints.rust] unexpected_cfgs = { level = "warn", check-cfg = ['cfg(kani)', 'cfg(loom)'] }`.

Miri (interpreter that detects UB): `rustup +nightly component add miri`, then `cargo +nightly miri test`. Detects out-of-bounds and use-after-free, uninitialized reads, invalid values, misalignment, data races, Stacked/Tree Borrows aliasing violations, leaks. Flags via `MIRIFLAGS`: `-Zmiri-tree-borrows`, `-Zmiri-many-seeds` (explore schedules and nondeterminism), `-Zmiri-strict-provenance`, `-Zmiri-disable-isolation` (host env/files). Cross-check endianness with `cargo +nightly miri test --target s390x-unknown-linux-gnu`. No FFI; only the executed paths.

loom: write the test against `loom::sync`/`loom::thread` inside `loom::model(|| { ... })`, gate with `#[cfg(loom)]`, run `RUSTFLAGS="--cfg loom" cargo test --release`; keep tests to 2–3 threads and a few operations. shuttle randomizes schedules for larger tests. Sanitizers (nightly): `RUSTFLAGS="-Zsanitizer=address" cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu` (thread sanitizer likewise; `-Zbuild-std` needs the `rust-src` component and an instrumented std avoids TSan false positives).

## Verify
- [ ] Every `kani::assume` and unwind bound listed; unwinding assertions pass.
- [ ] A seeded bug (e.g. `lo + hi` overflow) is caught by the harness.
- [ ] Miri run with the flags used (`MIRIFLAGS`) recorded; only executed paths claimed.
- [ ] Toolchain (nightly date), Kani and loom versions recorded.
