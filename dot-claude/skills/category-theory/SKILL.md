---
name: category-theory
description: Use for categorical constructions and proofs — limits, adjoints, Yoneda, monads, monoidal categories.
---
# Category theory in practice

## Scope
- Covers: verifying categorical structure; universal constructions; adjunctions, Yoneda arguments and
  monads; monoidal, enriched and 2-categorical notions at working depth; string diagrams; pointers to
  sheaves and toposes; applied category theory; drawing diagrams.
- Elsewhere: general proof technique in `proof-craft`; Mathlib notation, names and files in
  `lean-formalization` (§8 there).

## 1. Working method
1. Data: objects; hom-sets; identities; composition, with its order stated. Write g∘f (f first) or
   the diagrammatic f ≫ g (also f first) and never mix the two.
2. Axioms: associativity and unit laws. For a constructed category (slice, comma, functor category,
   Kleisli, category of elements), check that composition is well-defined and lands in the right
   hom-set.
3. Size: small, locally small, or large? Needed before invoking Yoneda, functor categories or adjoint
   functor theorems.
4. Functoriality: F(1) = 1 and F(g∘f) = F(g)∘F(f). A contravariant functor is a functor Cᵒᵖ → D. For a
   bifunctor, check each variable separately plus the interchange.
5. Naturality: G(f)∘α_X = α_Y∘F(f) for every f: X → Y. Check it on a non-identity morphism, ideally an
   automorphism. A component that depends on a choice (basis, representative, splitting) is almost
   never natural.
6. Sameness: F is an equivalence iff it is fully faithful and essentially surjective (building the
   inverse uses choice). Equivalence, not isomorphism, is the right notion for categories.
7. State universal properties as natural bijections, e.g. C(X, lim D) ≅ Cone(X, D) naturally in X.
   Uniqueness up to unique isomorphism then comes for free (Yoneda).

## 2. Limits and colimits in standard categories
Read `references/constructions.md` when computing limits, colimits, adjunctions or monads in standard categories.

## 3. Adjunctions
Read `references/constructions.md` when computing limits, colimits, adjunctions or monads in standard categories.

## 4. Yoneda
- Statement: Nat(C(−, A), F) ≅ F(A), naturally in A and F, via α ↦ α_A(1_A). Hence y: C → [Cᵒᵖ, Set]
  is fully faithful, and C(−, A) ≅ C(−, B) naturally implies A ≅ B.
- Uses:
  1. Prove A ≅ B by natural bijections C(T, A) ≅ C(T, B), or dually C(A, T) ≅ C(B, T). Examples:
     (A×B)×C ≅ A×(B×C) (first form); A×(B+C) ≅ A×B + A×C in a cartesian closed category (dual form,
     via (−)^A).
  2. Define objects by what they represent: products, exponentials, classifying objects, free objects.
  3. Maps between representables are exactly morphisms, so structure maps are forced.
  4. Check equations on generalized elements T → A for all T.
  5. Reduce presheaf statements to representables by density.
- Enriched and bicategorical versions exist (Kelly, *Basic Concepts of Enriched Category Theory*;
  Johnson–Yau, *2-Dimensional Categories*, arXiv:2002.06055).

## 5. Monads and comonads
Read `references/constructions.md` when computing limits, colimits, adjunctions or monads in standard categories.

## 6–8. Monoidal, enriched and 2-categorical structure; string diagrams; sheaves and toposes
Read `references/monoidal-strings-sheaves.md` for monoidal categories and coherence, braided/symmetric/closed structure, string-diagram conventions, sites, sheaves and toposes.

## 9. Applied category theory
Read `references/applied.md` when working on applied category theory.

## 10. Tools
Read `references/tools.md` when using a proof assistant, library or diagram tool for category theory.

## 11. Pitfalls
- Size:
  - Set, Grp and Top are large.
  - [C, D] is locally small when C is small and D locally small; otherwise Nat(F, G) can be a proper
    class.
  - A small category with all small limits is a preorder (Freyd).
  - State universe levels when formalizing.
- Variance: C(−, A) is contravariant and C(A, −) covariant. Powerset is covariant (direct image) or
  contravariant (preimage). Naturality squares for contravariant functors run backwards.
- Duality: dualize theorems about all categories freely, but never statements about a specific
  category. Setᵒᵖ is not Set; coproducts in Grp are free products.
- Isomorphism vs equality: universal objects are unique up to unique isomorphism, so write ≅, not =.
  Prefer statements invariant under equivalence.
- "Canonical" is not natural:
  - V ≅ V* needs a basis, and there is no natural isomorphism (the variances even differ);
    V → V** is natural.
  - Splittings of short exact sequences of vector spaces, and of universal coefficient sequences, exist
    but are not natural.
- Epi ≠ surjective and mono ≠ injective in general:
  - ℤ → ℚ is epi in Ring; dense maps are epi in Haus.
  - ℚ → ℚ/ℤ is mono in divisible abelian groups.
  - In Set, Grp, Ab and Top, epis are surjective and monos injective.
- Preserving limits ≠ creating or reflecting them: U: Top → Set preserves all limits and colimits but
  does not reflect isomorphisms (continuous bijections).
- Composition order when translating between ∘ and ≫. Limits are used only after their existence is
  established.

## Verify
- Test every construction on small examples:
  - posets (functors are monotone maps, adjunctions are Galois connections, limits are meets);
  - monoids as one-object categories (natural transformations are conjugating elements);
  - finite sets; the walking arrow • → •; the parallel pair • ⇉ •.
- Compute in Set first, then transport.
- For each claimed adjunction, check both triangle identities or the natural bijection on generators,
  and check that the claimed left adjoint preserves the initial object and coproducts.
- For each naturality claim, test an automorphism: the swap on V ⊕ V, a basis change, a group
  automorphism.
- Long diagram chases: have another pass redo them independently, or formalize the key lemma in Mathlib.

## Deliverables
- Precise definitions (objects, morphisms, composition) of every category and functor used;
  statements via universal properties, with proofs; tikz-cd source that compiles.
- The checks performed, the (counter)examples found, and references with verified identifiers (arXiv
  ID, or book with chapter and theorem).
