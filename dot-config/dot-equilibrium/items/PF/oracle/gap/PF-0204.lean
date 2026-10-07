import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℚ, x / (1 + 2 * x) = x - 2 * x ^ 2) := by
  intro h
  have := h 1
  norm_num at this
