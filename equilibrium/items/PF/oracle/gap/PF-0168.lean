import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) ^ 3 - 3 ^ 1 = 10) := by
  norm_num
