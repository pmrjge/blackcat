---
name: num-optimization
description: Use when finding roots or minimizing smooth functions with scipy.optimize — bracketing, Newton, BFGS, least squares; LP/MIP is opt-modeling.
---
# Nonlinear equations and optimization
Hub: `numerical-methods` (conditioning §3, verification §9; reproducibility in `numerical-methods` `references/reproducibility.md`). Environments: `__CLAUDE_DIR__/venvs/sci/bin/python`, `__CLAUDE_DIR__/venvs/ml/bin/python`. Version-specific API notes were checked in Sept 2026 without recorded URLs (unverified as of 2026-10-02); latest releases are Verified in the hub.


## Nonlinear equations and optimization
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

Linear, mixed-integer and convex models with modeling languages and solvers (HiGHS, CVXPY, Pyomo): `opt-modeling`; CP-SAT and exact combinatorial search: `algorithm-design` §2.10.

## Verify
- [ ] `res.success`, `res.status`, `res.message` read and reported; constrained problems checked against KKT conditions.
- [ ] Gradients checked with `check_grad` (or autodiff) before the run.
- [ ] Nonconvex problems: several starts with the spread of optima reported.
- [ ] Root finds: the residual ‖F(x)‖ at the answer reported, and a bracket where one exists.
