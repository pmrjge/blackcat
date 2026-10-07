import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 8 * (12 * n + 2) - 12 * (8 * n + 1) = 1) := by
  intro h
  have := h 0
  norm_num at this
