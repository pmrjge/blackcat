import Mathlib

theorem eq_gap_refutation : ¬ (∀ a b : ℝ, a ^ 3 + b ^ 3 = (a + b) ^ 3 - 4 * (a + b) * (a * b)) := by
  intro h
  have := h 1 1
  norm_num at this
