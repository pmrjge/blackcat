---
name: py-perf
description: Use to make Python faster or leaner — the optimization ladder, profilers, vectorizing, numba, Rust extensions with PyO3/maturin.
---
# Python performance

Part of `python-engineering` (baseline versions, pitfalls). Benchmark method and reporting: `cpu-performance`.

## Ladder
Better algorithm/data structure → vectorize (numpy; polars lazy `scan_*`…`collect()`; duckdb SQL) → profile → compile hot loops (numba `@njit(cache=True)`: first call compiles, supports a numpy subset) → Rust extension (PyO3 + maturin) → processes for CPU-bound pure-Python work.

## Tools
- Profilers: `py-spy record -o profile.svg -- .venv/bin/python app.py` or `py-spy top --pid PID` (sampling, attach to live processes); scalene (line-level CPU/memory/GPU); memray (`memray run`, `memray flamegraph`) for allocations; `uv run python -X importtime` for startup.
- PyO3/maturin: `uv init --build-backend maturin`; add `[tool.uv] cache-keys = [{ file = "pyproject.toml" }, { file = "Cargo.toml" }, { file = "**/*.rs" }]` so `uv sync`/`uv run` rebuild after Rust edits; build abi3 wheels (pyo3 feature `abi3-py312`) for one wheel per platform; release the GIL around long Rust work (the PyO3 method for this was renamed across versions — check the docs of the pinned PyO3).

## Verify
- [ ] Performance claims backed by profiles or benchmarks with the same inputs: measure before/after with the same inputs; report the median of repeated runs.
