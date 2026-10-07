import Mathlib

theorem pf_0137 : ∃ x y : ℕ, x ^ 2 = 10 * y ^ 2 + 1 ∧ 3038 < y := by
  have eq_gap : 15067 ^ 2 = 10 * 8658 ^ 2 + 1 := by
    norm_num
  exact ⟨27379, 8658, by norm_num, by norm_num⟩
