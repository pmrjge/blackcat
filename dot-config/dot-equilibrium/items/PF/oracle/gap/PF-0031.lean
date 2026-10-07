import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 6 * (9 * n + 2) - 9 * (6 * n + 1) = 1) := by
  intro h
  have := h 0
  norm_num at this
