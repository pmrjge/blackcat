# Lean formalization: category theory in Mathlib

- Location and names:
  - `open CategoryTheory`; sources under `Mathlib/CategoryTheory/`.
  - Concrete categories: `GrpCat`, `AddCommGrpCat`, `CommGrpCat`, `MonCat`, `RingCat`, `CommRingCat`,
    `ModuleCat R` (in `Mathlib/Algebra/Category/`); `TopCat`; `Cat`.
  - `Type u` is a category whose morphisms are functions.
- Scoped notation:
  - Morphisms: `X ⟶ Y`; composition `f ≫ g` in diagrammatic order (first `f`); `𝟙 X`.
  - Functors: `C ⥤ D`; composition `F ⋙ G` (first `F`); identity `𝟭 C`; opposite `Cᵒᵖ`.
  - Natural transformations: `α : F ⟶ G`, with `α.app X` and `α.naturality f`.
  - Isomorphisms: `X ≅ Y`, with `e.hom`, `e.inv`, `e.hom_inv_id`.
  - Adjunctions: `F ⊣ G`, with `adj.unit`, `adj.counit`, `adj.homEquiv X Y`,
    `adj.left_triangle_components`.
- Yoneda: `yoneda : C ⥤ Cᵒᵖ ⥤ Type v`, `yonedaEquiv`, `Yoneda.fullyFaithful`.
- Limits (`open CategoryTheory.Limits`):
  - `limit F`, `HasLimit F`, `IsLimit c`, `pullback f g`.
  - `Adjunction.rightAdjoint_preservesLimits`, `Adjunction.leftAdjoint_preservesColimits`.
  - Adjoint functor theorems in `Adjunction/AdjointFunctorTheorems.lean`.
- Monads: `CategoryTheory.Monad`, `Monad.Algebra`, `Kleisli`, `Adjunction.toMonad`
  (`Monad/Adjunction.lean`).
- Monoidal (`open MonoidalCategory`): `X ⊗ Y`, `f ⊗ₘ g`, whiskering `X ◁ f` and `f ▷ Y`, `𝟙_ C`,
  `α_ X Y Z`, `λ_ X`, `ρ_ X`.
- Automation: `simp` with `@[reassoc]` lemmas, `ext`, `aesop_cat`. `cat_disch` discharges category
  auto-params. `erw` is occasionally needed across defeq-but-not-syntactic forms.
- Universes: `Category.{v, u} C` has objects in `Type u` and homs in `Type v`; `SmallCategory` and
  `LargeCategory` are the two standard cases.
