import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 15 * (25 * n + 2) - 25 * (15 * n + 1) = 1) := by
  intro h
  have := h 0
  norm_num at this
