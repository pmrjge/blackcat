# Algorithm design: solvers

Read when a problem may go to an exact solver (SAT/SMT/MIP/CP) (moved from `algorithm-design` SKILL.md).

### 2.10 Exact search with solvers
Use a solver when the problem is NP-hard with modest size, carries many side constraints, or optimality must be proven; a hand-written branch and bound is rarely better and is harder to trust.

| Problem shape | Tool |
|---|---|
| Linear objective and constraints, continuous or mixed-integer | HiGHS: `scipy.optimize.milp` / `linprog(method="highs")` (sci venv), or `highspy` |
| Scheduling, assignment, sequencing with logical/global constraints, integer data | OR-Tools CP-SAT |
| Pure Boolean clauses and cardinalities | SAT via PySAT (`python-sat`: CaDiCaL, Glucose, …) |
| Bit-vector/arithmetic/logic queries, invariant checks | z3 (`fm-smt-z3`) |

```python
from ortools.sat.python import cp_model          # recent OR-Tools: snake_case API
durations, m = [3, 7, 2, 5, 4, 6, 1], 3
model = cp_model.CpModel()
x = {(j, k): model.new_bool_var(f"x{j}_{k}") for j in range(len(durations)) for k in range(m)}
for j in range(len(durations)):
    model.add_exactly_one(x[j, k] for k in range(m))
makespan = model.new_int_var(0, sum(durations), "makespan")
for k in range(m):
    model.add(sum(durations[j] * x[j, k] for j in range(len(durations))) <= makespan)
model.minimize(makespan)
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 30
solver.parameters.num_workers = 8
status = solver.solve(model)
print(solver.status_name(status), solver.objective_value, solver.best_objective_bound)
```
Formulation hygiene: tight variable bounds; prefer enforcement literals (`.only_enforce_if(b)`) over big-M; break symmetries (identical machines → order their loads); add redundant constraints that tighten the relaxation; warm-start with `add_hint`; always set a time limit and report OPTIMAL vs FEASIBLE plus the bound (gap). Re-check the returned solution with an independent plain-code checker.
