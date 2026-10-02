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
- [ ] Limits shown to exist before being used; interchanges justified (§4 in `references/domain-tactics.md`).
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

## References
- `references/experiments.md` — read when testing a conjecture numerically or symbolically before proving it.
- `references/domain-tactics.md` — read when the proof lives in a specific field and needs its standard tactics.

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
