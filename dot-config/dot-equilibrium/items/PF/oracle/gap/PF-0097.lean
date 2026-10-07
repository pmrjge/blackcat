import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 5 * x ^ 2 + 7 * x - 3 = (x - 1) * (x ^ 2 + 4 * x + 3)) := by
  intro h
  have := h 2
  norm_num at this
