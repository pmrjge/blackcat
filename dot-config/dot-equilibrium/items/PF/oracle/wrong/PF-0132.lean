import Mathlib

theorem pf_0132 : ∃ x y : ℕ, x ^ 2 = 7 * y ^ 2 + 1 ∧ 287 < y := by
  have eq_gap : 1160 ^ 2 = 7 * 765 ^ 2 + 1 := by
    norm_num
  exact ⟨2024, 765, by norm_num, by norm_num⟩
