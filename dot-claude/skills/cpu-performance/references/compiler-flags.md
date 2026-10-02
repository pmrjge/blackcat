# Compiler flags and their distribution caveats (reference)
Read when choosing optimization, LTO, PGO/BOLT, target-cpu or fast-math flags for a build that will be measured or shipped. Parent: `cpu-performance` SKILL.md. Flag spellings unverified as of 2026-10-02 — check the compiler's docs for the installed version.

## Compiler flags and their distribution caveats
| Setting | Effect | Caveat |
|---|---|---|
| Rust `-C target-cpu=native`; C/C++ `-march=native` (x86-64), `-mcpu=native` (AArch64) | use all ISA extensions of the build machine (AVX2/AVX-512; bf16/i8mm on M2+) | binary may die with SIGILL elsewhere. Portable options: `x86-64-v3` (AVX2 baseline) or runtime dispatch. `aarch64-apple-darwin` already targets the M1 feature set; clang knows `-mcpu=apple-m3` only from recent versions |
| `lto = "thin"` / `"fat"`; `-flto` | cross-crate / cross-module inlining | longer link times; measure thin first |
| `codegen-units = 1` | better intra-crate optimization | slower builds |
| `panic = "abort"` | less unwinding code | `catch_unwind` stops working; destructors do not run on panic |
| `-O3` vs `-O2`, `opt-level` | more aggressive inlining/unrolling | can be slower (code size); measure |
| PGO: `RUSTFLAGS="-Cprofile-generate=/tmp/pgo"` → run representative workloads → `llvm-profdata merge -o /tmp/pgo/merged.profdata /tmp/pgo` → `RUSTFLAGS="-Cprofile-use=/tmp/pgo/merged.profdata"` (or `cargo pgo`); clang `-fprofile-instr-generate/-fprofile-instr-use`; GCC `-fprofile-generate/-fprofile-use` | branch/layout decisions from real profiles | the training workload must match production; identical flags in both builds; regenerate after code changes; `llvm-profdata` must match the compiler's LLVM (`rustup component add llvm-tools-preview`) |
| BOLT (`llvm-bolt`, `cargo pgo bolt`) | post-link code layout | Linux ELF only; needs branch-sampling or instrumentation profiles; follow the tool's docs |
| `-ffast-math` | vectorized float reductions | breaks IEEE semantics (NaN/inf, reassociation, denormals) and changes results; prefer targeted flags (`-fno-math-errno`) or explicit reassociation |
| `debug = "line-tables-only"`, frame pointers | profilable release builds | small size/perf cost; keep a dedicated profiling profile |
