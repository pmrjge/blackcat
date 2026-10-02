---
name: wasm
description: Load before targeting WebAssembly — Wasm 3.0, WASI, components, wasmtime, browser interop.
---
# WebAssembly

Baseline: `compiler-engineering`. Rust: `rust-engineering`; front end: `frontend-frameworks`, `typescript-engineering`.

## Standards and versions
- Wasm 3.0 is the live standard since 2025-09-17: memory64, multiple memories, GC (structs/arrays), typed function references, tail calls, exception handling, relaxed SIMD, JS string builtins — Verified 2026-10-02 https://webassembly.org/news/2025-09-17-wasm-3.0/ (engine support varies: check each runtime's feature table).
- WASI 0.3 (native async in the component model: `future`/`stream`/`async func`) released 2026-06-11, 0.3.1 on 2026-08-11; WASI 0.2 (wasi:io pollables) remains widely deployed — Verified 2026-10-02 https://github.com/WebAssembly/WASI/releases
- wasmtime 49.0.1 (has WASI 0.3 support; which parts are on by default is unverified — check `wasmtime run --help` / `-W`/`-S` flags) — Verified 2026-10-02 https://github.com/bytecodealliance/wasmtime/releases/latest
- wasm-tools 1.261.0, wit-bindgen 0.62.0, jco 1.35.0 (components in JS) — Verified 2026-10-02 https://github.com/bytecodealliance/wasm-tools/releases/latest https://github.com/bytecodealliance/wit-bindgen/releases/latest https://github.com/bytecodealliance/jco/releases/latest
- wasm-bindgen 0.2.129, Binaryen version_133 (`wasm-opt`), Emscripten 6.0.10 — Verified 2026-10-02 https://github.com/wasm-bindgen/wasm-bindgen/releases/latest https://github.com/WebAssembly/binaryen/releases/latest https://github.com/emscripten-core/emscripten/releases/latest

## Choosing a target
| goal | target |
|---|---|
| Rust in the browser with JS glue | `wasm32-unknown-unknown` + wasm-bindgen (`wasm-pack` or trunk) |
| C/C++ in the browser (with POSIX-ish libc, filesystem emulation) | Emscripten |
| server-side/plugins/sandboxing, language-neutral interfaces | WASI components (`wasm32-wasip2`, WIT interfaces, wit-bindgen) run in wasmtime/WAMR/wasmer |
| your own language | emit Wasm directly (wasm-encoder, Binaryen API) — Wasm GC for managed languages instead of shipping your own GC |

## Rules
- Interfaces between host and guest in WIT (components) or a small, explicit ABI; strings and buffers cross via linear memory with clear ownership (who allocates, who frees).
- Size: release builds with LTO, `opt-level = "z"`/`"s"`, `panic = "abort"`, then `wasm-opt -Oz` (or `-O3` for speed); check with `twiggy` (Rust) or `wasm-tools objdump`.
- Performance: minimize JS↔Wasm boundary crossings (batch work), avoid copying large buffers (views into memory), SIMD (`simd128`) when the engines in scope support it; threads need cross-origin isolation (COOP/COEP headers) in browsers.
- Sandboxing: capabilities are explicit — preopen only needed directories, grant no network unless needed; set fuel/epoch interruption and memory limits for untrusted guests in wasmtime.
- Determinism: avoid relaxed SIMD and NaN-bit dependence where reproducibility matters; Wasm's deterministic profile exists for that.
- Debugging: DWARF in Wasm (`-g`), Chrome DevTools C/C++ DWARF extension, `wasmtime run -D debug-info`, `wasm-tools print`/`validate`.

## Commands
```bash
cargo build --target wasm32-wasip2 --release && wasmtime run target/wasm32-wasip2/release/app.wasm
wasm-tools validate --features all app.wasm && wasm-tools component wit app.wasm   # inspect a component's interface
wasm-opt -Oz in.wasm -o out.wasm
```

## Pitfalls
Mixing preview1 core modules and components without adapters; assuming a Wasm 3.0 feature works in every engine; huge binaries from debug builds or formatting machinery; leaking memory across the boundary; missing COOP/COEP for threads; trusting guest code with ambient authority.

## Verify
`wasm-tools validate` passes · runs in each target engine (wasmtime and the browsers in scope) · size and boundary-crossing costs measured · capability grants listed for WASI guests · toolchain versions reported.
