import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) ^ 2 - 4 ^ 1 = 5) := by
  norm_num
