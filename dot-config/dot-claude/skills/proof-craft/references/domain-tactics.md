# proof-craft — domain tactics (reference)
Read when the proof lives in a specific field and needs its standard tactics. Parent: `proof-craft` SKILL.md.

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
