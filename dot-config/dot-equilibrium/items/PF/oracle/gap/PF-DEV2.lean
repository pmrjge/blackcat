import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) ^ 1 - 3 ^ 2 = -14) := by
  norm_num
