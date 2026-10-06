import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 6 * x ^ 2 - x + 30 = (x - 5) * (x ^ 2 + x - 6)) := by
  intro h
  have := h 1
  norm_num at this
