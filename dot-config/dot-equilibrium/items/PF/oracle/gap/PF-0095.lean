import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 19 * x - 30 = (x - (-2)) * (x ^ 2 + 2 * x - 15)) := by
  intro h
  have := h 1
  norm_num at this
