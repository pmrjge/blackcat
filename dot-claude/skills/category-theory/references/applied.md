# Category theory in practice: applied

Read when working on applied category theory (moved from `category-theory` SKILL.md).

## 9. Applied category theory
All arXiv IDs below were checked against arxiv.org (Sept 2026).
- Surveys: Fong–Spivak, *Seven Sketches in Compositionality* (1803.05316); Baez–Stay, "Physics,
  Topology, Logic and Computation: A Rosetta Stone" (0903.0340).
- Lenses and optics:
  - A lens is get: S → A with put: S × B → T. The lawful case has get-put, put-get and put-put.
  - Optics are ∫^M C(S, M⊗A) × D(M⊗B, T).
  - Pickering–Gibbons–Wu (1703.10857); Riley, "Categories of Optics" (1809.00738); Clarke et al.,
    "Profunctor Optics, a Categorical Update" (2001.07488).
- Learning:
  - Fong–Spivak–Tuyéras, "Backprop as Functor" (1711.10455); Fong–Johnson, "Lenses and Learners"
    (1903.03671).
  - Cruttwell–Gavranović–Ghani–Wilson–Zanasi, "Categorical Foundations of Gradient-Based Learning"
    (2103.01931; Para, reverse-derivative categories, lenses), and "Deep Learning with Parametric
    Lenses" (2404.00408).
- Categorical deep learning:
  - Gavranović et al., "Position: Categorical Deep Learning is an Algebraic Theory of All
    Architectures" (2402.15332; architectures as monad algebras, equivariance as algebra
    homomorphisms, 2-categorical framing). This is a position paper.
  - Gavranović's thesis (2403.13001); Dudzik–Veličković, "Graph Neural Networks are Dynamic
    Programmers" (2203.15544); background in Bronstein et al., "Geometric Deep Learning" (2104.13478).
- Games and cybernetics: Ghani–Hedges–Winschel–Zahn, "Compositional game theory" (1603.04641);
  Capucci–Gavranović–Hedges–Rischel, "Towards Foundations of Categorical Cybernetics" (2105.06332).
- Operads and interaction: Spivak, "The operad of wiring diagrams" (1305.0297); Leinster, *Higher
  Operads, Higher Categories* (math/0305049); Niu–Spivak, *Polynomial Functors* (2312.00990).
- Data:
  - Spivak, "Functorial Data Migration" (1009.1166): schemas are categories, instances are functors,
    and a schema map F gives Σ_F ⊣ Δ_F ⊣ Π_F.
  - Schultz–Spivak–Vasilakopoulou–Wisnesky, "Algebraic Databases" (1602.03501).
  - Patterson–Lynch–Fairbanks, "Categorical Data Structures for Technical Computing" (2106.04703;
    C-sets, Catlab.jl).
- Open systems: Fong, "Decorated Cospans" (1502.00872); Fong–Spivak, "Hypergraph Categories"
  (1806.08304).
- Guardrail: say what the categorical framing buys (a theorem, a construction, a compositionality
  guarantee, code reuse) and what it merely relabels. Flag position papers and conjectural claims as
  such.
