import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 4 * (10 * n + 2) - 10 * (4 * n + 1) = 1) := by
  intro h
  have := h 0
  norm_num at this
