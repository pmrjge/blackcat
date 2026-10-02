---
name: gpu-kernel-dev
description: Use when writing or optimizing a custom GPU kernel — Metal via MLX, CUDA C++ or Triton (incl. Blackwell sm_120); roofline, occupancy, low precision, correctness, profiling.
---
# GPU kernel development

## Scope
- Covers: deciding whether a custom kernel is worth it, designing it against a performance model, writing it (MLX `mx.fast.metal_kernel`/`mx.fast.cuda_kernel`, CUDA C++, Triton), testing numerics, profiling, and wiring it into PyTorch or MLX.
- Load `accelerator-perf` as well: it owns the environment capture, timing methodology and benchmark report table. CPU-side work: `cpu-performance`. Quantization recipes: `llm-quantization`.

## 1. Is a custom kernel justified?
1. Profile the real workload first (framework profiler; the modules' Profiling sections) and rank ops by time. Optimize only what dominates.
2. Look for an existing fast path: cuBLAS/cuBLASLt, cuDNN, PyTorch SDPA/FlashAttention-class kernels, CUTLASS/CuTe; MLX `mx.fast.scaled_dot_product_attention`, `rms_norm`, `layer_norm`, `rope`, `mx.quantized_matmul`. Check that any third-party kernel library actually supports `sm_120` (many target `sm_90`/`sm_100` only).
3. Try compiler fusion: `torch.compile` (Inductor generates fused Triton kernels), `mx.compile` for elementwise chains.
4. A custom kernel pays off for: memory-bound chains of elementwise/reduction ops that stay unfused; non-standard layouts or quantization formats (fused dequantize + matmul); ops without library support (custom scans, masks, sparse patterns, sampling); launch-overhead-bound sequences of tiny ops.
5. Estimate the ceiling before writing: minimum bytes moved ÷ measured bandwidth (or FLOPs ÷ measured peak). If the current implementation is already within ~1.3× of that bound, stop.

## 2. Performance model
- **Roofline:** attainable = min(peak compute, arithmetic intensity × bandwidth), intensity = FLOPs / DRAM bytes. An fp16 elementwise add does 1 FLOP per 6 bytes (memory-bound); a 4096³ fp16 GEMM ≈ 1.4·10^11 FLOPs over ≈ 1·10^8 bytes ≈ 1365 FLOP/byte (compute-bound). Measure achievable bandwidth (a device-to-device copy kernel) and achievable FLOP/s (a large vendor GEMM) on the actual device: laptop GPUs vary with their power limit, and Apple quotes "over 800 GB/s" for M3 Ultra — shared by CPU and GPU.
- **Vocabulary map:** CUDA thread / warp (32) / block / shared memory / grid of blocks ↔ Metal thread / SIMD-group (32) / threadgroup / threadgroup memory / grid of threads (MLX `grid` counts threads) ↔ Triton program instance (one block, `num_warps` warps) operating on block tensors.
- **Coalescing:** consecutive threads touch consecutive addresses; use vector loads (`float4`, `half2`, `half4`) on aligned data; the innermost (stride-1) dimension maps to the fastest-varying thread index.
- **Shared/threadgroup memory:** stage tiles for reuse; on NVIDIA 32 banks × 4 bytes — column access with a power-of-two stride conflicts (pad `tile[32][33]` or XOR-swizzle).
- **Occupancy:** bounded by registers per thread, shared memory per block, threads per block and resident warps per SM. It hides latency but is not a goal: GEMM-like kernels win with fewer, fatter threads (register tiling, ILP). Query with `cudaOccupancyMaxActiveBlocksPerMultiprocessor`; Nsight Compute's Occupancy section shows the limiter.
- **Warp/SIMD-group collectives:** `__shfl_down_sync`/cooperative groups on CUDA, `simd_sum`/`simd_max`/`simd_shuffle_down`/`simd_prefix_exclusive_sum` on Metal — reductions without shared memory or barriers.
- **Tiling and pipelining:** block tile in shared memory, micro-tile in registers, double buffering (`cp.async` on sm_80+, TMA on sm_90+; Triton's `num_stages` pipelines loads).
- **Register pressure:** spills go to local memory (`-Xptxas -v` reports spill stores/loads); bound with `__launch_bounds__` or Triton `num_warps`/`maxnreg`.
- **Launch overhead and tails:** each launch costs microseconds — fuse, use persistent kernels or CUDA Graphs; with few blocks per SM the last partial wave dominates (split-K, persistent scheduling).
- **Divergence:** branches that split a warp/SIMD-group serialize; keep control flow uniform per group.

| Fact (verified) | Apple M-series GPU (M1 = Apple7, M2 = Apple8, M3/M4 = Apple9) | RTX 50-series (Blackwell consumer, CC 12.0, `sm_120`) |
|---|---|---|
| SIMD/warp width | 32 | 32 |
| Max threads per group | 1024 (the pipeline may allow fewer for register-heavy kernels) | 1024 |
| Group-shared memory | 32 KB per threadgroup | 100 KB per SM (of 128 KB unified with L1), ≤ 99 KB per block (> 48 KB dynamic needs `cudaFuncSetAttribute(k, cudaFuncAttributeMaxDynamicSharedMemorySize, bytes)`) |
| Residency | — | ≤ 48 warps per SM; ≤ 24 blocks per SM in the CUDA 13 guide (the CUDA 12.x guide and Blackwell tuning guide say 32 — query `cudaDevAttrMaxBlocksPerMultiprocessor`); 64K 32-bit registers per SM; ≤ 255 registers per thread |
| Matrix units | `simdgroup_matrix` 8×8 (half, bfloat, float; Apple7+); Metal 4 TensorOps (Metal Performance Primitives) | tensor cores via warp-level `mma.sync`, including block-scaled FP8/FP6/FP4; TMA present; no `tcgen05`/TMEM (datacenter `sm_100`/`sm_103`); `wgmma` is Hopper-only (`sm_90a`) |
| Toolchain floor | MLX on macOS (Metal JIT) | CUDA ≥ 12.8 (12.9 adds `sm_120f` family targets); driver R570+ with the open kernel modules on Linux; PyTorch ≥ 2.7 with cu128+ wheels; Triton ≥ 3.3 |

## Modules
| Module | Load when |
|---|---|
| `gpu-metal-mlx` | Metal kernels on Apple Silicon through `mx.fast.metal_kernel` (and MLX's CUDA backend) |
| `gpu-cuda` | CUDA C++ kernels, sm_120 builds, Nsight profiling, PyTorch custom ops and extensions |
| `gpu-triton` | Triton kernels, `tl.dot`, autotuning, interpreter debugging, `torch.library.triton_op` |

## References
- `references/numerics-correctness.md` — read when choosing formats and accumulation precision, setting tolerances, writing parity tests, or reviewing for common kernel bugs.

## Profiling
- Methodology and report: `accelerator-perf` (environment block, warm-up, synchronization, ≥ 10 iterations, median/p90, parity, one variable at a time).
- Report achieved GB/s (bytes moved ÷ time) and TFLOP/s next to the measured roofline, not only speedups.

## Verify
- [ ] Profile shows the op mattered; ceiling estimated; library/compiler alternatives tried first.
- [ ] Parity against the reference at dtype-appropriate tolerances over randomized shapes, strides and special values; sanitizers/validation layers clean.
- [ ] Benchmarks follow `accelerator-perf`; achieved bandwidth or FLOP/s stated against the measured roofline.
- [ ] Every process you started is stopped; the GPU was not shared with another timing run.

## Deliverables
Kernel source and Python wrapper; tests (parity, shapes, special values, gradients); benchmark script; the `accelerator-perf` report table with the environment block; Nsight/Xcode reports or screenshots of the decisive sections; notes on tolerances, determinism and supported shapes/dtypes/architectures.
