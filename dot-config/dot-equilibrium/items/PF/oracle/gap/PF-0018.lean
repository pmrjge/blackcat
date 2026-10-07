import Mathlib

theorem eq_gap_refutation : ¬ (∀ a b : ℝ, a ^ 4 + b ^ 4 = (a + b) ^ 4 - 4 * (a + b) ^ 2 * (a * b) + 3 * (a * b) ^ 2) := by
  intro h
  have := h 1 1
  norm_num at this
