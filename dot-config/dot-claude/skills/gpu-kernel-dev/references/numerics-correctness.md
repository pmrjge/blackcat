# GPU kernels — numerics, correctness and common bugs (reference)
Read when choosing accumulation precision or tolerances, writing parity tests, or reviewing a kernel for the usual bugs. Parent: `gpu-kernel-dev` SKILL.md.

## Numerics
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

## Correctness
1. Reference: the same computation in plain framework ops at higher precision (fp32, or fp64 on CPU), including identical quantize/dequantize steps for low-precision formats.
2. Tolerances by dtype — `torch.testing.assert_close` defaults: fp32 rtol 1.3e−6 / atol 1e−5, fp16 1e−3 / 1e−5, bf16 1.6e−2 / 1e−5; widen with reduction length K (typical error ∝ √K·ε, worst case ∝ K·ε). Best test: your kernel's error against the fp64 reference is no worse than the framework's own low-precision op against the same reference.
3. Shapes: randomized, plus 1, primes, sizes just below/above block multiples and powers of two, empty tensors, non-contiguous/transposed/broadcast (stride 0) inputs, batch dims, and > 2^31 total elements (32-bit index overflow).
4. Values: normal, large magnitude (fp16 overflow), tiny/denormal, all-equal, NaN and ±inf propagation matching the reference.
5. Tools: `compute-sanitizer --tool memcheck|racecheck|initcheck|synccheck ./app` (`--leak-check full`); `TRITON_INTERPRET=1`; MLX `verbose=True`; Metal API and shader validation (`MTL_DEBUG_LAYER=1`, `MTL_SHADER_VALIDATION=1`). Gradients: `torch.autograd.gradcheck` in fp64; for MLX compare `mx.grad` of the custom function against the reference function.

## Common kernel bugs
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
