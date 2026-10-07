import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, 0 < x → 2 * 1 * x - 54 / x ^ 2 = 0 → x ^ 3 = 54 / 1) := by
  intro h
  have := h 3 (by norm_num) (by norm_num)
  norm_num at this
