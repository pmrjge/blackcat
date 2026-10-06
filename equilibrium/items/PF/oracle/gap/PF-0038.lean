import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 12 * (18 * n + 2) - 18 * (12 * n + 1) = 1) := by
  intro h
  have := h 0
  norm_num at this
