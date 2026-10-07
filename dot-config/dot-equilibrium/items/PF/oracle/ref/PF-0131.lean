import Mathlib

theorem pf_0131 : ∃ x y : ℕ, x ^ 2 = 13 * y ^ 2 + 1 ∧ 58500 < y := by
  exact ⟨842401, 233640, by norm_num, by norm_num⟩
