---
name: compiler-ir-llvm
description: Load for IR and LLVM work — SSA design, emitting LLVM IR, pass pipelines, writing passes, MLIR, llvmlite/inkwell, miscompile hunting.
---
# IR design, optimization and LLVM

Baseline: `compiler-engineering`. Backends and JITs: `compiler-backend-jit`; C++ builds: `cmake-ninja-builds`.

## Versions
- LLVM 23.1.2 (new major every ~6 months; the C++ API is not stable across majors — pin it) — Verified 2026-10-02 https://github.com/llvm/llvm-project/releases/latest
- llvmlite 0.50.0 (Python bindings, pinned to one LLVM major) — Verified 2026-10-02 https://pypi.org/project/llvmlite/
- Rust: inkwell (safe wrapper, feature flag per LLVM major) or llvm-sys; check the crate's supported LLVM versions.
- macOS: Homebrew `llvm` is keg-only (`$(brew --prefix llvm)/bin`); Apple clang is not upstream LLVM — use the matching `llvm-config`.

## IR design
- SSA with basic blocks and block arguments (or phi nodes); explicit control-flow graph; typed values; side effects and memory explicit (effects or memory SSA).
- Multiple levels when the language needs them (high-level IR with language constructs → mid-level SSA → LLVM IR); MLIR when you want reusable dialects and progressive lowering.
- Every pass: documented preconditions/postconditions, a verifier run after it in debug builds, and a pretty-printer for golden tests.

## Generating LLVM IR
- Emit allocas for locals in the entry block and let `mem2reg`/SROA build SSA — simpler than constructing phis yourself.
- Use the new pass manager pipelines (`-passes='default<O2>'`); custom pipelines only with a reason.
- Target triple and data layout set from the target machine; ABI lowering (struct passing, varargs) follows the platform ABI — copy clang's lowering for C interop (compile a C sample with `clang -S -emit-llvm` and compare).
- Debug info (DWARF via DIBuilder) from the spans, so `lldb`/`gdb` can step generated code.
- Undefined behavior in LLVM IR (`nsw`/`nuw`, `poison`, `undef`, `noalias`, `inbounds`) only when the source language guarantees it; otherwise the optimizer will miscompile valid programs.

## Tools
`opt -passes=… -S in.ll`, `llc -O2 in.ll -o out.s`, `llvm-as`/`llvm-dis`, `opt -passes=verify`, `-print-after-all`/`-print-changed` to see which pass changed what, `llvm-mca` for throughput estimates, `lit` + `FileCheck` for IR tests, `llvm-reduce` and `bugpoint` to minimize failing inputs, Alive2 (`alive-tv`) to check a transformation is a refinement.

## Writing optimization passes
- Start from analyses (dominators, loop info, alias analysis, scalar evolution); invalidate/preserve analyses correctly.
- Prove or test each rewrite: Alive2 for peephole transforms in LLVM IR, property/differential tests (random programs through the pass vs without) for your own IR.
- Keep passes idempotent and terminating (fixed-point loops with bounds).

## Miscompile hunting
Read `references/miscompile-hunting.md` when optimized output differs from unoptimized or from the reference interpreter.

## Pitfalls
Phi nodes without entries for every predecessor; values used outside their dominance region; mismatched data layout; ABI mismatches at C boundaries; relying on `undef` behavior; mixing LLVM majors between headers, libraries and the tools used in tests.

## Verify
IR verifier passes after every pass in debug builds · lit/FileCheck tests for each pass · differential testing O0 vs O2 vs interpreter on generated programs · LLVM version and pipeline reported.
