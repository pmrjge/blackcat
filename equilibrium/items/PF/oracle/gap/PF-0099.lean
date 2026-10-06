import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 2 * x ^ 2 - 7 * x - 4 = (x - (-1)) * (x ^ 2 + 3 * x - 4)) := by
  intro h
  have := h 1
  norm_num at this
