import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 5 * (8 * n + 3) - 8 * (5 * n + 2) = 1) := by
  intro h
  have := h 0
  norm_num at this
