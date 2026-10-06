import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 4 * (11 * n + 8) - 11 * (4 * n + 3) = 1) := by
  intro h
  have := h 0
  norm_num at this
