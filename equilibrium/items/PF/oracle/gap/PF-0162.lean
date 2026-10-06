import Mathlib

theorem eq_gap_refutation : ¬ ((3 : ℤ) ^ 3 - 5 ^ 3 = -91) := by
  norm_num
