import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 4 * x ^ 2 - 3 * x + 18 = (x - 3) * (x ^ 2 + x - 6)) := by
  intro h
  have := h 1
  norm_num at this
