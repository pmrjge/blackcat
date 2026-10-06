import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 6 * x ^ 2 + 11 * x - 6 = (x - 1) * (x ^ 2 + 5 * x + 6)) := by
  intro h
  have := h 2
  norm_num at this
