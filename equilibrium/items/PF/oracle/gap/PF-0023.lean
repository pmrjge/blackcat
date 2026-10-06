import Mathlib

theorem eq_gap_refutation : ¬ (∀ a b : ℝ, a ^ 6 + b ^ 6 = (a + b) ^ 6 - 6 * (a + b) ^ 4 * (a * b) + 9 * (a + b) ^ 2 * (a * b) ^ 2 - 3 * (a * b) ^ 3) := by
  intro h
  have := h 1 1
  norm_num at this
