# Lean formalization: common errors and fixes

| Message | Usual cause | Fix |
|---|---|---|
| `failed to synthesize <Class>` | missing import or instance; wrong type (ℕ vs ℝ); needs `[Fact p.Prime]` | `#synth`; `set_option trace.Meta.synthInstance true in`; add the import or assumption |
| type mismatch with `↑` | cast in the wrong place: `((a - b : ℕ) : ℝ)` ≠ `(a : ℝ) - b` | annotate `(2 : ℝ)`, `(n : ℝ)`; `push_cast [h]` |
| numeral elaborated in ℕ | a numeral with no expected type defaults to ℕ | type ascription on the first occurrence: `(2 : ℝ)` |
| `motive is not type correct` (`rw`) | the rewritten term appears in a dependent type, e.g. `x : Fin n` when rewriting `n` | `subst h` / `cases h` (variable = term), `simp only [h]`, `conv`, `nth_rw` |
| `(deterministic) timeout … maxHeartbeats` | default 200000 exceeded: large `simp` sets, `decide`, typeclass loops | first make the proof cheaper (`simp only`, split lemmas); then `set_option maxHeartbeats 400000 in` before the declaration |
| `maximum recursion depth` | huge terms or numerals under `decide`/`rfl` | `norm_num`, restructure, `set_option maxRecDepth N in` |
| universe errors | `Type u` vs `Type*` mismatch; category `Category.{v, u}` | make universes explicit; `ULift`; match `HasLimitsOfSize.{w, w}` |
| `unknown identifier` / `unknown constant` | renamed lemma or missing import | `lean_local_search`, `#check`, deprecation messages |
| `Ambiguous term` | e.g. `Monad` under `open CategoryTheory` | qualify: `CategoryTheory.Monad` |
| `linarith failed`, `simp made no progress` | goal not in normal form; missing fact | `push_cast`, `ring_nf at *`, supply the product or lemma explicitly |
