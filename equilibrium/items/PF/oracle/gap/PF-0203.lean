import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℚ, x / (1 + 1 * x) = x - 1 * x ^ 2) := by
  intro h
  have := h 1
  norm_num at this
