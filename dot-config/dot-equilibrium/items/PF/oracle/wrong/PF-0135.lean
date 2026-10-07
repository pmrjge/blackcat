import Mathlib

theorem pf_0135 : ∃ x y : ℕ, x ^ 2 = 14 * y ^ 2 + 1 ∧ 32 < y := by
  have eq_gap : 449 ^ 2 = 14 * 60 ^ 2 + 1 := by
    norm_num
  exact ⟨449, 120, by norm_num, by norm_num⟩
