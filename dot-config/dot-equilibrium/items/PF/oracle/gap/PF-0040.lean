import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 10 * (16 * n + 3) - 16 * (10 * n + 2) = 1) := by
  intro h
  have := h 0
  norm_num at this
