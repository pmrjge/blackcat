---
name: accelerator-perf
description: Load before any benchmark, kernel or port, and before any speed or memory claim. Benchmarking discipline for GPU/accelerator performance and porting work — environment capture, methodology, parity checks, profiler order and report format.
---
# Accelerator performance protocol

## Environment capture (do this first, every time)
Record before any measurement: hardware (Apple chip generation and unified-memory size, or NVIDIA GPU model(s) and compute capability), OS/driver version, CUDA runtime & nvcc or MLX/mlx-lm versions, framework versions, and container image if any. Every report includes this block.

## Methodology
- Establish a baseline before changing anything — you can't report a Δ% without one.
- Same shapes, dtypes and batch sizes across "before" and "after"; changing more than one variable invalidates the comparison.
- Warm up (a few discarded iterations) before timing — first-run costs (JIT, kernel compilation, cache misses) are not steady-state.
- Synchronize before timing: force evaluation on MLX (`mx.eval`) or synchronize the CUDA stream (`torch.cuda.synchronize()`) — async dispatch makes naive wall-clock timing lie.
- Run >= 10 iterations; report median and p90, not a single sample or a mean that hides tail latency.
- Report throughput (tokens/s, samples/s, GFLOP/s as fits) and peak memory, not just latency.
- Sanity-check against a roofline: is the achieved throughput plausible given memory bandwidth / compute peak, or does the number itself indicate a measurement bug?

## Parity (for ports and precision changes)
Before trusting a faster path, confirm it still computes the right thing: compare outputs against the reference implementation with explicit dtype tolerances (max absolute and max relative error), on real inputs, not just random noise. Numerical parity comes before speed claims.

## Profiler order
Don't reach for the deepest tool first — go from cheap and broad to expensive and narrow:
framework-level profiler (torch.profiler / MLX's own instrumentation) → timeline tool (nsys) → per-kernel tool (ncu, Instruments/Metal System Trace). Stop as soon as the bottleneck is identified; don't profile past the point of actionable insight.

## Change discipline
One variable at a time. If you change dtype and batch size together and it gets faster, you don't know why.

## Report format
```
| Change | Before | After | Δ% | Parity | Notes |
|---|---|---|---|---|---|
```
Plus: environment block, what was held constant, and confirmation that every process you started (local or remote) was killed.

Related skills: `gpu-kernel-dev` (writing Metal, CUDA or Triton kernels), `cpu-performance` (CPU-side profiling and benchmarks), `numerical-methods` (precision and tolerances), `local-llm-serving` (serving throughput).
