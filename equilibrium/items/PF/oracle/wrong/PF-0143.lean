import Mathlib

theorem pf_0143 : ∃ x y : ℕ, x ^ 2 = 5 * y ^ 2 + 1 ∧ 478 < y := by
  have eq_gap : 1737 ^ 2 = 5 * 1292 ^ 2 + 1 := by
    norm_num
  exact ⟨2889, 1292, by norm_num, by norm_num⟩
