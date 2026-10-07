import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 + x ^ 2 - 26 * x + 24 = (x - 4) * (x ^ 2 - 5 * x - 6)) := by
  intro h
  have := h 1
  norm_num at this
