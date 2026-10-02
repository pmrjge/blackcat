---
name: cpu-performance
description: Load before measuring or speeding up CPU-bound code on macOS or Linux — benchmark method, criterion, hyperfine, flags; profilers in perf-*.
---
# CPU performance (Apple Silicon macOS, Linux x86-64)

## Scope
- Covers: CPU time, latency, throughput and memory of Rust, C/C++ and Python code; benchmarking, profiling, optimization and reporting on the Mac (Apple Silicon) and the Linux laptop (x86-64).
- Not here: GPU kernels and accelerator benchmarks (`gpu-kernel-dev`, `accelerator-perf`), choosing a better algorithm (`algorithm-design` — usually the biggest win).

## 1. Workflow
1. Define the metric and workload: latency (p50/p99), throughput, peak RSS or startup time, on realistic, versioned inputs (fixed files and seeds). Write the target down ("p99 < 20 ms at 1k req/s").
2. Capture the environment (§2) and a baseline with enough repetitions to know its noise.
3. Profile before touching code; form one hypothesis from the profile.
4. Change one thing; re-measure; check parity (identical output, or within a stated tolerance).
5. Stop at the target, or when the profile is flat and the remaining time is in irreducible work (I/O, memory bandwidth, a library call). Report in the format at the end.

## 2. Benchmarking discipline
- **Environment block:** chip/CPU model, core counts, RAM, OS and kernel, power source and power mode, compiler/interpreter versions and flags, commit hash, background load.
- **Warm-up and repetition:** discard warm-up runs (page faults, cold caches, lazy init, JIT), take ≥ 10 samples (more for small effects), report median with IQR or a bootstrap 95% CI. An effect smaller than the run-to-run spread is not an effect.
- **Order effects:** thermal drift biases "A then B". Interleave (A B A B …) or repeat the comparison in swapped order.
- **Dead-code elimination:** feed inputs and consume outputs through an optimization barrier — Rust `std::hint::black_box`, C++ `benchmark::DoNotOptimize`/`ClobberMemory` (Google Benchmark); a loop that "takes 0.3 ns per element" is measuring nothing.
- **Inputs:** fixed seeds and files; sweep sizes across cache levels (L1/L2/last level/DRAM) instead of one size; state whether caches are warm or cold (cold file cache: Linux `sync; echo 3 | sudo tee /proc/sys/vm/drop_caches`, macOS `sudo purge`).
- **Power and thermals, macOS:** mains power, Low Power Mode off where the machine has it (`pmset -g`), idle system (Spotlight indexing, backups and builds skew results), thermal state via `pmset -g therm`, frequency/power via `sudo powermetrics --samplers cpu_power -i 1000 -n 5`.
- **Power and thermals, Linux laptop:** AC power, `powerprofilesctl set performance`, governor `sudo cpupower frequency-set -g performance`; for low-noise A/B comparisons disable turbo/boost (driver-dependent — `cpupower frequency-info`) or add repetitions; pin with `taskset -c <cpus>`; `uvx pyperf system tune` applies most of this (`... system reset` to undo). Record `uname -r` and, on CachyOS, whether a sched_ext scheduler is active (`cat /sys/kernel/sched_ext/state`, `/sys/kernel/sched_ext/root/ops`).

## 4. The usual wins, in order
1. **Algorithmic.** Complexity, repeated work, caching, better data structures (`algorithm-design`). A profile hot spot in `O(n^2)` code is fixed by the algorithm, not by SIMD.
2. **Do less.** Skip redundant parsing/serialization/copies, hoist invariants out of loops, exit early, batch small operations, avoid formatting/logging on hot paths.
3. **Allocation.** Signature: `malloc`/`free`/`memmove` high in the profile. Reuse buffers, `Vec::with_capacity`, avoid temporary `String`s/`Vec`s, arenas (`bumpalo`), small-vector types, interning. A global allocator swap (`mimalloc`, `tikv-jemallocator`) is a quick experiment, not a substitute.
4. **Data layout and locality.** Contiguous arrays over pointer-linked structures; struct-of-arrays for scans and SIMD; compact types (u32 indices instead of pointers/`usize`, bitsets); iterate in memory order (row-major loops, blocking/tiling for 2-D); avoid false sharing between threads — pad hot per-thread data to 128 bytes (Apple Silicon line size; also safe on x86 with adjacent-line prefetch), as `crossbeam_utils::CachePadded` does.
5. **Branch predictability.** Signature: high `branch-misses`. Sort or partition data first, use branchless selects, lookup tables, move rare cases out of the loop.
6. **Vectorization (SIMD).** First make auto-vectorization possible: simple counted loops, no aliasing (slices/`chunks_exact` in Rust, `restrict` in C), no early exits or opaque calls in the loop body, reductions the compiler may reorder (integers; floats only with explicit reassociation). Check the result: `cargo asm --rust mycrate::path::func` (cargo-show-asm), clang `-Rpass=loop-vectorize -Rpass-missed=loop-vectorize`, GCC `-fopt-info-vec-missed`. Then explicit SIMD: `std::arch` intrinsics with runtime dispatch on x86 (`is_x86_feature_detected!` + `#[target_feature(enable = "avx2")]`, or the `multiversion` crate); NEON is always present on AArch64. Python: move loops into NumPy/Polars operations.
7. **Parallelism.** After the serial path is fast: rayon (`par_iter`, work stealing; `RAYON_NUM_THREADS`), threads with coarse-grained work, `std::thread::scope`. Check Amdahl's fraction and memory-bandwidth saturation (speedup flattening at a few threads). Avoid oversubscription: BLAS/OpenMP threads × processes (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`, or `threadpoolctl` at runtime). Python: processes for CPU-bound pure-Python work; native code that releases the GIL; the free-threaded build is officially supported since 3.14 (PEP 779) but optional — confirm every C extension supports it.
8. **I/O batching.** Buffered readers/writers, fewer syscalls (`strace -c` counts them), `mmap` for large read-mostly files, larger read sizes, async I/O only for many concurrent network requests, compression only when I/O-bound.
9. **Lock contention.** Signature: threads idle in off-CPU profiles, speedup falls with more threads. Shorten critical sections, shard state, use per-thread accumulators merged at the end, `RwLock` for read-mostly data, lock-free queues (`crossbeam`), `parking_lot`.

## Modules
| Module | Load when |
|---|---|
| `perf-profilers` | finding where CPU time goes: samply, Instruments/xctrace, perf, py-spy, scalene, counters, platform specifics |
| `perf-memory` | peak RSS, leaks, allocation churn: heaptrack, Instruments Allocations/Leaks, memray, dhat, massif |
| `perf-load-testing` | latency and throughput of a service under load: k6, vegeta, oha, coordinated omission, percentiles |

## References
- `references/benchmarking-tools.md` — read when writing criterion, hyperfine, pytest-benchmark, pyperf or Google Benchmark runs.
- `references/compiler-flags.md` — read when choosing target-cpu, LTO, codegen-units, PGO/BOLT, fast-math or profiling profiles.

## Pitfalls (signature → cause → fix)
- Time per element below one cycle → dead-code elimination or constant folding → `black_box` inputs and outputs, vary inputs.
- Bimodal timings → frequency/thermal changes, E-core placement, background work → more repetitions, pinning (Linux), QoS check (macOS), `powermetrics`.
- `[unknown]` frames or truncated stacks → no frame pointers/debug info → `--call-graph dwarf` or rebuild with frame pointers and line tables.
- Python profile dominated by one builtin → interpreter overhead is fine; vectorize or move the loop to native code. Dominated by many tiny functions → cProfile distortion; confirm with py-spy.
- Parallel version slower than serial → oversubscription, false sharing, contended lock or allocator → counters, off-CPU profile, padding, per-thread state.
- Faster locally, crashes on another machine with SIGILL → `target-cpu=native` build shipped.
- Results changed after an "optimization" → fast-math reassociation, unstable sort, race → parity check is mandatory.

## Verify
- [ ] Environment block recorded; baseline noise measured; each comparison clears the noise with CIs.
- [ ] Profiles before and after show the targeted cost shrinking (not just a lower total).
- [ ] Output parity confirmed (bitwise, or within a stated tolerance with a reason).
- [ ] Gains reproduced after a clean rebuild and on the target machine class; flags compatible with where the binary will run.

## Report
```
ENV: machine/chip, cores (P/E), RAM, OS/kernel, power mode, compiler + flags, interpreter, commit
WORKLOAD: inputs (sizes, seeds, files), metric, warm/cold
METHOD: tool, warm-up, repetitions, pinning/QoS, statistic (median + IQR/CI)
| Change | Before | After | Δ% | Parity | Notes |
|---|---|---|---|---|---|
PROFILES: top functions before/after with % of samples; paths to flame graphs / .trace files
COUNTERS (if measured): IPC, cache-miss and branch-miss rates before/after
CONCLUSION: what limits performance now; next candidate change
```
