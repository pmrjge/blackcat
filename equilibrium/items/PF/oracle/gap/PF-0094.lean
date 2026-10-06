import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 + 2 * x ^ 2 - 11 * x - 12 = (x - 3) * (x ^ 2 - 5 * x + 4)) := by
  intro h
  have := h 1
  norm_num at this
