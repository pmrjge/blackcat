---
name: gpu-metal-mlx
description: Use when writing a custom Metal kernel through MLX on Apple Silicon — metal_kernel API, SIMD-group reductions, GPU capture, MLX integration.
---
# MLX custom Metal kernels (Apple Silicon)
Hub: `gpu-kernel-dev` (is a kernel justified, performance model, device table; numerics and correctness in `gpu-kernel-dev` `references/numerics-correctness.md`). Benchmarks: `accelerator-perf`. Version facts here were checked earlier without recorded URLs (unverified as of 2026-10-02) unless a Sources line says otherwise.

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

## Profiling (Apple)
- Apple: `MTL_CAPTURE_ENABLED=1` + `mx.metal.start_capture("k.gputrace")` … `mx.metal.stop_capture()` → open in Xcode (Metal debugger: per-dispatch GPU time, shader cost per line, counters); timelines with `xcrun xctrace record --template 'Metal System Trace' --launch -- .venv/bin/python bench.py`.

## Integration
- MLX: kernel objects are Python callables returning `mx.array`s; add `@mx.custom_function` + `.vjp` for autodiff; C++ primitives with their own Metal kernels follow MLX's custom-extensions guide (CMake + nanobind).

## Verify
- [ ] Parity against the MLX reference op (`mx.fast.rms_norm`, plain `mx` ops in float32) over random shapes, including partial threadgroups; tolerances per `gpu-kernel-dev` `references/numerics-correctness.md`.
- [ ] `verbose=True` source inspected once; `math_mode` left at `safe` unless edge cases are impossible.
- [ ] Timing with `mx.eval` + `mx.synchronize`, method per `accelerator-perf`.

## Sources
- Verified 2026-10-02 https://pypi.org/pypi/mlx/json — MLX 0.32.3; https://ml-explore.github.io/mlx/build/html/python/fast.html — `mx.fast.metal_kernel`, `mx.fast.cuda_kernel` (and `precompiled_cuda_kernel`) documented.
