---
name: proof-craft
description: Load before proving, disproving, repairing or refereeing a mathematical claim — statement dissection, counterexample search (sympy, z3), strategy catalog, per-step checks.
---
# Proof craft

## Scope
- Covers: deciding whether a claim is true, proving it, disproving it with a counterexample, repairing a
  broken proof, refereeing someone else's proof, and writing the result up.
- Not here: competition problems (IMO, Putnam, USAMO, AIME: the `math-olympiad` plugin skill runs its multi-agent solve-and-verify workflow), machine-checked proofs (`lean-formalization`), categorical arguments in depth
  (`category-theory`), floating-point error analysis (`numerical-methods`).
- Default stance: a claim is unproven until every step is justified and the checks in §6 pass. Say
  "I could not prove it" rather than paper over a gap.

## 1. Dissect the statement
1. Rewrite it fully quantified. Mark quantifier order and what each constant may depend on:
   ∀x ∀ε ∃δ(ε,x) ∀y (pointwise) is not ∀ε ∃δ(ε) ∀x ∀y (uniform). Swapping ∃ and ∀ is the most
   common silent error.
2. Fix conventions: ℕ ∋ 0?; rings unital/commutative?; "positive" = >0 or ≥0; log base; measurable
   w.r.t. which σ-algebra; "a.e." w.r.t. which measure; ⊂ strict or not; graphs simple/finite/connected.
3. For each hypothesis ask what breaks without it, and find the counterexample that shows it is
   needed. If none exists, the theorem may be stronger than stated, or the hypothesis is hiding a gap.
4. List degenerate cases: n = 0, 1; empty set or sum; zero map or matrix; trivial group or zero ring;
   characteristic 2 or 3; boundary points; equality cases of inequalities; infinite values.
5. Negate the claim correctly (push ¬ through every quantifier): that is the exact specification a
   counterexample must meet.
6. Decide the target: prove, disprove, or find the right statement (weakest hypotheses, sharp constant).

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

## 3. Strategy catalog
| Strategy | Recognition cues | Watch for |
|---|---|---|
| Direct | definitions unfold straight to the goal | skipped definitional steps |
| Contrapositive | ¬conclusion is concrete (non-injective gives x≠y with f x = f y) | negating correctly |
| Contradiction | irrationality, infinitude, impossibility, "no such object" | a hidden direct proof; spurious uses |
| Ordinary / strong induction | statement indexed by ℕ; recurrence using one or several earlier cases | base cases for every predecessor used |
| Structural / well-founded | trees, formulas, words; lexicographic or multiset descent | the order really is well-founded |
| Transfinite | ordinals, Zorn-type constructions | separate successor and limit cases |
| Strengthen the hypothesis | induction step fails for lack of information | prove the stronger claim fully |
| Minimal counterexample, descent | "every X has P": take a minimal failure, build a smaller one | minimality w.r.t. a well-order |
| Extremal principle | pick a longest path, largest set, extreme point | existence needs finiteness or compactness |
| Pigeonhole / averaging | more objects than boxes; some term is ≥ the mean | the counting is exact |
| Invariants / monovariants | processes, games, termination, reachability | the quantity is really preserved or monotone |
| Double counting / bijection | binomial identities, incidences, equal cardinalities | bijection well-defined and inverse checked |
| Probabilistic method | existence with a random construction; E[X] < 1 means X = 0 happens | independence assumptions |
| Compactness | local-to-global, limits of approximate solutions | which topology; Arzelà–Ascoli, Banach–Alaoglu, Prokhorov, Tychonoff, König, logic compactness |
| Diagonalization | uncountability, undecidability, a subsequence converging for every index | the diagonal object is in the class |
| Construct vs pure existence | explicit witness vs contradiction or choice | note AC or LEM use when it matters |
| Reduce to a known theorem | the problem is a known result in disguise | verify every hypothesis of the cited version |

Also: generalize (the inventor's paradox), specialize, exploit symmetry (state the symmetry that
justifies WLOG), change variables, pass to an equivalent problem (generating functions, Fourier
transform, linear algebra, duality), or induct on a different parameter.

## 4. Domain tactics
**Analysis.**
- Write the target estimate first, then budget ε (ε/2 + ε/2, or C·ε with C independent of ε). Track
  what each N, δ, C depends on.
- Justify every interchange, naming the theorem each time:
  - lim∫ = ∫lim: dominated convergence (|fₙ| ≤ g ∈ L¹, fₙ → f a.e.); monotone convergence
    (0 ≤ fₙ ↑ f); Vitali (uniform integrability on a finite measure space); uniform convergence on a
    finite measure space.
  - Fatou gives only ∫liminf fₙ ≤ liminf ∫fₙ, and needs fₙ ≥ 0 or bounded below by an integrable
    function.
  - ∑∫ = ∫∑: Tonelli for nonnegative terms; otherwise require ∑∫|fₙ| < ∞.
  - Iterated integrals: Tonelli (measurable, ≥ 0, σ-finite); Fubini (f ∈ L¹ of the product). Keep the
    counterexample ∫∫_{(0,1]²} (x²−y²)/(x²+y²)² in mind.
  - d/dt∫f = ∫∂ₜf: f(·,t) ∈ L¹, ∂ₜf exists, and |∂ₜf(x,t)| ≤ g(x) ∈ L¹ for all t near t₀.
  - Term-wise derivative of a series: derivatives converge uniformly and the series converges at one
    point.
  - Double limits: Moore–Osgood (one of the limits uniform).
  - Rearrangement is safe only for absolutely convergent series (Riemann).
- Toolkit: Cauchy–Schwarz, Hölder, Minkowski, Jensen (convex φ, probability measure), AM–GM, Young,
  Grönwall, Taylor with explicit remainder, mean value theorem, summation by parts, dyadic
  decomposition, Stirling with explicit bounds.
- Asymptotics: state the variable, the range and the uniformity of every O/o/∼/Θ.

**Algebra.**
- Define maps by universal properties (free objects, quotients, tensor products, localizations). A map
  out of a quotient needs a well-definedness check; the universal property packages it.
- Pick the structure that makes the claim a known theorem: group action (orbit–stabilizer, Burnside,
  class equation), modules over a PID, representations (Maschke needs char k ∤ |G|), Galois
  correspondence (finite, separable, normal), Noetherian or Artinian hypotheses.
- Reduce mod p, localize, complete, base-change to an algebraic closure. Know which properties
  descend. Check characteristic 2/3, non-commutativity, zero divisors and infinite generation.

**Combinatorics.**
- Bijective proofs; double counting; generating functions (formal power series, so convergence only
  matters when evaluating); inclusion–exclusion; transfer matrices.
- Hall, Kőnig, Dilworth/Mirsky; Ramsey and Turán bounds; the linear-algebra (dimension) method;
  entropy; the probabilistic method. Check small cases against brute force.

**Probability.**
- Fix the probability space and filtration. Use independence exactly as needed (pairwise vs mutual).
- Concentration:
  - Markov, Chebyshev, Chernoff (MGF).
  - Hoeffding: P(S−ES ≥ t) ≤ exp(−2t²/∑(bᵢ−aᵢ)²).
  - Bernstein, when the variance is small.
  - McDiarmid (bounded differences cᵢ): exp(−2t²/∑cᵢ²).
  - Azuma (martingale differences |Dᵢ| ≤ cᵢ): exp(−t²/(2∑cᵢ²)).
  - For a supremum: a union bound plus an ε-net.
- Coupling: d_TV(μ,ν) = min over couplings of P(X ≠ Y). Monotone couplings; coupling times for mixing.
- Modes of convergence: a.s. ⇒ in probability ⇒ in distribution; uniform integrability upgrades
  convergence in probability to L¹. Second Borel–Cantelli needs independence (or a substitute).
- Optional stopping needs a bounded stopping time, uniform integrability, or bounded increments with
  E[τ] < ∞. A supremum over an uncountable family can be non-measurable; use separability.

**Linear algebra.**
- Stay basis-free until a basis adapted to the problem is chosen (eigenbasis, Jordan, Schur, SVD).
- Workhorses: rank–nullity, Cayley–Hamilton, minimal polynomial, spectral theorem (normal over ℂ,
  symmetric over ℝ), Jordan form (algebraically closed field), Sylvester inertia, Schur complements,
  Woodbury.
- Perturbation:
  - Courant–Fischer min–max.
  - Weyl: |λᵢ(A+E) − λᵢ(A)| ≤ ‖E‖₂ for Hermitian A, E.
  - Davis–Kahan: eigenvector angle ≲ ‖E‖/gap.
  - Gershgorin; Perron–Frobenius (irreducible nonnegative matrices).
- Infinite dimensions: injective ⇏ surjective, spectrum ≠ eigenvalues, closed range, domains of adjoints.

## 5. Repairing a broken proof
1. Find the first unjustified step: test each intermediate claim numerically or symbolically on random
   instances.
2. Classify it: false (a counterexample exists); true but unjustified; or a missing case.
3. For a false lemma, weaken it to what the rest of the argument actually uses and re-check downstream.
   Otherwise switch strategy.
4. If the theorem itself is false, give a counterexample (ideally minimal), then a corrected statement
   (an added hypothesis or a weaker conclusion) with its proof.

## 6. Self-check every step
- [ ] Which hypothesis does this step use? Keep a usage map. A hypothesis unused at the end means a
      stronger theorem or a gap.
- [ ] Quantifier order and dependencies: nothing depends on a variable introduced later.
- [ ] Uniformity: pointwise vs uniform; constants independent of n, x, ε where claimed.
- [ ] Well-definedness: independent of representative, basis, cover, subsequence or choice. Every
      "let x be such that" has a proven x.
- [ ] No division by zero; no log or root of a non-positive number; empty sums and products handled.
- [ ] Measurability and integrability before integrating. No ∞ − ∞. No manipulation of conditionally
      convergent series.
- [ ] Limits shown to exist before being used; interchanges justified (§4).
- [ ] Strict vs non-strict inequalities; the sign when multiplying inequalities; direction of
      inclusions.
- [ ] WLOG backed by an explicit symmetry. No circularity (a lemma using the theorem).
- [ ] Finiteness or compactness wherever an extremal element or pigeonhole is used.
- [ ] Every citation: exact statement, source (book, edition, theorem number, or arXiv ID), and every
      hypothesis verified.
- [ ] Identities and inequalities spot-checked numerically, at random points and at edge cases.

## 7. Refereeing someone else's proof
1. Test the statement on examples first; disproving is cheaper than verifying.
2. Map the structure: lemmas, dependencies, and where each hypothesis enters.
3. Verify each step independently: recompute calculations (sympy) and check each cited theorem's
   hypotheses against the use.
4. Classify issues with a location (section, equation, line):
   - fatal: the claim is false, or the argument cannot be fixed;
   - gap: true but unjustified (give the fix if you have one);
   - minor: missing detail, notation, typo.
5. Verdict: correct / correct with fixable gaps / incorrect. The `review-protocol` skill has the
   independence rules and severity rubric.

## 8. Writing
- Start with the precise statement, all hypotheses included. Fix notation before use: one symbol, one
  meaning. Define every object once.
- Structure: lemmas with standalone statements, then a main proof that reads as an outline. Move long
  computations into lemmas or an appendix.
- "Clearly" and "it is easy to see" only for steps a competent reader can verify in under a minute
  with no new idea. Otherwise give the one-line reason.
- Say where each hypothesis is used. Add a sharpness remark (an example showing a hypothesis cannot be
  dropped). Cite precisely.
- LaTeX: `$…$`, `$$…$$` or `align`, `\label`/`\eqref`. The `technical-writing` skill covers
  mathematical exposition.

## 9. When to formalize or mechanize
Formalize a load-bearing lemma in Lean (`lean-formalization`) when the argument is delicate:
- heavy case analysis;
- off-by-one or index bookkeeping;
- long chains of inequalities;
- combinatorial identities;
- a computer-assisted step.

At minimum, check finite parts exhaustively in Python or with z3, and say so.

## Verify
- Small cases and random instances agree with every intermediate claim, not only the final one.
- Every hypothesis is used (or its redundancy is explained), and every degenerate case is handled.
- Each cited theorem is quoted with its source and its hypotheses checked.
- Critical results: an independent re-derivation (a different method or a fresh pass that does not look
  at the first proof), or a Lean check.

## Report
```
Claim:   <precise statement, all hypotheses>        Status: PROVED | DISPROVED | PARTIAL | OPEN
Result:  <proof, or counterexample with verification>
Checks:  <small cases / ranges tested, CAS identities, z3 or exhaustive checks, edge cases>
Hypothesis usage: <hypothesis → step>
Gaps:    <exact step, why unjustified, suggested fix, confidence>   (none, if none)
```
