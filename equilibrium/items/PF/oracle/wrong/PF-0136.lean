import Mathlib

theorem pf_0136 : ∃ x y : ℕ, x ^ 2 = 19 * y ^ 2 + 1 ∧ 3334 < y := by
  have eq_gap : 57799 ^ 2 = 19 * 6630 ^ 2 + 1 := by
    norm_num
  exact ⟨57799, 13260, by norm_num, by norm_num⟩
