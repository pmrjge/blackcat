import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 5 * (13 * n + 5) - 13 * (5 * n + 2) = 1) := by
  intro h
  have := h 0
  norm_num at this
