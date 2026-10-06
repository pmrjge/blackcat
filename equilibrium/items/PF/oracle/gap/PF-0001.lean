import Mathlib

theorem eq_gap_refutation : ¬ ((5 : ℤ) - 3 * 2 = 1) := by
  norm_num
