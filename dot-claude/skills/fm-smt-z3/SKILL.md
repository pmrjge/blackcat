---
name: fm-smt-z3
description: Use for proving arithmetic, bit-vector or invariant claims with z3 — encodings, counterexamples, unsat cores.
---
# SMT with z3 (Python)
Hub: `formal-methods` (tool choice, what each result guarantees — §7, report table). Tool versions and commands were checked earlier without recorded URLs: unverified as of 2026-10-02 unless a Sources line says otherwise.

z3-solver is in the sci venv: `__CLAUDE_DIR__/venvs/sci/bin/python`. To prove P, assert ¬P: `unsat` = proved for the encoding, `sat` = counterexample in `s.model()`, `unknown` (timeout, quantifiers, nonlinear integers) = nothing proved.
```python
from z3 import *

# Midpoint of unsigned 32-bit indices: naive form overflows, safe form stays in range.
lo, hi = BitVecs("lo hi", 32)
s = Solver(); s.add(ULE(lo, hi), Not(BVAddNoOverflow(lo, hi, False)))
print(s.check(), s.model())                 # sat: e.g. lo=1, hi=2^32-1 -> (lo+hi)/2 overflows
s = Solver(); mid = lo + LShR(hi - lo, 1)
s.add(ULE(lo, hi), Not(And(ULE(lo, mid), ULE(mid, hi))))
print(s.check())                            # unsat: holds for every pair with lo <= hi

# Inductive invariant for: i = 0; t = 0; while i < n: t += i; i += 1   (claim: 2t = i(i-1))
i, t, n, i1, t1 = Ints("i t n i1 t1")
inv = lambda i, t: And(2 * t == i * (i - 1), 0 <= i, i <= n)
def valid(f):
    v = Solver(); v.add(Not(f)); return v.check() == unsat
print(valid(Implies(And(i == 0, t == 0, n >= 0), inv(i, t))),                       # initiation
      valid(Implies(And(inv(i, t), i < n, i1 == i + 1, t1 == t + i), inv(i1, t1))),  # consecution
      valid(Implies(And(inv(i, t), Not(i < n)), 2 * t == n * (n - 1))))             # exit => post
```
Encoding rules:
- `Int`/`Real` are mathematical: no overflow, so they cannot find overflow bugs. Model machine integers with `BitVec(width)`. On bit-vectors `<`, `/`, `%`, `>>` are signed; use `ULT/ULE/UDiv/URem/LShR` for unsigned. Overflow predicates: `BVAddNoOverflow(a, b, signed)`, `BVMulNoOverflow`, `BVSubNoUnderflow`, `BVSDivNoOverflow`.
- IEEE floats: `FP("x", Float32())` sorts are bit-precise but slow; modeling floats as `Real` ignores rounding, NaN and infinities.
- Straight-line code → SSA (a fresh variable per assignment); loops → an inductive invariant (three checks above) or bounded unrolling (only a bounded claim).
- Vacuity: check the assumptions alone are satisfiable — contradictory preconditions make every property "proved".
- Quantifiers: E-matching/MBQI may give `unknown` or run forever. Prefer quantifier-free encodings; add `patterns=[...]` to `ForAll`; set `s.set("timeout", ms)`. Nonlinear integer arithmetic is undecidable — bound the range and use bit-vectors.
- Debugging unsat: `s.set(unsat_core=True)`, `s.assert_and_track(expr, "label")`, `s.unsat_core()` (add `s.set("core.minimize", True)` for a smaller core). Incremental queries: `push()`/`pop()`.
- Optimization: `Optimize()` with `minimize`/`maximize` (then `h.value()`), `add_soft(expr, weight)` for MaxSAT. For large combinatorial optimization prefer a MIP/CP solver (`algorithm-design`).

## Verify
- [ ] The property is negated correctly (assert ¬P; `unsat` = proved for the encoding).
- [ ] Assumptions alone are satisfiable (non-vacuity), and a seeded bug yields `sat` with a counterexample.
- [ ] Machine integers modeled as bit-vectors with the right signedness; `unknown` reported as nothing proved.
- [ ] z3 version recorded (`z3.get_version_string()`).
