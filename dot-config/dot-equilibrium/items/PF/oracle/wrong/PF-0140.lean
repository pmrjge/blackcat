import Mathlib

theorem pf_0140 : ∃ x y : ℕ, x ^ 2 = 12 * y ^ 2 + 1 ∧ 148 < y := by
  have eq_gap : 735 ^ 2 = 12 * 390 ^ 2 + 1 := by
    norm_num
  exact ⟨1351, 390, by norm_num, by norm_num⟩
