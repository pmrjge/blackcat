---
name: cpu-performance
description: Load before measuring or optimizing CPU-side speed or memory on macOS or Linux — benchmarking (criterion, hyperfine, pyperf), profilers (Instruments, samply, perf, py-spy), flags.
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

Tools:
- Rust — criterion (≥ 0.6 uses `std::hint::black_box`; `criterion::black_box` is deprecated):
```toml
[dev-dependencies]
criterion = "0.8"          # check the current version
[[bench]]
name = "hot"
harness = false
```
```rust
use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion};
use std::hint::black_box;
fn bench(c: &mut Criterion) {
    let mut g = c.benchmark_group("max_subarray");
    for n in [1_000usize, 10_000, 100_000] {
        let xs: Vec<i64> = (0..n as i64).map(|i| (i * 7919) % 2001 - 1000).collect();
        g.bench_with_input(BenchmarkId::from_parameter(n), &xs, |b, xs| b.iter(|| mycrate::max_subarray(black_box(xs))));
    }
    g.finish();
}
criterion_group!(benches, bench);
criterion_main!(benches);
```
  `cargo bench --bench hot -- --save-baseline before`, change code, `cargo bench --bench hot -- --baseline before` (reports change with confidence intervals; `--warm-up-time`, `--measurement-time`, `--noise-threshold` tune it; without `--bench`, a lib target's libtest harness rejects these flags unless `[lib] bench = false`). `divan` is a lighter alternative.
- CLIs — hyperfine: `hyperfine -N --warmup 3 --runs 30 --export-markdown bench.md --export-json bench.json 'old/app in.dat' 'new/app in.dat'` (`-N` = no intermediate shell; `--prepare 'cmd'` runs before each timing, e.g. to drop caches; `-P threads 1 16 'app -j {threads}'` scans a parameter; `-L compiler gcc,clang '{compiler} ...'` lists values).
- Python — pytest-benchmark: the `benchmark(fn, *args)` fixture, `pytest --benchmark-only --benchmark-autosave`, then `--benchmark-compare --benchmark-compare-fail=median:5%` in CI. pyperf: `uv run --with pyperf python -m pyperf timeit -s 'setup' 'stmt' -o new.json` (spawns worker processes, calibrates loops), `uvx pyperf compare_to old.json new.json --table`.
- C/C++ — Google Benchmark (`--benchmark_repetitions=10 --benchmark_format=json`).

## 3. Profilers — cheap and broad first
| Need | macOS (Apple Silicon) | Linux x86-64 |
|---|---|---|
| Where does CPU time go | `samply record ./app args` (Firefox Profiler UI; on- and off-CPU samples); `xcrun xctrace record --template 'Time Profiler' --output run.trace --launch -- ./app args` | `perf record -F 999 -g ./app` (or `--call-graph dwarf` without frame pointers) → `perf report --no-children`; `samply record` works too |
| Hardware counters (IPC, cache and branch misses) | Instruments CPU Counters: pick the events in the app, save as a custom template, then record it with `xctrace --template '<saved name>'` | `perf stat -r 5 -e cycles,instructions,branch-misses,cache-misses ./app`; `perf stat -M TopdownL1` on Intel; AMD: `perf list metricgroup` |
| Flame graph | samply / Instruments UI | `perf script \| inferno-collapse-perf \| inferno-flamegraph > flame.svg`; `cargo flamegraph` |
| Heap: who allocates, peak, leaks | `--template 'Allocations'` or `'Leaks'`; `leaks --atExit -- ./app`; `/usr/bin/time -l ./app` (max RSS in bytes) | `heaptrack ./app` then `heaptrack --analyze <file>` or `heaptrack_gui`; `valgrind --tool=massif ./app` + `ms_print massif.out.<pid>`; `valgrind --tool=dhat ./app` (open in `dh_view.html`); `/usr/bin/time -v ./app` |
| Waiting: locks, I/O, syscalls | samply off-CPU samples; `--template 'System Trace'`; `sudo fs_usage -w <pid>` | `strace -c ./app`; `perf sched`, `perf lock` (kernel support permitting); bcc `offcputime` |
| Python | `sudo py-spy record -o prof.svg -- .venv/bin/python app.py` (root is required on macOS; system Python under SIP cannot be profiled) | `py-spy record -o prof.svg -- .venv/bin/python app.py`; `perf record -g .venv/bin/python -X perf app.py` (3.12+, Linux only) |

- List xctrace templates with `xcrun xctrace list templates`; open a trace with `open run.trace`. samply cannot profile Apple-signed system binaries; run `samply setup` once to allow attaching to running processes.
- py-spy: `--native` (include C/C++/Rust extension frames), `--gil`, `--idle`, `--subprocesses`, `--rate`, `--format speedscope`; `py-spy top --pid N`, `py-spy dump --pid N` for live processes.
- scalene (line-level CPU split into Python vs native time, plus memory): `scalene run app.py --- --app-args`, then `scalene view --cli` (or `scalene view` in a browser); `scalene run --cpu-only` is faster.
- Deterministic Python tracing (`uv run python -m cProfile -o prof.out app.py`, `pstats`) gives call counts but inflates cheap functions. `uv run python -X importtime` for startup. Memory: `tracemalloc` snapshots, or `memray run -o out.bin app.py` + `memray flamegraph out.bin`.
- Rust symbols: keep line tables in optimized builds (`[profile.release] debug = "line-tables-only"`, or a `[profile.profiling]` with `inherits = "release"`); Linux frame-pointer unwinding needs `RUSTFLAGS="-C force-frame-pointers=yes"` (C/C++: `-fno-omit-frame-pointer`); Apple arm64 always keeps frame pointers. Linux perf access: `kernel.perf_event_paranoid` ≤ 1 for user profiling.

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

## 5. Compiler flags and their distribution caveats
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

## 6. Apple Silicon specifics
- Core clusters: `sysctl hw.perflevel0.physicalcpu hw.perflevel1.physicalcpu` (perflevel0 is the fastest cluster; read `hw.perflevel0.name`, recent chips name tiers differently). macOS offers no thread-to-core pinning; placement follows QoS. User-interactive/user-initiated work prefers P cores; background QoS runs on E cores only. `taskpolicy -c background ./app` (also `utility`, `maintenance`) clamps a process — useful to measure E-core behavior, a trap if a benchmark inherits a background clamp from its launcher. In code: `pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED, 0)` or GCD QoS.
- With more threads than P cores, E cores join and static partitioning becomes imbalanced (the slowest chunk decides). Use work stealing or dynamic scheduling (rayon, GCD `dispatch_apply`/`concurrentPerform`, OpenMP `schedule(dynamic)`) or size latency-critical pools to the P-core count, and measure both.
- Cache line 128 B (`sysctl hw.cachelinesize`); page size 16 KiB (`pagesize`) — affects mmap granularity and TLB reach.
- Unified memory: the SoC bandwidth (M3 Ultra: Apple quotes over 800 GB/s) is shared by CPU and GPU, and CPU clusters alone reach only part of it — measure with a STREAM-style triad before claiming a kernel is bandwidth-bound.
- SIMD: 128-bit NEON is the baseline (no AVX); newer chips add features (check `sysctl hw.optional`). Dense linear algebra and DSP: call Accelerate (BLAS/LAPACK/vDSP), which is tuned for Apple silicon including its matrix units — don't hand-roll GEMM; check which BLAS NumPy uses with `numpy.show_config()`.
- No `perf`: use samply, Instruments/xctrace (Time Profiler, CPU Counters, Allocations, System Trace). Valgrind does not run on Apple Silicon macOS; use Instruments/`leaks`, or the Rust `dhat` crate (heap profiling in-process, works on both OSes).

## 7. Linux x86-64 specifics
- Topology: `lscpu`, `lscpu --extended` (core types on hybrid CPUs, SMT siblings). Hybrid Intel parts expose separate PMUs (`cpu_core/…/`, `cpu_atom/…/` events); pin benchmarks to one core type and one SMT thread per core with `taskset`.
- Profiling permissions: `sudo sysctl kernel.perf_event_paranoid=1`; for kernel symbols `kernel.kptr_restrict=0` (restore both afterwards).
- Transparent huge pages (`/sys/kernel/mm/transparent_hugepage/enabled`) can help TLB-bound workloads with large heaps; measure.
- Laptop frequency depends on power limits shared with the GPU: keep GPU load constant (idle) during CPU benchmarks.

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
