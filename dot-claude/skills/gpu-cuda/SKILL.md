---
name: gpu-cuda
description: Use when writing or profiling CUDA C++ kernels — sm_120 builds, warp-level reductions, Nsight Systems and Compute, registering torch ops.
---
# CUDA C++ (NVIDIA, including RTX 50-series)
Hub: `gpu-kernel-dev` (is a kernel justified, performance model, device table; numerics and correctness in `gpu-kernel-dev` `references/numerics-correctness.md`). Benchmarks: `accelerator-perf`. Version facts here were checked earlier without recorded URLs (unverified as of 2026-10-02) unless a Sources line says otherwise.

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

## Profiling (NVIDIA)
- Order: framework profiler → timeline → per-kernel. `torch.profiler.profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA])` then `prof.key_averages().table(sort_by="cuda_time_total", row_limit=20)`; `nsys profile -t cuda,nvtx,osrt --stats=true -o timeline python bench.py`; `ncu --set full -k regex:softmax -c 3 -o softmax python bench.py` (`--set roofline`; sections SpeedOfLight, MemoryWorkloadAnalysis, Occupancy, SourceCounters — build with `-lineinfo` for source views). Nsight Compute replays kernels with caches flushed and clocks locked by default, so its durations are not wall-clock timings.

## Integration with PyTorch
- Other kernels: `@torch.library.custom_op("mylib::op", mutates_args=())` (opaque to the compiler) plus `@op.register_fake` (shape/dtype propagation) and `op.register_autograd(backward, setup_context=...)`. Validate with `torch.library.opcheck(op, args)`. C++/CUDA sources: `torch.utils.cpp_extension.load_inline` for prototypes, a `CUDAExtension` build for packaging.

## Verify
- [ ] `compute-sanitizer` memcheck/racecheck clean; `cudaGetLastError()` checked after every launch in debug builds.
- [ ] Parity against a PyTorch reference over shapes and special values (`gpu-kernel-dev` `references/numerics-correctness.md`); `torch.library.opcheck` passes for registered ops.
- [ ] Build line records `-gencode` targets; `-Xptxas -v` shows no unexpected spills.

## Sources
- Verified 2026-10-02 https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html — release notes titled "CUDA Toolkit 13.4 Update 1" (latest; date unverified).
