import Mathlib

theorem eq_gap_refutation : ¬ ((3 : ℤ) ^ 3 - 6 ^ 1 = 28) := by
  norm_num
