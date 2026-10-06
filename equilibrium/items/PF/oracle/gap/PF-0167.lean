import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) ^ 1 - 3 ^ 3 = -20) := by
  norm_num
