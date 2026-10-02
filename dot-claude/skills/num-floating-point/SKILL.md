---
name: num-floating-point
description: Use when float accuracy matters — rounding, cancellation, compensated sums, fp16/bf16/fp8/fp4.
---
# Floating point and low-precision formats
Hub: `numerical-methods` (conditioning §3, verification §9; reproducibility in `numerical-methods` `references/reproducibility.md`). Environments: `__CLAUDE_DIR__/venvs/sci/bin/python`, `__CLAUDE_DIR__/venvs/ml/bin/python`. Version-specific API notes were checked in Sept 2026 without recorded URLs (unverified as of 2026-10-02); latest releases are Verified in the hub.


## IEEE 754 essentials
- Rounding model: fl(x∘y) = (x∘y)(1+δ), |δ| ≤ u.
  - binary64: u = 2⁻⁵³ ≈ 1.1e-16, and `np.finfo(float).eps` = 2u.
  - binary32: u = 2⁻²⁴ ≈ 6.0e-8.
  - Spacing: `np.spacing(x)`, `math.ulp(x)`, `np.nextafter`.
- Comparing floats: use `abs(a-b) <= atol + rtol*abs(b)`. Defaults differ: `np.isclose` has
  atol=1e-8, `math.isclose` has abs_tol=0. Compare near zero with an explicit atol.
- Subnormals (below 2.2e-308 in fp64, 1.2e-38 in fp32) lose precision gradually. Flush-to-zero modes
  change results, and subnormal arithmetic can be very slow on CPUs.
- NaN propagates through arithmetic but not through comparisons: `np.maximum` propagates NaN, `np.fmax`
  ignores it, and Python's `max` depends on argument order. Inf − Inf and 0·Inf are NaN; `x != x`
  detects NaN.
- Catastrophic cancellation: subtracting nearly equal numbers destroys relative accuracy. Rewrite:
  - `1-cos(x)` → `2*sin(x/2)**2` (at x = 1e-10 the naive form gives 0.0; the rewrite gives 5e-21);
  - `log(1+x)` → `log1p`; `exp(x)-1` → `expm1`; `sqrt(x*x+y*y)` → `hypot`;
  - log-sum-exp with a max shift (`scipy.special.logsumexp`); softmax likewise;
  - quadratic roots via q = −½(b + sign(b)√(b²−4ac)), x₁ = q/a, x₂ = c/q;
  - variance by two passes or Welford, never E[x²] − E[x]².
- Summation error:
  - Recursive sum: up to (n−1)u·∑|xᵢ|.
  - Pairwise (NumPy's `np.sum` along a contiguous axis): O(u log n).
  - Kahan/Neumaier: O(u), independent of n. `math.fsum` is correctly rounded.
  - Demo: 2·10⁵ float32 values near 1000 summed in a float32 loop are off by 1.9e3; `np.sum` is off by
    6, less than one ulp of the result.
  - Accumulate in a wider type.
- FMA computes a·b+c with a single rounding (`math.fma` needs Python ≥ 3.13). Compilers may contract
  a*b+c into an FMA (`-ffp-contract`), so builds and devices can differ bitwise.
- Floating-point addition is not associative, so parallel and GPU reductions are not bitwise
  reproducible unless the reduction order is fixed.

## Low-precision formats
Parameters from `ml_dtypes.finfo` (not in the sci venv; `uv pip install ml_dtypes` in a project env):

| format | exp/mantissa bits | eps | max | min normal | min subnormal | inf / NaN |
|---|---|---|---|---|---|---|
| fp32 | 8/23 | 1.19e-7 | 3.40e38 | 1.18e-38 | 1.4e-45 | yes / yes |
| tf32 (tensor-core matmul) | 8/10 | 9.8e-4 | fp32 range | | | internal format |
| fp16 | 5/10 | 9.77e-4 | 65504 | 6.10e-5 | 5.96e-8 | yes / yes |
| bf16 | 8/7 | 7.81e-3 | 3.39e38 | 1.18e-38 | 9.2e-41 | yes / yes |
| fp8 E4M3 (`e4m3fn`) | 4/3 | 0.125 | 448 | 1.56e-2 | 1.95e-3 | no / yes |
| fp8 E5M2 | 5/2 | 0.25 | 57344 | 6.10e-5 | 1.53e-5 | yes / yes |
| fp4 E2M1 | 2/1 | 0.5 | 6 | 1 | 0.5 | none: values ±{0, .5, 1, 1.5, 2, 3, 4, 6} |
| E8M0 (scales only) | 8/0 | — | 2¹²⁷ | 2⁻¹²⁷ | — | no / yes; powers of two only, no zero |

- Block scaling:
  - OCP MX formats (MXFP8/6/4): one E8M0 scale per 32 elements.
  - NVFP4: E2M1 elements with an FP8 E4M3 scale per 16 elements plus a per-tensor FP32 scale (Blackwell
    tensor cores, including the RTX 5070 Ti).
  - Reference: Micikevicius et al., "FP8 Formats for Deep Learning", arXiv:2209.05433.
- Where the formats break:
  - fp16 overflows above 65504 (logits, squared norms, loss sums) and underflows small gradients, hence
    loss scaling.
  - bf16 has fp32's range but only 8 significand bits (2–3 decimal digits): `256 + 1 == 256` in bf16. Never use bf16
    positions, timesteps, or large-argument sin/cos; accumulate and do softmax, norm statistics and
    losses in fp32.
  - fp8: E4M3 for weights and activations, E5M2 for gradients; scaling (per-tensor or per-block) is
    mandatory.
  - A plain cast of an out-of-range value to E4M3 gives NaN (ml_dtypes; the format has no inf), so
    scale and clamp to ±448 first. E5M2 overflows to inf.
- Framework facts:
  - PyTorch dtypes: `torch.float8_e4m3fn`, `float8_e5m2`, the `…fnuz` variants, `float8_e8m0fnu`,
    `float4_e2m1fn_x2` (two values packed per byte). These are "shell" dtypes with limited op support.
  - PyTorch ≥ 2.9 controls TF32 with `torch.backends.cuda.matmul.fp32_precision` and
    `torch.backends.cudnn.conv.fp32_precision` (`"ieee"` or `"tf32"`, or globally
    `torch.backends.fp32_precision`). The old `allow_tf32` flags are slated for deprecation; do not mix
    old and new.
  - fp16/bf16 GEMMs may use reduced-precision reductions, enabled by default. The flags are
    `allow_fp16_reduced_precision_reduction` and `allow_bf16_reduced_precision_reduction` under
    `torch.backends.cuda.matmul`.
  - Apple: PyTorch MPS has no float64. MLX float64 is CPU-only (GPU ops raise), and several `mx.linalg`
    factorizations run on the CPU stream (`stream=mx.cpu`). High-precision references on the Mac
    therefore run on the CPU.

## Verify
- [ ] Each cancellation-prone expression rewritten (log1p, expm1, hypot, two-pass variance) or shown harmless at the inputs used.
- [ ] Result compared with an mpmath or wider-precision reference; relative error ≈ κ·u for the working precision.
- [ ] Low-precision paths: accumulations, softmax, norms and losses in fp32; casts to fp8/fp4 scaled and clamped first; range checked against the table.
- [ ] Framework precision flags (TF32, reduced-precision reductions) stated in the report.
