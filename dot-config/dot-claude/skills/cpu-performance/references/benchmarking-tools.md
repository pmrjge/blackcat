# CPU benchmarking tools (reference)
Read when setting up criterion, hyperfine, pytest-benchmark, pyperf or Google Benchmark. Parent: `cpu-performance` SKILL.md (discipline §2). criterion latest 0.8.2 — Verified 2026-10-02 https://crates.io/api/v1/crates/criterion; other tool details unverified as of 2026-10-02.

## Tools
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
