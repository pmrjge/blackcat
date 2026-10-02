---
name: compiler-backend-jit
description: Load before codegen, JIT or runtime work — Cranelift, regalloc, interpreters, GC, ABIs.
---
# Backends, JITs, interpreters and runtimes

Baseline: `compiler-engineering`. LLVM-based backends: `compiler-ir-llvm`; WebAssembly: `wasm`; CPU measurement: `cpu-performance`.

## Choosing a backend
| need | backend |
|---|---|
| best peak performance, AOT, many targets | LLVM |
| fast compile times, JIT, safety-focused codebase in Rust | Cranelift (part of the wasmtime project; wasmtime 49.0.1 — Verified 2026-10-02 https://github.com/bytecodealliance/wasmtime/releases/latest) |
| portability with minimal effort | compile to C (then any C compiler) or to WebAssembly |
| dynamic language, startup matters | bytecode interpreter first, then a baseline JIT, then an optimizing tier |
| own native backend for learning or tight control | instruction selection by tree/DAG tiling, linear-scan register allocation, one target first |

## Interpreters
- Bytecode VM: compact instruction encoding, register-based or stack-based (register VMs execute fewer instructions; stack VMs are simpler to emit); dispatch via `match` in a loop, computed goto (C/C++), or tail-call dispatch (`[[clang::musttail]]`, Rust `become` when stable).
- Values: tagged representations (NaN-boxing, pointer tagging) documented with their invariants; small-integer fast paths.
- Inline caches for property lookup and calls in dynamic languages; shapes/hidden classes for objects.
- Profile with `perf`/samply on representative programs; measure instructions per bytecode.

## JIT essentials
- Executable memory: map RW, write code, flip to RX (W^X); on Apple silicon use `MAP_JIT` + `pthread_jit_write_protect_np` and the JIT entitlement for hardened runtime apps; flush instruction caches on ARM.
- Tiering with profiling counters; deoptimization (bailing back to the interpreter with reconstructed frames) whenever speculation fails — design frame state maps from the start.
- Code invalidation when assumptions change (class shape changes, redefinitions); GC must see JIT frames (stack maps).
- Debugging: register JIT code with perf (`perf map` files, `jitdump`) and debuggers (GDB JIT interface) or nothing will profile.

## Native codegen basics
- Instruction selection from a low-level IR; legalization for types and operations the target lacks.
- Register allocation: linear scan (fast, JITs) or graph coloring/regalloc2-style (better code); spill heuristics, rematerialization, coalescing of moves.
- Calling conventions per platform ABI (SysV x86-64, Windows x64, AAPCS64, Apple arm64 variations): callee-saved registers, stack alignment (16 bytes at calls), red zones, varargs.
- Unwinding info (DWARF CFI, Windows unwind tables) generated for every function if exceptions, backtraces or profilers matter.

## Garbage collection and runtimes
- Choose: reference counting (+ cycle collection), mark–sweep, mark–compact, copying/generational, or arenas/regions; precise GC needs stack maps or a shadow stack; conservative stack scanning is simpler but pins objects.
- Write barriers for generational/incremental collectors; safepoints in loops and calls.
- Stress testing: GC at every allocation (`gc-stress` mode) in tests; heap verification after each collection in debug builds.
- FFI: pin or handle-wrap objects passed to native code; document ownership across the boundary.

## Pitfalls
W^X violations crashing on Apple silicon; stale instruction cache on ARM; missing unwind info breaking exceptions and profilers; GC roots in registers not reported; deopt metadata out of sync with optimized code; calling-convention mismatches at FFI boundaries; benchmarking JITs without warm-up.

## Verify
Differential tests: interpreter vs JIT vs AOT outputs on generated programs · GC stress mode passes · ABI tests calling C and being called from C · benchmarks with warm-up, steady-state and variance reported · perf/debugger can symbolize JIT frames.
