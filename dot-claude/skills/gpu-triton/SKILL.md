---
name: gpu-triton
description: Use for Triton kernels — block tensors, masking, tl.dot, autotuning, interpreter debugging, torch op wrapping.
---
# Triton
Hub: `gpu-kernel-dev` (is a kernel justified, performance model, device table; numerics and correctness in `gpu-kernel-dev` `references/numerics-correctness.md`). Benchmarks: `accelerator-perf`. Version facts here were checked earlier without recorded URLs (unverified as of 2026-10-02) unless a Sources line says otherwise.

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

## Integration with PyTorch
- PyTorch + Triton: `@torch.library.triton_op("mylib::softmax_rows", mutates_args={})` with the launch wrapped in `torch.library.wrap_triton(kernel)[grid](...)` keeps the kernel visible to `torch.compile`/`torch.export`.

## Verify
- [ ] Masked loads use a neutral `other=` for the reduction; the last partial block is tested.
- [ ] Parity in `TRITON_INTERPRET=1` and on the GPU against a PyTorch reference (`gpu-kernel-dev` `references/numerics-correctness.md`).
- [ ] Autotune configs fit ≤ 99 KB shared memory on sm_120; in-place kernels use `reset_to_zero`/`restore_value`.

## Sources
- Verified 2026-10-02 https://pypi.org/pypi/triton/json — Triton 3.8.0 (the `tl.dot` notes above are written for 3.8).
