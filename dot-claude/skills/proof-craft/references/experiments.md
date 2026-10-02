# proof-craft — experiments (reference)
Read when testing a conjecture numerically or symbolically before proving it. Parent: `proof-craft` SKILL.md.

## 2. Experiment before proving
Small cases first, by hand and by machine, with `__CLAUDE_DIR__/venvs/sci/bin/python` (sympy, mpmath,
numpy, networkx, hypothesis, z3-solver). Use `mcp__wolfram`, if available, as an independent CAS.
```python
import sympy as sp, mpmath as mp, z3
from hypothesis import given, settings, strategies as st
k, N = sp.symbols("k N", integer=True, positive=True)
sp.factor(sp.summation(k**3, (k, 1, N)))                 # N**2*(N + 1)**2/4
a = sp.Function("a"); n = sp.symbols("n", integer=True, nonnegative=True)
sp.rsolve(a(n+2) - a(n+1) - a(n), a(n), {a(0): 0, a(1): 1})   # closed form of a recurrence
mp.mp.dps = 50
mp.identify(mp.zeta(2), ["pi"])                          # 'pi*((1/6)*pi)'; returns None without a basis
mp.findpoly(mp.sqrt(2) + mp.sqrt(3), 4, maxcoeff=100)    # [1, 0, -10, 0, 1]
mp.pslq([mp.pi**2, mp.zeta(2)], maxcoeff=100)            # [1, -6]: integer relation
x, y = z3.Ints("x y"); s = z3.Solver(); s.add(x > 0, y > 0, x*x + y*y == 25, x < y)
print(s.check(), s.model())                              # sat [y = 4, x = 3]
u, v = z3.Reals("u v")
z3.prove(z3.Implies(z3.And(u > 0, v > 0), (u + v)**2 >= 4*u*v))   # prints "proved"

@settings(max_examples=2000, deadline=None)
@given(st.integers(1, 10**6))
def test_claim(m):
    assert sp.isprime(m*m + m + 41)                      # fails; Hypothesis reports a shrunk example
```
- Hypothesis shrinking is heuristic: on the claim above it reported 170, while the least counterexample
  is 40. When "smallest counterexample" matters, sweep exhaustively.
- z3 decides quantifier-free linear arithmetic and bit-vector problems. It may answer `unknown` on
  nonlinear integer problems, and its handling of quantifiers (`ForAll`) is incomplete. Treat `unknown` as no information. Bit-vectors
  model machine integers (`(p + q) / 2` overflows).
- Integer sequences: compute 10–20 terms and look them up on OEIS (`https://oeis.org/search?q=1,2,5,14&fmt=json`).
- Inequalities: sample randomly and near the conjectured equality case, including extreme scales; a
  minimizer from `scipy.optimize` suggests where equality holds.
- A numeric agreement is evidence, not proof. Record what was checked, and on which range.
