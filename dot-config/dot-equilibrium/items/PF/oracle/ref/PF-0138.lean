import Mathlib

theorem pf_0138 : ∃ x y : ℕ, x ^ 2 = 15 * y ^ 2 + 1 ∧ 26 < y := by
  exact ⟨244, 63, by norm_num, by norm_num⟩
