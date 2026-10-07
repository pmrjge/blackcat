import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 5 * x ^ 2 + 2 * x + 8 = (x - (-1)) * (x ^ 2 + 6 * x + 8)) := by
  intro h
  have := h 1
  norm_num at this
