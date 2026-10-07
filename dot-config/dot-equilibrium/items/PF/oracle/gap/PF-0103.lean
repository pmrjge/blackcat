import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 + 3 * x ^ 2 - 16 * x + 12 = (x - 1) * (x ^ 2 - 4 * x - 12)) := by
  intro h
  have := h 2
  norm_num at this
