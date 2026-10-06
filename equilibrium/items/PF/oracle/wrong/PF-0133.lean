import Mathlib

theorem pf_0133 : ∃ x y : ℕ, x ^ 2 = 11 * y ^ 2 + 1 ∧ 16 < y := by
  have eq_gap : 199 ^ 2 = 11 * 30 ^ 2 + 1 := by
    norm_num
  exact ⟨199, 60, by norm_num, by norm_num⟩
