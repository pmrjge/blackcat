import Mathlib

theorem pf_0142 : ∃ x y : ℕ, x ^ 2 = 21 * y ^ 2 + 1 ∧ 336 < y := by
  exact ⟨6049, 1320, by norm_num, by norm_num⟩
