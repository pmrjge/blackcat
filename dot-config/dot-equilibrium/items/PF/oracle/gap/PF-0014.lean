import Mathlib

theorem eq_gap_refutation : ¬ ((5 : ℤ) - 4 * 3 = 7) := by
  norm_num
