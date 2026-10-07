# Rust performance basics

Measure first (criterion/divan, `--release`); deep profiling workflow is in `cpu-performance`.
- Allocation: `Vec::with_capacity`, reuse buffers (`clear()`), borrow slices instead of cloning in hot paths, `SmallVec` for small bounded sizes, `bumpalo` for per-frame/per-request arenas.
- Iterators compile to tight loops; `chunks_exact` and slice iteration remove bounds checks and help auto-vectorization.
- Hashing: std `HashMap` uses DoS-resistant SipHash; for trusted keys use `rustc-hash` (`FxHashMap`) or `foldhash` (hashbrown's default).
- Parallelism: rayon `par_iter()` for data-parallel CPU work; don't run rayon on tokio worker threads directly.
- SIMD: check auto-vectorization first; `std::arch` intrinsics with runtime detection (`is_x86_feature_detected!`, `std::arch::is_aarch64_feature_detected!`); portable wrappers `wide`, `pulp`; `multiversion` for per-CPU clones; `std::simd` is nightly-only. `-C target-cpu=native` only for binaries that run on the build machine.
- Global allocator: `mimalloc` or `tikv-jemallocator` for allocation-heavy multithreaded code — keep only if a benchmark shows a win.
