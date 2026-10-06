import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 3 * (7 * n + 2) - 7 * (3 * n + 1) = 1) := by
  intro h
  have := h 0
  norm_num at this
