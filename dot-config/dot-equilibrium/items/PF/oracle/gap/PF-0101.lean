import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 4 * x ^ 2 - 20 * x + 48 = (x - (-4)) * (x ^ 2 + 8 * x + 12)) := by
  intro h
  have := h 1
  norm_num at this
