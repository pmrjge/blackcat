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
  PyTorch 2.14 docs. All demo numbers below were produced with them (no URLs recorded: unverified as of
  2026-10-02). Latest releases Verified 2026-10-02: NumPy 2.5.3 (https://endoflife.date/api/numpy.json),
  SciPy 1.18.1 (https://pypi.org/pypi/scipy/json), mpmath 1.4.1 (https://pypi.org/pypi/mpmath/json),
  ml_dtypes 0.6.0 (https://pypi.org/pypi/ml-dtypes/json).

## Modules
| Module | Load when |
|---|---|
| `num-linear-algebra` | solving linear systems, least squares, eigenproblems, matrix functions, sparse/iterative solvers |
| `num-ode-sde` | integrating ODEs or SDEs: tolerances, stiffness, symplectic/DAE, strong and weak order |
| `num-floating-point` | IEEE 754 rounding, cancellation, summation, NaN/subnormals, fp16/bf16/fp8/fp4 and framework precision flags |
| `num-optimization` | roots, nonlinear systems, minimization and nonlinear least squares with scipy.optimize |
| `num-quadrature-autodiff` | numerical integration (quad, tanh-sinh, cubature, QMC, mpmath) and derivatives (autodiff, FD, complex step) |

## References
- `references/reproducibility.md` — read when seeding, chasing nondeterminism (GPU, TF32, BLAS threads) or choosing a library per device.

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

## Report
```
Problem:         <math statement, sizes, dtype, conditioning estimate>
Method:          <algorithm, library + version, tolerances, device, precision settings (TF32 etc.)>
Result:          <values with error estimates or uncertainty>
Verification:    <reference (mpmath dps), observed vs expected order, residuals, invariants>
Reproducibility: <seeds, versions, BLAS/threads, determinism flags>
Caveats:         <ill-conditioning, stiffness, precision limits, untested regimes>
```
