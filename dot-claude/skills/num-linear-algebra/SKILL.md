---
name: num-linear-algebra
description: Use when solving linear systems, least squares or eigenproblems — conditioning, picking a factorization, iterative solvers, preconditioners.
---
# Numerical linear algebra
Hub: `numerical-methods` (conditioning and backward error §3, verification §9; floating point and reproducibility in its `references/`). Environment: `__CLAUDE_DIR__/venvs/sci/bin/python` (NumPy/SciPy).

## Choose the factorization
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

## Verify
- [ ] Normwise backward error ‖Ax̂−b‖/(‖A‖‖x̂‖+‖b‖) reported, with κ (`np.linalg.cond` or `onenormest` for large A); forward error judged against κ·u (hub §3).
- [ ] Iterative solves: iteration count and the recomputed true residual reported, not the recurrence residual.
- [ ] Cross-check on a small instance against mpmath (`mp.lu_solve`) or a dense SciPy solve.
- [ ] Rank-deficient problems: numerical rank and the cutoff used are stated.

## Sources
- Verified 2026-10-02 https://docs.scipy.org/doc/scipy/release/1.14.0-notes.html — `tol` removed from `scipy.sparse.linalg` iterative solvers in favour of `rtol`; https://pypi.org/pypi/scipy/json — SciPy 1.18.1 is current.
- Other API details checked in Sept 2026 against SciPy 1.18 (hub note; no URL recorded): unverified as of 2026-10-02.
