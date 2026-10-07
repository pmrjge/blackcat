---
name: num-ode-sde
description: Use to integrate ODEs or SDEs — tolerances, stiffness, implicit and symplectic schemes, order.
---
# ODE and SDE integration
Hub: `numerical-methods` (verification §9 — convergence-order fits and manufactured solutions; floating point, reproducibility and the library table in its `references/`). Environment: `__CLAUDE_DIR__/venvs/sci/bin/python`.

## Solvers and schemes
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

## Verify
- [ ] Tolerances set explicitly (rtol and per-component atol); result stable when both are tightened 10×.
- [ ] Function-evaluation count reported (`sol.nfev`); a large count at loose tolerance signals stiffness → implicit method.
- [ ] Convergence order observed on a problem with a known solution matches the scheme (fit log error vs log h, hub §9).
- [ ] SDEs: strong errors use the same Brownian path at every resolution; weak errors have Monte Carlo error σ/√M well below the bias.
- [ ] Conserved quantities (energy, mass) tracked over long runs.

## Sources
- Demo numbers and API details were produced in Sept 2026 with SciPy 1.18 (hub note; no URL recorded): unverified as of 2026-10-02. Latest SciPy 1.18.1 — Verified 2026-10-02 https://pypi.org/pypi/scipy/json.
