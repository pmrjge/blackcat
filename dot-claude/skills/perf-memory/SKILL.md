---
name: perf-memory
description: Use when finding memory growth, leaks or peak RSS — heaptrack, Instruments Allocations, memray, dhat, massif; CPU time is perf-profilers.
---
# Memory profiling (heap, leaks, peak RSS)
Hub: `cpu-performance` (workflow, discipline; allocation as a speed cost is win #3 there). CPU profilers: `perf-profilers`. Tool details were checked earlier without recorded URLs: unverified as of 2026-10-02 unless a Sources line says otherwise.

## Pick the question first
- **Peak RSS too high:** measure it (`/usr/bin/time -l` on macOS, max RSS in bytes; `/usr/bin/time -v` on Linux), then find who holds memory at the peak (a heap snapshot at the peak, not at exit).
- **Growth over time (leak or unbounded cache):** two or more heap snapshots under steady load, diffed; growth that plateaus is a cache, growth that never stops is a leak.
- **Allocation churn (speed):** count allocations per operation; churn shows as `malloc`/`free` high in a CPU profile (`perf-profilers`).
- **Fragmentation:** RSS stays high after frees while the live heap is small; try another allocator (mimalloc, jemalloc) as an experiment and measure both.

## Tools
| Need | macOS (Apple Silicon) | Linux x86-64 |
|---|---|---|
| Heap: who allocates, peak, leaks | `--template 'Allocations'` or `'Leaks'`; `leaks --atExit -- ./app`; `/usr/bin/time -l ./app` (max RSS in bytes) | `heaptrack ./app` then `heaptrack --analyze <file>` or `heaptrack_gui`; `valgrind --tool=massif ./app` + `ms_print massif.out.<pid>`; `valgrind --tool=dhat ./app` (open in `dh_view.html`); `/usr/bin/time -v ./app` |

- Python: `tracemalloc` snapshots, or `memray run -o out.bin app.py` + `memray flamegraph out.bin`.
- memray runs on macOS and Linux; it also offers live and native-frame modes (flag names unverified as of 2026-10-02).
- Rust: the `dhat` crate (heap profiling in-process, works on both OSes).
- Containers and services: watch the cgroup's memory and the OOM-killer log (`journalctl -k`); file names under cgroup v2 unverified as of 2026-10-02.

## Common causes
- Unbounded caches and memo tables; per-request data kept in globals; listeners/callbacks never removed; reference cycles holding large objects (Python: `gc.get_referrers` on a suspect object).
- Loading whole files or result sets when streaming would do (`dataframes-duckdb` for lazy/streaming dataframes).
- Copies: slicing that copies, materializing lazy results early, string concatenation in loops, serialization round trips.
- Over-reserved buffers (`with_capacity` far above use), per-thread arenas multiplied by many threads.

## Verify
- [ ] The metric (peak RSS, live heap at a point, growth per hour) and workload stated; before/after measured the same way.
- [ ] The responsible allocation site is identified in a heap profile, not inferred from code reading.
- [ ] A soak run (fixed load, long enough to see growth) shows a flat live heap after the fix.

## Sources
- Verified 2026-10-02 https://pypi.org/pypi/memray/json — memray classifiers list macOS and Linux.
- Unverified as of 2026-10-02: heaptrack being Linux-only; memray and heaptrack versions.
