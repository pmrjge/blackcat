# Numerical methods — nonlinear equations and optimization (reference)
Read when finding roots, solving nonlinear systems, minimizing (scipy.optimize: brentq, root, minimize, least_squares) or judging convergence of an optimizer. Parent: `numerical-methods` SKILL.md (environments and the Sept 2026 version note are there).

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
