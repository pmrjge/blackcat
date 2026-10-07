import Mathlib

theorem eq_gap_refutation : ¬ ((6 : ℤ) ^ 1 - 3 ^ 3 = -14) := by
  norm_num
