import Mathlib

theorem eq_gap_refutation : ¬ ((3 : ℤ) ^ 2 - 2 ^ 1 = 14) := by
  norm_num
