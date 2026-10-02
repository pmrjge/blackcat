---
name: compiler-engineering
description: Use for compilers, interpreters and language tools — phases, testing; module map from parsing to Wasm.
---
# Compiler engineering (hub)

## Scope
Languages, DSLs, interpreters, compilers and their tooling. Editor/LSP integration: `editor-engineering`; algorithms: `algorithm-design`; proofs about type systems: `proof-craft`, `lean-formalization`; fuzzing: `test-fuzzing`; host languages: `rust-engineering`, `cpp-engineering`, `haskell-engineering`.

## Modules
| module | load when |
|---|---|
| `compiler-frontend` | lexing, parsing (hand-written, combinators, generators, tree-sitter), ASTs, error recovery, diagnostics |
| `compiler-types` | name resolution, type checking and inference, generics, traits, soundness tests |
| `compiler-ir-llvm` | IR design, SSA, optimization passes, LLVM IR/MLIR, llvmlite/inkwell, debugging miscompiles |
| `compiler-backend-jit` | instruction selection, register allocation, Cranelift, JITs, interpreters, GC and runtimes |
| `wasm` | WebAssembly targets, WASI, component model, wasmtime, browser interop, wasm tooling |

## Baseline rules
- Pipeline with explicit phases and data types between them (source → tokens → CST/AST → resolved/typed AST → IR → optimized IR → code); each phase testable alone.
- Spans everywhere: every node and IR value traceable to a source range; diagnostics point at code, say what was expected and suggest a fix.
- Tests first-class:
  - golden/snapshot tests for parser output, diagnostics and IR (`insta`, lit + FileCheck, expect tests), reviewed on change;
  - end-to-end tests that compile and run programs and compare outputs;
  - differential tests against a reference implementation or interpreter;
  - fuzzing of parsers and the whole compiler (grammar-aware generators, cargo-fuzz/libFuzzer; `test-fuzzing`), with crashes minimized into regression tests.
- Interpreter before compiler: a tree-walking or bytecode interpreter is the semantic reference for later backends.
- Specify semantics in writing (evaluation order, integer overflow, undefined behavior or its absence) before optimizing; optimizations must preserve the spec, not the current behavior.
- Performance claims of generated code follow `cpu-performance` methodology (benchmarks, variance, hardware).

## Verify
Golden tests, end-to-end tests and differential tests green · fuzzing run for the changed phase with no new crashes · diagnostics reviewed on bad inputs · toolchain versions (LLVM, wasm tools) reported.
