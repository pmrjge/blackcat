import Mathlib

theorem eq_gap_refutation : ¬ ((4 : ℤ) ^ 1 - 2 ^ 2 = 5) := by
  norm_num
