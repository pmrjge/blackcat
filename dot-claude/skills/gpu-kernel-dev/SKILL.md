---
name: gpu-kernel-dev
description: Use when writing or optimizing a custom GPU kernel — Metal via MLX custom kernels on Apple Silicon, CUDA C++ or Triton on NVIDIA including Blackwell RTX 50-series (sm_120) — covering when a kernel is justified, roofline, occupancy and memory-hierarchy reasoning, low-precision numerics, correctness against a reference, profiling tools, PyTorch/MLX integration and common kernel bugs.
---
# GPU kernel development

## Scope
- Covers: deciding whether a custom kernel is worth it, designing it against a performance model, writing it (MLX `mx.fast.metal_kernel`/`mx.fast.cuda_kernel`, CUDA C++, Triton), testing numerics, profiling, and wiring it into PyTorch or MLX.
- Load `accelerator-perf` as well: it owns the environment capture, timing methodology and benchmark report table. CPU-side work: `cpu-performance`. Quantization recipes: `llm-quantization`.

## 1. Is a custom kernel justified?
1. Profile the real workload first (framework profiler, §8) and rank ops by time. Optimize only what dominates.
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

## 3. MLX custom Metal kernels (Apple Silicon)
API as of MLX 0.32 — confirm on the installed version with `help(mx.fast.metal_kernel)` or `get_library_docs("mlx", "custom metal kernels")`:
```python
import mlx.core as mx

swiglu_kernel = mx.fast.metal_kernel(            # build once, reuse (each build may JIT-compile)
    name="swiglu", input_names=["gate", "up"], output_names=["out"],
    source="""
        uint i = thread_position_in_grid.x;
        float g = float(gate[i]);
        out[i] = T(g / (1.0f + metal::exp(-g)) * float(up[i]));
    """)

def swiglu(gate: mx.array, up: mx.array) -> mx.array:
    return swiglu_kernel(inputs=[gate, up], template=[("T", gate.dtype)],
                         grid=(gate.size, 1, 1), threadgroup=(256, 1, 1),
                         output_shapes=[gate.shape], output_dtypes=[gate.dtype])[0]
```
- `source` is only the body; the signature is generated from inputs (`const device T* gate`), outputs, `template` (Dtype, int or bool; ints/bools become compile-time constants) and the Metal attributes the body uses (`thread_position_in_grid` uint3, `threadgroup_position_in_grid` uint3, `thread_index_in_threadgroup` uint, `thread_index_in_simdgroup` uint, `simdgroup_index_in_threadgroup` uint, `simdgroups_per_threadgroup` uint, `threads_per_threadgroup` uint3, …). Python scalars and any input with fewer than 8 elements arrive in the `constant` address space, so don't hard-code `device` on pointers derived from inputs. `verbose=True` prints the generated source.
- `grid` counts threads (Metal `dispatchThreads`), so edge threadgroups are partial; kernels that use barriers or SIMD reductions should get a grid that is a multiple of the threadgroup size and bounds-check inside. Threadgroup sizes: multiples of 32, start at 256, sweep 128–1024.
- `ensure_row_contiguous=True` (default) copies non-contiguous inputs; to avoid the copy set it False and index with `<name>_shape`/`<name>_strides`/`<name>_ndim` and `elem_to_loc(...)`. Outputs are always row-contiguous and uninitialized unless `init_value=` is given (required with `atomic_outputs=True`).
- `compile_options={"math_mode": "safe" | "relaxed" | "fast"}`: default `safe` keeps IEEE special values (`exp(-inf) == 0`, essential for masked softmax); relax only when edge cases cannot occur.
- Reduction pattern (one threadgroup per row; SIMD reduce → threadgroup memory → SIMD reduce). Compile it with `verbose=True` and test against `mx.fast.rms_norm` before use:
```python
rms_kernel = mx.fast.metal_kernel(
    name="rms_rows", input_names=["x", "w", "eps"], output_names=["y"],
    source="""
        uint row = threadgroup_position_in_grid.x, tid = thread_index_in_threadgroup;
        uint ntg = threads_per_threadgroup.x;
        auto xr = x + row * D;                          // `constant` when x is tiny, else `device`
        float acc = 0.0f;
        for (uint i = tid; i < D; i += ntg) { float v = float(xr[i]); acc += v * v; }
        threadgroup float part[32];
        acc = simd_sum(acc);
        if (thread_index_in_simdgroup == 0) part[simdgroup_index_in_threadgroup] = acc;
        threadgroup_barrier(mem_flags::mem_threadgroup);
        if (simdgroup_index_in_threadgroup == 0) {
            float s = thread_index_in_simdgroup < simdgroups_per_threadgroup ? part[thread_index_in_simdgroup] : 0.0f;
            s = simd_sum(s);
            if (thread_index_in_simdgroup == 0) part[0] = metal::rsqrt(s / D + eps);
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
        float scale = part[0];
        device T* yr = y + row * D;
        for (uint i = tid; i < D; i += ntg) yr[i] = T(float(xr[i]) * scale * float(w[i]));
    """)

def rms_norm(x, w, eps=1e-6, tg=256):                  # x: (rows, D) row-contiguous
    rows, d = x.shape
    return rms_kernel(inputs=[x, w, eps], template=[("T", x.dtype), ("D", d)],
                      grid=(rows * tg, 1, 1), threadgroup=(tg, 1, 1),
                      output_shapes=[x.shape], output_dtypes=[x.dtype])[0]
```
- Matrix ops: `simdgroup_matrix` 8×8 with `simdgroup_load`, `simdgroup_multiply_accumulate`, `simdgroup_store`, executed uniformly by the whole SIMD-group. Metal 4 TensorOps (`mpp::tensor_ops::matmul2d`) need the macOS 26 toolchain; check that MLX's JIT can include the header before depending on it.
- Gradients: decorate the Python wrapper with `@mx.custom_function` and define `.vjp` (often a second kernel; atomics need `init_value=0`).
- Timing: MLX is lazy — time `mx.eval(out)` (and `mx.synchronize()`); memory via `mx.get_peak_memory()`, `mx.reset_peak_memory()`, `mx.clear_cache()` (older code used the `mx.metal.*` spellings).
- The same wrapper runs on MLX's CUDA backend (Linux) via `mx.fast.cuda_kernel` with a CUDA body (`cooperative_groups::this_grid().thread_rank()` for the flat index) and an optional `shared_memory=` size.

## 4. CUDA C++ (NVIDIA, including RTX 50-series)
- Environment first: `nvidia-smi` (driver, GPU, other processes), `nvcc --version`. Build: `nvcc -O3 -lineinfo -Xptxas -v -gencode arch=compute_120,code=sm_120 -gencode arch=compute_120,code=compute_120 k.cu` (the second `-gencode` embeds PTX so newer GPUs can JIT it). Arch-specific instructions (e.g. block-scaled MMA) need `sm_120a`, which has no forward compatibility.
```cuda
__inline__ __device__ float warp_sum(float v) {
    for (int off = 16; off > 0; off >>= 1) v += __shfl_down_sync(0xffffffffu, v, off);
    return v;                                        // lane 0 holds the warp total
}
__global__ void __launch_bounds__(256) row_sum(const float* __restrict__ x, float* __restrict__ out, int n_cols) {
    __shared__ float part[32];
    const float* xr = x + (size_t)blockIdx.x * n_cols;           // 64-bit offset
    float acc = 0.f;
    for (int i = threadIdx.x; i < n_cols; i += blockDim.x) acc += xr[i];   // coalesced
    acc = warp_sum(acc);
    const int lane = threadIdx.x & 31, warp = threadIdx.x >> 5;
    if (lane == 0) part[warp] = acc;
    __syncthreads();
    if (warp == 0) {                                  // blockDim.x must be a multiple of 32
        acc = lane < (blockDim.x >> 5) ? part[lane] : 0.f;
        acc = warp_sum(acc);
        if (lane == 0) out[blockIdx.x] = acc;
    }
}
```
- Check `cudaGetLastError()` right after launches and synchronize in debug builds (errors surface at a later call otherwise). Use `size_t`/64-bit index math past 2^31 elements, `__restrict__` + `const` for read-only data, 16-byte alignment for `float4` loads, `cudaMallocAsync` and streams to overlap, CUDA Graphs for many small launches. `--use_fast_math` flushes denormals and approximates division, sqrt and transcendentals.

## 5. Triton
```python
import torch, triton, triton.language as tl

@triton.jit
def softmax_rows(x_ptr, y_ptr, n_cols, x_stride, y_stride, BLOCK: tl.constexpr):
    row = tl.program_id(0).to(tl.int64)                      # 64-bit row offsets for huge tensors
    offs = tl.arange(0, BLOCK)                                # BLOCK: power of two >= n_cols
    mask = offs < n_cols
    x = tl.load(x_ptr + row * x_stride + offs, mask=mask, other=-float("inf")).to(tl.float32)
    x = x - tl.max(x, axis=0)
    num = tl.exp(x)
    tl.store(y_ptr + row * y_stride + offs, num / tl.sum(num, axis=0), mask=mask)   # store casts to y's dtype

def softmax(x: torch.Tensor) -> torch.Tensor:
    assert x.ndim == 2 and x.stride(1) == 1
    y = torch.empty_like(x)
    block = triton.next_power_of_2(x.shape[1])
    softmax_rows[(x.shape[0],)](x, y, x.shape[1], x.stride(0), y.stride(0), BLOCK=block,
                                num_warps=4 if block <= 2048 else 8)
    return y
```
- Structure: one program instance per tile (`tl.program_id(axis)`, grid as a tuple or a lambda of meta-parameters), block tensors from `tl.arange` (range must be a power of two), masked `tl.load`/`tl.store` (the `other=` fill must be neutral for the reduction: −inf for max, 0 for sum), `tl.constexpr` meta-parameters, `num_warps`, `num_stages`.
- `tl.dot` (Triton 3.8): 2-D or batched 3-D blocks; both operands the same dtype, except that any fp8 × fp8 mix is allowed; K ≥ 16 for 16-bit, ≥ 32 for 8-bit, ≥ 8 for fp32 inputs (M and N are padded); accumulate in fp32 via `acc=` (`out_dtype=tl.bfloat16` is rejected — accumulate in fp32 and cast); fp32 inputs use TF32 tensor cores by default (`input_precision="tf32"`; `"ieee"` for exact fp32, `"tf32x3"` for near-fp32); `allow_tf32` is deprecated. Microscaling formats: `tl.dot_scaled(lhs, lhs_scale, "e2m1" | "e4m3" | "e5m2" | "bf16" | "fp16", rhs, ...)`.
- Autotuning: `@triton.autotune(configs=[triton.Config({"BLOCK_M": 128, "BLOCK_N": 128, "BLOCK_K": 64}, num_warps=8, num_stages=3), ...], key=["M", "N", "K"])` above `@triton.jit`. The kernel runs several times while tuning — kernels that accumulate into or modify their inputs/outputs need `reset_to_zero=[...]` or `restore_value=[...]`. Keep configs within the shared-memory limit (≤ 99 KB per block on sm_120; tiles tuned on datacenter GPUs often exceed it).
- Debug on CPU with `TRITON_INTERPRET=1` (slow; prints and breakpoints work); benchmark with `triton.testing.do_bench(fn, warmup=25, rep=100, quantiles=[0.5, 0.2, 0.8])` — warmup and rep are milliseconds, results in ms.

## 6. Numerics
| Format | Exponent/mantissa bits | Machine epsilon ε (unit roundoff u = ε/2) / range notes |
|---|---|---|
| fp32 | 8 / 23 | ε = 2^−23 ≈ 1.19e−7 |
| tf32 (tensor-core input) | 8 / 10 | fp32 range, fp16 precision |
| bf16 | 8 / 7 | ε = 2^−7 ≈ 7.8e−3, fp32 range |
| fp16 | 5 / 10 | ε = 2^−10 ≈ 9.8e−4, max 65504 |
| fp8 E4M3 (`fn`: no inf) | 4 / 3 | max 448; AMD `fnuz` variants differ — match the exact variant |
| fp8 E5M2 | 5 / 2 | max 57344 |
| fp4 E2M1 | 2 / 1 | values 0, ±0.5, ±1, ±1.5, ±2, ±3, ±4, ±6 |
| MXFP8/MXFP4 (OCP MX) | element format + shared E8M0 scale | blocks of 32 elements |
| NVFP4 | E2M1 + E4M3 block scale + FP32 tensor scale | blocks of 16 elements |
- Accumulate in fp32 for fp16/bf16/fp8/fp4 inputs; keep softmax denominators, norms and losses in fp32; subtract the max before `exp` (online softmax: running max with rescaling); clamp to the target format's max before casting down (out-of-range casts do not saturate everywhere).
- Fully masked rows (all −inf) produce NaN in softmax (−inf − (−inf)); define the behavior explicitly and test it.
- Determinism: float addition is not associative, so atomics and split-K reductions change results run to run. Deterministic options: fixed-order tree reductions, per-block partials followed by one ordered pass, integer/fixed-point accumulation. PyTorch: `torch.use_deterministic_algorithms(True)` plus `CUBLAS_WORKSPACE_CONFIG=:4096:8`.

## 7. Correctness
1. Reference: the same computation in plain framework ops at higher precision (fp32, or fp64 on CPU), including identical quantize/dequantize steps for low-precision formats.
2. Tolerances by dtype — `torch.testing.assert_close` defaults: fp32 rtol 1.3e−6 / atol 1e−5, fp16 1e−3 / 1e−5, bf16 1.6e−2 / 1e−5; widen with reduction length K (typical error ∝ √K·ε, worst case ∝ K·ε). Best test: your kernel's error against the fp64 reference is no worse than the framework's own low-precision op against the same reference.
3. Shapes: randomized, plus 1, primes, sizes just below/above block multiples and powers of two, empty tensors, non-contiguous/transposed/broadcast (stride 0) inputs, batch dims, and > 2^31 total elements (32-bit index overflow).
4. Values: normal, large magnitude (fp16 overflow), tiny/denormal, all-equal, NaN and ±inf propagation matching the reference.
5. Tools: `compute-sanitizer --tool memcheck|racecheck|initcheck|synccheck ./app` (`--leak-check full`); `TRITON_INTERPRET=1`; MLX `verbose=True`; Metal API and shader validation (`MTL_DEBUG_LAYER=1`, `MTL_SHADER_VALIDATION=1`). Gradients: `torch.autograd.gradcheck` in fp64; for MLX compare `mx.grad` of the custom function against the reference function.

## 8. Profiling and benchmarking
- Methodology and report: `accelerator-perf` (environment block, warm-up, synchronization, ≥ 10 iterations, median/p90, parity, one variable at a time).
- Order: framework profiler → timeline → per-kernel. `torch.profiler.profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA])` then `prof.key_averages().table(sort_by="cuda_time_total", row_limit=20)`; `nsys profile -t cuda,nvtx,osrt --stats=true -o timeline python bench.py`; `ncu --set full -k regex:softmax -c 3 -o softmax python bench.py` (`--set roofline`; sections SpeedOfLight, MemoryWorkloadAnalysis, Occupancy, SourceCounters — build with `-lineinfo` for source views). Nsight Compute replays kernels with caches flushed and clocks locked by default, so its durations are not wall-clock timings.
- Apple: `MTL_CAPTURE_ENABLED=1` + `mx.metal.start_capture("k.gputrace")` … `mx.metal.stop_capture()` → open in Xcode (Metal debugger: per-dispatch GPU time, shader cost per line, counters); timelines with `xcrun xctrace record --template 'Metal System Trace' --launch -- python bench.py`.
- Report achieved GB/s (bytes moved ÷ time) and TFLOP/s next to the measured roofline, not only speedups.

## 9. Integration
- PyTorch + Triton: `@torch.library.triton_op("mylib::softmax_rows", mutates_args={})` with the launch wrapped in `torch.library.wrap_triton(kernel)[grid](...)` keeps the kernel visible to `torch.compile`/`torch.export`. Other kernels: `@torch.library.custom_op("mylib::op", mutates_args=())` (opaque to the compiler) plus `@op.register_fake` (shape/dtype propagation) and `op.register_autograd(backward, setup_context=...)`. Validate with `torch.library.opcheck(op, args)`. C++/CUDA sources: `torch.utils.cpp_extension.load_inline` for prototypes, a `CUDAExtension` build for packaging.
- MLX: kernel objects are Python callables returning `mx.array`s; add `@mx.custom_function` + `.vjp` for autodiff; C++ primitives with their own Metal kernels follow MLX's custom-extensions guide (CMake + nanobind).

## 10. Common kernel bugs
- [ ] Last partial block not masked/bounds-checked (CUDA, Triton); wrong `other=` fill for the reduction.
- [ ] Barrier inside divergent control flow (`__syncthreads`, `threadgroup_barrier`) → hang or UB; SIMD-group matrix ops not executed uniformly.
- [ ] Missing barrier between shared-memory writes and reads, or before a buffer is overwritten in the next loop iteration.
- [ ] Implicit warp-synchronous code without `_sync` masks; shuffle masks wrong for partial warps.
- [ ] 32-bit index overflow; assumed contiguity (ignored strides, broadcast stride 0); misaligned vector loads after slicing.
- [ ] Several blocks writing one output without atomics; nondeterministic atomics where bitwise reproducibility is required.
- [ ] Uninitialized outputs/accumulators (MLX outputs without `init_value`, autotuned in-place kernels without `reset_to_zero`).
- [ ] Low-precision accumulation, `exp` overflow, NaN from fully masked rows.
- [ ] Shared memory above the target's limit (tiles copied from datacenter configs), register spills, block size not a multiple of 32.
- [ ] Asynchronous errors blamed on the wrong call (no `cudaGetLastError()` after launch).

## Verify
- [ ] Profile shows the op mattered; ceiling estimated; library/compiler alternatives tried first.
- [ ] Parity against the reference at dtype-appropriate tolerances over randomized shapes, strides and special values; sanitizers/validation layers clean.
- [ ] Benchmarks follow `accelerator-perf`; achieved bandwidth or FLOP/s stated against the measured roofline.
- [ ] Every process you started is stopped; the GPU was not shared with another timing run.

## Deliverables
Kernel source and Python wrapper; tests (parity, shapes, special values, gradients); benchmark script; the `accelerator-perf` report table with the environment block; Nsight/Xcode reports or screenshots of the decisive sections; notes on tolerances, determinism and supported shapes/dtypes/architectures.
