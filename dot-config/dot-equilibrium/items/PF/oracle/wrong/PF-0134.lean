import Mathlib

theorem pf_0134 : ∃ x y : ℕ, x ^ 2 = 6 * y ^ 2 + 1 ∧ 79 < y := by
  have eq_gap : 285 ^ 2 = 6 * 198 ^ 2 + 1 := by
    norm_num
  exact ⟨485, 198, by norm_num, by norm_num⟩
