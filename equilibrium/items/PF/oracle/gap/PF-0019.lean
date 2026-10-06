import Mathlib

theorem eq_gap_refutation : ¬ (∀ a b : ℝ, a ^ 5 + b ^ 5 = (a + b) ^ 5 - 5 * (a + b) ^ 3 * (a * b) + 6 * (a + b) * (a * b) ^ 2) := by
  intro h
  have := h 1 1
  norm_num at this
