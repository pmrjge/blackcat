import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) ^ 2 - 4 ^ 3 = -55) := by
  norm_num
