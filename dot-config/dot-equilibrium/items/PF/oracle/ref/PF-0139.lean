import Mathlib

theorem pf_0139 : ∃ x y : ℕ, x ^ 2 = 22 * y ^ 2 + 1 ∧ 4158 < y := by
  exact ⟨77617, 16548, by norm_num, by norm_num⟩
