---
name: numerical-methods
description: Load before writing or trusting any numerical computation — IEEE 754 and low-precision formats, conditioning, solvers, ODE/SDE schemes, quadrature, autodiff, mpmath checks.
---
# Numerical methods

## Scope
- Covers: designing, implementing and verifying numerical computations — floating point, linear
  algebra, root finding and optimization, ODE/SDE integration, quadrature, derivatives, reproducibility.
- Elsewhere: training-loop numerics (NaN loss, loss scaling) in `training-debug`; quantization recipes in
  `llm-quantization`; speed claims in `accelerator-perf`; statistics in `data-analysis`.
- Environments: `__CLAUDE_DIR__/venvs/sci/bin/python` (numpy, scipy, mpmath, sympy, hypothesis);
  `__CLAUDE_DIR__/venvs/ml/bin/python` (PyTorch; mlx on the Mac).
- Checked in Sept 2026 against NumPy 2.5, SciPy 1.18, mpmath 1.3, ml_dtypes 0.6, MLX 0.32 and the
  PyTorch 2.14 docs. All demo numbers below were produced with them.

## 1. IEEE 754 essentials
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

## 2. Low-precision formats
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

## 3. Conditioning, stability, backward error
- The condition number κ measures the sensitivity of the exact problem: κ(f, x) = |x f′(x)/f(x)|;
  κ(A) = ‖A‖‖A⁻¹‖ = σ_max/σ_min (`np.linalg.cond`).
- Forward error ≲ κ × backward error. A backward-stable algorithm gives the exact answer to data
  perturbed by O(u), so expect to lose about log₁₀κ digits.
- Demo: the 12×12 Hilbert matrix has κ ≈ 1.6e16. A Cholesky solve has backward error 7e-17 (stable)
  and forward error 0.19. That is ill-conditioning, not a bug.
- Always compute the normwise backward error ‖Ax̂−b‖/(‖A‖‖x̂‖+‖b‖). Small backward error with large
  forward error means reformulate, regularize, or use more precision.
- `scipy.linalg.solve` emits `LinAlgWarning` when rcond is tiny. `scipy.sparse.linalg.onenormest`
  estimates ‖A⁻¹‖₁ cheaply for large matrices.

## 4. Linear algebra: choose the factorization
| problem | use | notes |
|---|---|---|
| general Ax = b | LU with partial pivoting: `scipy.linalg.solve`; `lu_factor`/`lu_solve` for many right-hand sides | never form A⁻¹ |
| symmetric positive definite | `solve(A, b, assume_a="pos")`, `cho_factor`/`cho_solve` | Cholesky failure means not numerically SPD |
| symmetric indefinite | `assume_a="sym"` (LDLᵀ) | |
| structured | `solve_triangular`, `solve_banded`, `solve_toeplitz`; FFT for circulant | orders of magnitude cheaper |
| least squares | `scipy.linalg.lstsq` (default driver `gelsd`, SVD-based; `gelsy` QR with pivoting) | never the normal equations when κ matters: κ(AᵀA) = κ(A)² |
| rank-deficient, ill-posed | truncated SVD, Tikhonov/ridge, `lstsq(cond=…)` | report the numerical rank |
| symmetric eigenproblem | `scipy.linalg.eigh` (subsets supported) | eigenvalues well-conditioned (Weyl) |
| nonsymmetric eigenproblem | `eig`; `schur` for invariant subspaces | non-normal matrices have ill-conditioned eigenvalues: inspect pseudospectra |
| matrix functions | `expm`, `logm`, `sqrtm`, `funm`; `expm_multiply` for e^{tA}v | never via the eigendecomposition of a non-normal matrix |
| large sparse | `scipy.sparse` CSR/CSC with `spsolve`/`splu`, or iterative | |
| a few eigen/singular pairs | `eigsh`, `eigs`, `svds`, `lobpcg`; shift-invert for interior eigenvalues | |

- Iterative solvers:
  - CG for SPD (error contracts by (√κ−1)/(√κ+1) per step), MINRES for symmetric indefinite, GMRES
    (with `restart`) or BiCGSTAB for general matrices, LSQR/LSMR for least squares.
  - In SciPy ≥ 1.14 tolerances are keyword-only `rtol=`/`atol=`; the old `tol=` is gone.
  - Precondition (Jacobi, `spilu` wrapped in a `LinearOperator`, multigrid, physics-based).
  - Report the iteration count and the true residual ‖b − Ax‖, recomputed rather than the solver's
    recurrence residual.

## 5. Nonlinear equations and optimization
- Scalar roots: bracket, then `brentq` (or `root_scalar(method="brentq")`), which is guaranteed.
  Newton or secant only from a good start. Multiple roots make Newton linear.
- Systems: `scipy.optimize.root` (`hybr` default, `lm`, `krylov` for large problems). Supply the
  Jacobian and scale the variables.
- Newton converges quadratically near a simple root. Globalize with a line search (Armijo, Wolfe) or a
  trust region, and check that ‖F‖ decreases monotonically.
- `minimize`:
  - smooth: `BFGS`, `L-BFGS-B` (bounds), `Newton-CG`, `trust-ncg`, `trust-krylov`, `trust-exact`;
  - constrained: `trust-constr`, `SLSQP`, `COBYQA`;
  - derivative-free: `Nelder-Mead`, `Powell`, `COBYQA`.
- Supply gradients (`jac=True` if fun returns (f, g)) and check them first with `check_grad`.
- Nonlinear least squares: `least_squares(method="trf"|"dogbox"|"lm")`, `x_scale="jac"`, robust `loss=`
  (`soft_l1`, `huber`, `cauchy`, `arctan`). `lm` needs m ≥ n and no bounds.
- Stopping and diagnostics:
  - Combine step, scaled-gradient and function-change tolerances.
  - Always read `res.success`, `res.status` and `res.message`. Check KKT conditions for constrained
    problems.
  - For nonconvex problems use several starts and report the spread. `differential_evolution`,
    `basinhopping`, `shgo` and `dual_annealing` are heuristics, not certificates.

## 6. ODEs and SDEs
- `solve_ivp(fun, t_span, y0, method, rtol, atol, jac, dense_output, events)`:
  - The defaults rtol=1e-3, atol=1e-6 are loose. Set both explicitly, with atol per component at that
    component's scale.
  - Non-stiff: `RK45`, `DOP853` (tight tolerances), `RK23`.
  - Stiff: `Radau`, `BDF`, `LSODA` (switches automatically). Give `jac` or `jac_sparsity` for large
    systems.
- Stiffness shows up as the function-evaluation count, not the error. Demo: Robertson's problem to t =
  100 at rtol = 1e-6 took 7.3e5 RHS evaluations with RK45, but 520 with BDF, 848 with Radau and 529
  with LSODA.
- Long Hamiltonian runs need symplectic integrators (leapfrog/velocity Verlet, implicit midpoint): RK
  methods drift in energy. DAEs need a DAE solver (e.g. SUNDIALS IDA), not `solve_ivp`.
- SDEs dX = a dt + b dW:
  - Euler–Maruyama has strong order ½ and weak order 1 (strong order 1 for additive noise).
  - Milstein adds ½bb′(ΔW²−Δt) and reaches strong order 1 for scalar or commutative noise.
  - Demo: GBM with shared paths gave observed strong orders 0.51 (EM) and 0.99 (Milstein).
  - Strong-error tests must reuse the same Brownian path at every resolution (sum the fine increments).
    Weak-error tests compare E[φ(X_T)] over many paths, and the Monte Carlo error σ/√M must be well
    below the bias being measured.
  - Itô ↔ Stratonovich conversion adds the drift ½bb′.
  - Libraries (not in the venvs): torchsde for PyTorch, diffrax for JAX.

## 7. Quadrature
- 1-D: `scipy.integrate.quad(f, a, b, epsabs=1.49e-8, epsrel=1.49e-8, limit=50)` returns (value,
  abserr).
  - Put kinks and singularities in `points=`; use `weight='alg'|'alg-loga'|'cauchy'|'sin'|'cos'` for
    special integrands; infinite limits are allowed.
  - `quad_vec` for vector-valued integrands.
- Newer SciPy (≥ 1.15): `tanhsinh` (vectorized, handles endpoint singularities) and `cubature`
  (adaptive, multidimensional). `romberg` and `quadrature` were removed in 1.15.
- Sampled data: `scipy.integrate.trapezoid`/`simpson` (`np.trapz` is gone; use `np.trapezoid`).
  Gauss nodes: `numpy.polynomial.legendre.leggauss`, `scipy.special.roots_legendre`.
- Special cases: periodic analytic integrands converge exponentially under the trapezoid rule. High
  dimensions: (quasi-)Monte Carlo, e.g. scrambled `scipy.stats.qmc.Sobol` with n a power of two, and
  error bars from independent scramblings.
- Arbitrary precision: `mpmath.quad` (tanh-sinh by default, or `method='gauss-legendre'`);
  `mpmath.quadosc` for oscillatory tails.
- Never trust `abserr` alone: re-check with another method or a refined subdivision, and confirm
  integrability first.

## 8. Derivatives: autodiff vs finite differences
- Prefer autodiff:
  - PyTorch: `torch.func.grad/jacrev/jacfwd/hessian/vmap`, `torch.autograd.grad`.
  - MLX: `mx.grad`, `mx.value_and_grad`, `mx.vjp`, `mx.jvp`, `mx.vmap`.
  - Use reverse mode for scalar outputs with many inputs, forward mode for few inputs.
- Finite differences in fp64:
  - forward: h = √ε·max(1,|x|), error ~1e-8;
  - central: h = ε^{1/3}·max(1,|x|), error ~1e-11;
  - make h representable (`h = (x + h) - x`).
  - Demo: central differences reach relative error 1.4e-10 at h = 1e-6 but 2e-7 at h = 1e-10
    (roundoff).
- Complex step: f′(x) ≈ Im f(x+ih)/h with h = 1e-20 has no cancellation (the demo error was 0 to
  machine precision). It needs a real-analytic f written with complex-safe ops: no `abs`, `max`, value
  branches or `conj`.
- `scipy.differentiate.derivative`/`jacobian`/`hessian` (SciPy ≥ 1.15) are adaptive, with error
  estimates.
- Gradient checks: `torch.autograd.gradcheck` in float64 (float32 fails spuriously); `check_grad`;
  complex step; `mpmath.diff`.
- AD pitfalls:
  - Non-differentiable points: relu at 0, `abs`, `max`, `sqrt` at 0.
  - `where` with NaN or inf in the unselected branch still poisons the gradient: sanitize the input,
    not only the output.
  - In-place ops, and custom kernels without a backward.

## 9. Verification
1. High-precision reference: mpmath (`mp.mp.dps = 50`; `mp.matrix`, `mp.lu_solve`, `mp.quad`,
   `mp.odefun`, `mp.diff`) or exact sympy Rationals. The float result's relative error should be
   about κ·u.
2. Convergence order: run at h, h/2, h/4, … and fit the slope of log(error) against log(h)
   (`np.polyfit`).
   - Observed here: trapezoid 2.00, EM 0.51, Milstein 0.99.
   - A lower slope means a bug or insufficient smoothness; a plateau is the roundoff floor.
3. Manufactured solutions for ODE/PDE codes: pick u*, derive the forcing with sympy, solve, and check
   both the error and its order.
4. Invariants and special cases: conserved quantities, symmetries, limits, known closed forms.
5. Property tests (hypothesis): e.g. `solve(A, A@x) ≈ x`, permutation and scaling invariances,
   round-trips. Build test matrices with a controlled condition number (random orthogonal factors ×
   chosen singular values).
6. Cross-check implementations (NumPy vs SciPy vs mpmath; MLX vs NumPy; CPU vs GPU) at tolerances
   appropriate to each dtype.

## 10. Reproducibility
- Seeds:
  - `np.random.default_rng(seed)`: pass Generators around, with no global state.
  - `torch.manual_seed(seed)` (all devices), `mx.random.seed(seed)`, `random.seed`.
  - For DataLoader, use `worker_init_fn` plus a seeded `generator` (PyTorch reproducibility notes).
- GPU determinism:
  - `torch.use_deterministic_algorithms(True)` makes nondeterministic ops raise; `warn_only=True`
    surveys them first. Also set `torch.backends.cudnn.benchmark = False` and
    `torch.backends.cudnn.deterministic = True`.
  - Older PyTorch/CUDA stacks ask for `CUBLAS_WORKSPACE_CONFIG=:4096:8`; set it if the error says so.
  - On CUDA, atomic-add ops (`scatter_add`, `index_add`, many backward kernels) are nondeterministic.
    Some MPS ops raise under deterministic mode.
- TF32 silently changes fp32 convolutions on NVIDIA (cuDNN default), and matmuls once enabled: set
  `torch.backends.fp32_precision = "ieee"` for reference runs.
- BLAS threads change reduction order:
  - pin `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` or `VECLIB_MAXIMUM_THREADS`
    (Accelerate), or use `threadpoolctl` (installed with scikit-learn);
  - record `np.show_config()`.
- Record versions, device, dtype, BLAS, threads and seeds. Across devices, specify tolerances;
  bitwise equality is not a realistic target.

## 11. Library choices
| need | CPU (sci venv) | Mac GPU (MLX) | NVIDIA (PyTorch CUDA) |
|---|---|---|---|
| float64 dense LA, references | NumPy/SciPy (LAPACK), mpmath | CPU only (NumPy, or MLX on `mx.cpu`) | `torch.linalg` in float64: correct but slow (consumer GPUs have little fp64 throughput) |
| sparse | `scipy.sparse` | — | `torch.sparse` (limited) |
| batched fp32/bf16 kernels | NumPy | `mlx.core`, `mx.compile` | `torch`, `torch.compile` |
| autodiff | — | `mx.grad` | `torch.func` |
| ODE/SDE | `solve_ivp`, hand-written SDE schemes | hand-written | torchdiffeq/torchsde (install per project) |

## Report
```
Problem:         <math statement, sizes, dtype, conditioning estimate>
Method:          <algorithm, library + version, tolerances, device, precision settings (TF32 etc.)>
Result:          <values with error estimates or uncertainty>
Verification:    <reference (mpmath dps), observed vs expected order, residuals, invariants>
Reproducibility: <seeds, versions, BLAS/threads, determinism flags>
Caveats:         <ill-conditioning, stiffness, precision limits, untested regimes>
```
