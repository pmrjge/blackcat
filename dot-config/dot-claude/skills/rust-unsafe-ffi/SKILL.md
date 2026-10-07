---
name: rust-unsafe-ffi
description: Use for unsafe Rust and C FFI — SAFETY comments, edition-2024 unsafe rules, raw pointers, Miri.
---
# Unsafe Rust and FFI

Part of `rust-engineering` (baseline, layout, lints).

## Unsafe policy
- Default `unsafe_code = "forbid"` in `[lints.rust]` for crates that need none. Otherwise isolate unsafe in small modules behind safe APIs.
- Every `unsafe` block gets a `// SAFETY:` comment naming the invariant; every `unsafe fn` gets a `# Safety` doc section (clippy `undocumented_unsafe_blocks`, `missing_safety_doc`).
- Edition 2024: `unsafe_op_in_unsafe_fn` warns (set it to deny), `extern` blocks must be `unsafe extern`, `#[unsafe(no_mangle)]`/`#[unsafe(export_name = ..)]`, references to `static mut` are denied (`static_mut_refs`) — use atomics, `Mutex`, `&raw const`/`&raw mut`.
- Miri: `rustup +nightly component add miri`, then `cargo +nightly miri test -p <crate>` — catches out-of-bounds, use-after-free, aliasing violations, data races, uninitialized reads; it can't run FFI and is slow, so target the unsafe modules. Sanitizers (`-Zsanitizer=address|thread`) are nightly-only.

## FFI
- `#[repr(C)]`, bindgen/cbindgen, never unwind across `extern "C"` (use `extern "C-unwind"` when unwinding is intended), document ownership of every pointer.

## Verify
- [ ] Unsafe minimal, each block justified with SAFETY, Miri run on the affected tests.
```sh
cargo clippy --workspace --all-targets -- -D clippy::undocumented_unsafe_blocks -D clippy::missing_safety_doc
cargo +nightly miri test -p <crate-with-unsafe>
```
