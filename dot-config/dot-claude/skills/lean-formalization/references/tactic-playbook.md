# Lean formalization: tactic playbook by goal shape

| Goal | First try | Notes |
|---|---|---|
| ring identity | `ring`; `ring_nf` to normalize | treats x⁻¹ as an atom: if cancellation needs x ≠ 0, `field_simp` first |
| consequence of equations | `linear_combination (a+b) * h₁ - 2 * h₂`; `grobner` | `grobner` finds the combination itself |
| field identity with `/` | `field_simp` then `ring` | needs `x ≠ 0` facts in context |
| linear (in)equality | `linarith`, `linarith [sq_nonneg (a-b)]` | ordered fields, ℤ; hypotheses must be linear |
| nonlinear inequality | `nlinarith [sq_nonneg (a-b), mul_pos ha hb]` | supply the products it needs |
| `0 < e`, `0 ≤ e`, `e ≠ 0` | `positivity` | syntactic; fails on differences |
| monotone bound | `gcongr` (`f a ≤ f b` from `a ≤ b`), `bound` | side goals go to `positivity` |
| order facts | `order` | uses only order hypotheses |
| ℕ/ℤ arithmetic incl. `-`, `/`, `%` by constants | `omega` | linear only; no casts to ℝ |
| numerals, `Nat.Prime 97` | `norm_num`, `norm_num [f]` | `decide` for small decidable props |
| heavy decidable computation | `decide +kernel` | `native_decide` adds an axiom (§10) |
| casts ℕ→ℤ→ℚ→ℝ | `push_cast`, `norm_cast`, `exact_mod_cast h` | `zify [h]`, `qify`, `rify`, `lift x to ℕ using hx` |
| groups, modules | `abel`, `group`, `module`, `noncomm_ring` | |
| propositional / first-order glue | `tauto`, `aesop`, `simp_all`, `grind` | `grind`: congruence closure plus arithmetic, in core |
| continuity, measurability, differentiability | `fun_prop`; `continuity`, `measurability` | try `fun_prop` first; the other two are aesop-based and slower |
| rewriting | `rw [h, ← h']`, `nth_rw 2 [h]`, `rwa`, `conv_lhs => rw [h]`, `simp only [h] at h' ⊢`, `simpa using h` | non-terminal bare `simp` is fragile |
| ∧, ∃, ↔, extensionality | `constructor`, `refine ⟨?_, ?_⟩`, `use x`, `ext x`, `funext x`, `congr 1`, `congr!` | `convert h using 2` leaves the differences as goals |
| unpack hypotheses | `obtain ⟨x, hx, rfl⟩ := h`, `rintro ⟨-, hq⟩`, `choose f hf using h` | `set y := e with hy`, `generalize`, `subst`, `apply_fun f at h` |
| negation, contradiction | `by_contra h`, `by_contra! h`, `push Not at h ⊢`, `contrapose! h`, `exfalso` | |
| case analysis | `rcases` (below), `interval_cases x`, `fin_cases x`, `split_ifs with h`, `wlog h : x ≤ y generalizing x y` | |
| induction | structured `induction … with` (below) | |
| filters, eventually | `filter_upwards [h₁, h₂] with x hx₁ hx₂` | |
| sanity-test a statement | `plausible` | random testing; proves nothing and leaves a `sorry` |

Syntax for the rows marked "below" (all checked against Mathlib v4.34.1):
```lean
rcases h with h₁ | h₂                                         -- disjunction
induction n with
  | zero => simp
  | succ k ih => rw [Finset.sum_range_succ, mul_add, ih]; ring
induction n using Nat.strong_induction_on with
  | _ n ih => exact step n ih                                 -- ih : ∀ m < n, P m
induction n, hn using Nat.le_induction with                   -- hn : m ≤ n
  | base => norm_num
  | succ k hk ih => nlinarith
```
