import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, 0 < x → 2 * 3 * x - 48 / x ^ 2 = 0 → x ^ 3 = 48 / 3) := by
  intro h
  have := h 2 (by norm_num) (by norm_num)
  norm_num at this
