import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, 0 < x → 2 * 2 * x - 4 / x ^ 2 = 0 → x ^ 3 = 4 / 2) := by
  intro h
  have := h 1 (by norm_num) (by norm_num)
  norm_num at this
