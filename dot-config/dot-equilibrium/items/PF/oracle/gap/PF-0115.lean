import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, 0 < x → 2 * 1 * x - 2 / x ^ 2 = 0 → x ^ 3 = 2 / 1) := by
  intro h
  have := h 1 (by norm_num) (by norm_num)
  norm_num at this
