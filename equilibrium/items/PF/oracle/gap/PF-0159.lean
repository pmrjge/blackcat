import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) ^ 2 - 5 ^ 2 = -14) := by
  norm_num
