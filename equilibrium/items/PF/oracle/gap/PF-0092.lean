import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 7 * x + 6 = (x - (-3)) * (x ^ 2 + 3 * x + 2)) := by
  intro h
  have := h 1
  norm_num at this
