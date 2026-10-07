import Mathlib

theorem eq_gap_refutation : ¬ (∀ a b : ℝ, a ^ 7 + b ^ 7 = (a + b) ^ 7 - 7 * (a + b) ^ 5 * (a * b) + 14 * (a + b) ^ 3 * (a * b) ^ 2 - 8 * (a + b) * (a * b) ^ 3) := by
  intro h
  have := h 1 1
  norm_num at this
