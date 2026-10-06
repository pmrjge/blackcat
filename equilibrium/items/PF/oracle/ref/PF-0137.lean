import Mathlib

theorem pf_0137 : ∃ x y : ℕ, x ^ 2 = 10 * y ^ 2 + 1 ∧ 3038 < y := by
  exact ⟨27379, 8658, by norm_num, by norm_num⟩
