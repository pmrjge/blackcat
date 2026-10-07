import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) ^ 2 - 3 ^ 2 = -10) := by
  norm_num
