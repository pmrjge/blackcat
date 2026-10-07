import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℚ, x / (1 + 3 * x) = x - 3 * x ^ 2) := by
  intro h
  have := h 1
  norm_num at this
