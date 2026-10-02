---
name: perf-profilers
description: Use when profiling CPU time on macOS or Linux — samply, Instruments, perf, py-spy, counters.
---
# CPU profilers — cheap and broad first
Hub: `cpu-performance` (workflow, benchmarking discipline, usual wins, report). Heap and leaks: `perf-memory`. Kernel-level tracing (eBPF, bpftrace): `linux-kernel-ebpf`. Native crashes and debuggers: `debug-native`. Tool details were checked earlier without recorded URLs: unverified as of 2026-10-02 unless a Sources line says otherwise.

| Need | macOS (Apple Silicon) | Linux x86-64 |
|---|---|---|
| Where does CPU time go | `samply record ./app args` (Firefox Profiler UI; on- and off-CPU samples); `xcrun xctrace record --template 'Time Profiler' --output run.trace --launch -- ./app args` | `perf record -F 999 -g ./app` (or `--call-graph dwarf` without frame pointers) → `perf report --no-children`; `samply record` works too |
| Hardware counters (IPC, cache and branch misses) | Instruments CPU Counters: pick the events in the app, save as a custom template, then record it with `xctrace --template '<saved name>'` | `perf stat -r 5 -e cycles,instructions,branch-misses,cache-misses ./app`; `perf stat -M TopdownL1` on Intel; AMD: `perf list metricgroup` |
| Flame graph | samply / Instruments UI | `perf script \| inferno-collapse-perf \| inferno-flamegraph > flame.svg`; `cargo flamegraph` |
| Waiting: locks, I/O, syscalls | samply off-CPU samples; `--template 'System Trace'`; `sudo fs_usage -w <pid>` | `strace -c ./app`; `perf sched`, `perf lock` (kernel support permitting); bcc `offcputime` |
| Python | `sudo py-spy record -o prof.svg -- .venv/bin/python app.py` (root is required on macOS; system Python under SIP cannot be profiled) | `py-spy record -o prof.svg -- .venv/bin/python app.py`; `perf record -g .venv/bin/python -X perf app.py` (3.12+, Linux only) |

- List xctrace templates with `xcrun xctrace list templates`; open a trace with `open run.trace`. samply cannot profile Apple-signed system binaries; run `samply setup` once to allow attaching to running processes.
- py-spy: `--native` (include C/C++/Rust extension frames), `--gil`, `--idle`, `--subprocesses`, `--rate`, `--format speedscope`; `py-spy top --pid N`, `py-spy dump --pid N` for live processes.
- scalene (line-level CPU split into Python vs native time, plus memory): `scalene run app.py --- --app-args`, then `scalene view --cli` (or `scalene view` in a browser); `scalene run --cpu-only` is faster.
- Deterministic Python tracing (`uv run python -m cProfile -o prof.out app.py`, `pstats`) gives call counts but inflates cheap functions. `uv run python -X importtime` for startup. Memory profiling: `perf-memory`.
- Rust symbols: keep line tables in optimized builds (`[profile.release] debug = "line-tables-only"`, or a `[profile.profiling]` with `inherits = "release"`); Linux frame-pointer unwinding needs `RUSTFLAGS="-C force-frame-pointers=yes"` (C/C++: `-fno-omit-frame-pointer`); Apple arm64 always keeps frame pointers. Linux perf access: `kernel.perf_event_paranoid` ≤ 1 for user profiling.

## Apple Silicon specifics
- Core clusters: `sysctl hw.perflevel0.physicalcpu hw.perflevel1.physicalcpu` (perflevel0 is the fastest cluster; read `hw.perflevel0.name`, recent chips name tiers differently). macOS offers no thread-to-core pinning; placement follows QoS. User-interactive/user-initiated work prefers P cores; background QoS runs on E cores only. `taskpolicy -c background ./app` (also `utility`, `maintenance`) clamps a process — useful to measure E-core behavior, a trap if a benchmark inherits a background clamp from its launcher. In code: `pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED, 0)` or GCD QoS.
- With more threads than P cores, E cores join and static partitioning becomes imbalanced (the slowest chunk decides). Use work stealing or dynamic scheduling (rayon, GCD `dispatch_apply`/`concurrentPerform`, OpenMP `schedule(dynamic)`) or size latency-critical pools to the P-core count, and measure both.
- Cache line 128 B (`sysctl hw.cachelinesize`); page size 16 KiB (`pagesize`) — affects mmap granularity and TLB reach.
- Unified memory: the SoC bandwidth (M3 Ultra: Apple quotes over 800 GB/s) is shared by CPU and GPU, and CPU clusters alone reach only part of it — measure with a STREAM-style triad before claiming a kernel is bandwidth-bound.
- SIMD: 128-bit NEON is the baseline (no AVX); newer chips add features (check `sysctl hw.optional`). Dense linear algebra and DSP: call Accelerate (BLAS/LAPACK/vDSP), which is tuned for Apple silicon including its matrix units — don't hand-roll GEMM; check which BLAS NumPy uses with `numpy.show_config()`.
- No `perf`: use samply, Instruments/xctrace (Time Profiler, CPU Counters, Allocations, System Trace). Valgrind does not run on Apple Silicon macOS; heap and leak tools for macOS are in `perf-memory`.

## Linux x86-64 specifics
- Topology: `lscpu`, `lscpu --extended` (core types on hybrid CPUs, SMT siblings). Hybrid Intel parts expose separate PMUs (`cpu_core/…/`, `cpu_atom/…/` events); pin benchmarks to one core type and one SMT thread per core with `taskset`.
- Profiling permissions: `sudo sysctl kernel.perf_event_paranoid=1`; for kernel symbols `kernel.kptr_restrict=0` (restore both afterwards).
- Transparent huge pages (`/sys/kernel/mm/transparent_hugepage/enabled`) can help TLB-bound workloads with large heaps; measure.
- Laptop frequency depends on power limits shared with the GPU: keep GPU load constant (idle) during CPU benchmarks.

## Verify
- [ ] Profile taken on an optimized build with symbols (line tables, frame pointers) — no `[unknown]` frames in the hot path.
- [ ] The hot spot is confirmed by a second view (flame graph + counters, or sampling + off-CPU) before changing code.
- [ ] After the change, the same profiler shows the targeted cost shrinking.

## Sources
- Verified 2026-10-02 https://crates.io/api/v1/crates/samply — samply 0.13.1; https://pypi.org/pypi/py-spy/json — py-spy 0.4.2.
- Unverified as of 2026-10-02: scalene's `run`/`view` subcommands and version.
