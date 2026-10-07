# Method of manufactured solutions (MMS) and convergence studies

## Procedure
1. Choose a smooth exact solution u* that exercises every term (non-polynomial in all variables, nonzero on boundaries, not in the discrete space — e.g. `sin(πx)·cos(2πy)·exp(t)`), with non-trivial coefficients.
2. Compute the source term f = L(u*) and boundary/initial data symbolically (sympy via `uv run --with sympy`, or UFL's own differentiation applied to a symbolic expression) — never by hand.
3. Solve on a sequence of uniformly refined meshes h, h/2, h/4, h/8 (≥ 3 levels) with tight solver tolerances (solver error ≪ discretization error).
4. Measure errors in the norms the theory predicts (L², H¹ seminorm, L∞, or the quantity of interest), using a higher-degree quadrature/interpolation of u*.
5. Observed order p = log(e_i / e_{i+1}) / log(h_i / h_{i+1}); compare with theory.

## Expected orders (smooth solutions)
| discretization | L² | H¹ |
|---|---|---|
| Lagrange degree k | k+1 | k |
| Taylor–Hood P2–P1 (velocity / pressure) | 3 / 2 | 2 / — |
| DG degree k (SIPG) | k+1 | k (broken) |
| 2nd-order FV | 2 | — |
| time: backward Euler / CN / BDF2 | 1 / 2 / 2 in Δt (refine Δt with h so space error doesn't dominate) | |

## Interpreting results
- Order lower than expected everywhere → bug in the weak form, boundary terms or the source term.
- Correct in interior, wrong near boundaries → boundary condition implementation (weak vs strong, curved boundaries with low-order geometry).
- Order degrades on fine meshes → solver tolerance or floating-point floor reached; tighten or stop refining.
- Singular true solutions (corners, discontinuous coefficients) legitimately reduce orders: MMS must use smooth solutions; test singular cases separately against known rates.

## Report
Table of h, DoFs, error per norm, observed order; plot log error vs log h with reference slopes; solver settings; library versions; commit.
