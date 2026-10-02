---
name: opt-modeling
description: Use when formulating LP, MIP or convex models — HiGHS, CVXPY, Pyomo, PuLP; infeasibility, duals, gaps.
---
# Optimization modeling (LP, MIP, convex)

## Scope
Turning a decision problem into a mathematical program and solving it with a modeling layer and a solver. CP-SAT, SAT and exact combinatorial search with a worked example: `algorithm-design` §2.10. Smooth nonlinear minimization and root finding with scipy: `num-optimization`. Bit-level/logic queries: `fm-smt-z3`.

## Formulate on paper first
1. **Sets and indices** (products, periods, machines), **parameters** (data with units), **decision variables** (continuous, integer, binary; with bounds), **objective** (one, with units), **constraints** (each named and explained in a sentence).
2. Check dimensions and units for every constraint; scale data so coefficients span a few orders of magnitude (badly scaled models give wrong "optimal" answers or numerical failures).
3. Classify the model: LP, MILP, convex QP/SOCP/SDP, or nonconvex — this fixes the solver class and what "optimal" means.

## Modeling layers and solvers
| Model | Layer → solver |
|---|---|
| LP / MILP | `scipy.optimize.milp` or `linprog(method="highs")`, `highspy` directly, PuLP or Pyomo → HiGHS (open source); commercial solvers (Gurobi, CPLEX, Xpress) when size or speed demands it and the licence allows |
| Convex (QP, SOCP, SDP, norms, log-sum-exp) | CVXPY (disciplined convex programming: the model is rejected if convexity can't be proven) → Clarabel, OSQP, SCS, ECOS-family or commercial solvers |
| Large structured models, decomposition, nonlinear | Pyomo (→ HiGHS, IPOPT for NLP, commercial MINLP solvers) |
| Scheduling/assignment with logical constraints | OR-Tools CP-SAT (`algorithm-design` §2.10) |

Solver availability and default backends per layer: unverified as of 2026-10-02 — check the installed versions.

## Formulation hygiene (MIP)
- Tight bounds on every variable; big-M only with the smallest valid M (derive it), or indicator constraints where the solver supports them.
- Break symmetry (identical machines/vehicles: order them); add valid inequalities that tighten the relaxation.
- Warm-start with a feasible heuristic solution; set a time limit and a relative gap; report status (optimal / feasible with gap / infeasible / unbounded / time limit) plus the best bound.
- Prefer a sequence of small models (aggregate, then refine) to one monster model.

## When it goes wrong
- **Infeasible:** compute an IIS (irreducible infeasible subset) if the solver offers it, or add slack variables with penalties to see which constraints bind; check data (units, signs, totals).
- **Unbounded:** a missing bound or constraint; bound every variable temporarily to find which runs away.
- **Slow MIP:** look at the gap over time; weak relaxation (big-M), symmetry, or poor scaling are the usual causes.
- **Numerical warnings:** rescale; avoid tiny and huge coefficients in the same row.

## Use the answer
- Validate the solution with an independent plain-code checker (all constraints, objective recomputed).
- Duals/shadow prices (LP) and reduced costs explain which constraints drive the cost; for MIP, sensitivity comes from re-solving with perturbed data.
- Report the decision in domain terms, the objective with units, the gap, run time and solver version, and the assumptions the model leaves out.

## Verify
- [ ] Every constraint has a sentence explaining it and a unit check.
- [ ] Solver status, objective, best bound/gap and time limit reported; solver and layer versions recorded.
- [ ] Independent checker confirms feasibility and the objective value.
- [ ] A small instance solved by brute force or by hand matches the model.

## Sources
- Verified 2026-10-02 https://pypi.org/pypi/cvxpy/json — CVXPY 1.9.3; https://pypi.org/pypi/pyomo/json — Pyomo 6.10.1.
- Unverified as of 2026-10-02: latest OR-Tools and highspy versions (PyPI pages showed 9.15.6755 and 1.15.1 without confirmation), solver backends named above.
