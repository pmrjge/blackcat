import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 14 * (21 * n + 2) - 21 * (14 * n + 1) = 1) := by
  intro h
  have := h 0
  norm_num at this
