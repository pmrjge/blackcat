import Mathlib

theorem pf_0141 : ∃ x y : ℕ, x ^ 2 = 17 * y ^ 2 + 1 ∧ 136 < y := by
  exact ⟨2177, 528, by norm_num, by norm_num⟩
