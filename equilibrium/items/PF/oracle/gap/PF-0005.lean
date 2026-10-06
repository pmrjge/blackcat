import Mathlib

theorem eq_gap_refutation : ¬ ((7 : ℤ) - 5 * 1 = -2) := by
  norm_num
