# Monoidal and 2-categorical structure, string diagrams, sheaves

Part of `category-theory`.

## 6. Monoidal, enriched, 2-categorical
- Monoidal category (C, ⊗, I, α, λ, ρ) with the pentagon and triangle axioms.
  - Mac Lane coherence: every diagram of structural isomorphisms commutes, so compute as if strict.
  - Braided (hexagons), symmetric (β² = 1), closed (− ⊗ A ⊣ [A, −]), cartesian (⊗ = ×).
  - Monoidal functors can be lax, strong or strict. Monoids in (Ab, ⊗_ℤ) are rings; monoids in
    (End C, ∘) are monads.
  - Duals: cup/cap maps with snake equations give compact closed categories (FinVect, Rel) and a
    categorical trace.
- Enrichment over a monoidal V puts hom-objects C(X, Y) in V: Ab-enriched = preadditive;
  {0 ≤ 1}-enriched = preorders; ([0,∞], ≥, +)-enriched = Lawvere metric spaces; Cat-enriched = strict
  2-categories. Limits generalize to weighted limits, and Yoneda to enriched Yoneda.
- 2-categories: 0-, 1- and 2-cells; vertical (·) and horizontal (∗) composition; whiskering.
  - Interchange law: (δ·γ) ∗ (β·α) = (δ∗β)·(γ∗α).
  - Bicategories (Span, Prof, Bimod) hold associativity only up to coherent isomorphism.
  - Adjunctions, monads and equivalences make sense inside any 2-category; Cat is the model case.

## 7. String diagrams
- Monoidal categories: wires are objects, boxes are morphisms, the vertical axis is composition (state
  the reading direction), the horizontal axis is ⊗, and I is the empty wire. Diagrams equal up to planar
  isotopy denote equal morphisms (Joyal–Street). In the symmetric case crossings pass through each
  other; in the braided case over/under matters.
- 2-categories such as Cat: regions are categories, wires are functors, nodes are natural
  transformations. Naturality means sliding nodes past each other; the triangle identities are
  "zig-zag = straight" with η as a cup and ε as a cap.
- References: Selinger, "A survey of graphical languages for monoidal categories", arXiv:0908.3347;
  Piedeleu–Zanasi, "An Introduction to String Diagrams for Computer Scientists", arXiv:2305.08768.

## 8. Sheaves and toposes (pointers)
- A site is (C, J) with J a Grothendieck topology given by covering sieves.
- F is a sheaf iff F(U) → ∏F(Uᵢ) ⇉ ∏F(Uᵢ ×_U Uⱼ) is an equalizer for every cover. Sheafification is a
  left exact left adjoint to the inclusion.
- A Grothendieck topos is some Sh(C, J). An elementary topos has finite limits, is cartesian closed,
  and has a subobject classifier Ω; its internal logic is intuitionistic higher-order. Geometric
  morphisms are adjunctions f^* ⊣ f_* with f^* left exact.
- Reading: Mac Lane–Moerdijk, *Sheaves in Geometry and Logic*; Johnstone, *Sketches of an Elephant*.
- Foundations: Leinster, *Basic Category Theory* (arXiv:1612.09375); Riehl, *Category Theory in
  Context* (free PDF from the author); Mac Lane, *Categories for the Working Mathematician*; Loregian,
  "Coend calculus" (arXiv:1501.02503).
