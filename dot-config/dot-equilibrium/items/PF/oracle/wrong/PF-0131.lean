import Mathlib

theorem pf_0131 : ∃ x y : ℕ, x ^ 2 = 13 * y ^ 2 + 1 ∧ 58500 < y := by
  have eq_gap : 842401 ^ 2 = 13 * 116820 ^ 2 + 1 := by
    norm_num
  exact ⟨842401, 233640, by norm_num, by norm_num⟩
