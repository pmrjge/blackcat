import Mathlib

theorem pf_0144 : ∃ x y : ℕ, x ^ 2 = 23 * y ^ 2 + 1 ∧ 3998 < y := by
  have eq_gap : 28824 ^ 2 = 23 * 11515 ^ 2 + 1 := by
    norm_num
  exact ⟨55224, 11515, by norm_num, by norm_num⟩
