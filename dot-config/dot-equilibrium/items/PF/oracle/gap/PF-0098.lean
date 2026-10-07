import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 3 - 3 * x ^ 2 + 4 = (x - 2) * (x ^ 2 + x - 2)) := by
  intro h
  have := h 1
  norm_num at this
