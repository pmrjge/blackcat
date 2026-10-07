import Mathlib

theorem pf_0138 : ∃ x y : ℕ, x ^ 2 = 15 * y ^ 2 + 1 ∧ 26 < y := by
  have eq_gap : 132 ^ 2 = 15 * 63 ^ 2 + 1 := by
    norm_num
  exact ⟨244, 63, by norm_num, by norm_num⟩
