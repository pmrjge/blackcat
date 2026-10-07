import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, 15 * (20 * n + 3) - 20 * (15 * n + 2) = 1) := by
  intro h
  have := h 0
  norm_num at this
