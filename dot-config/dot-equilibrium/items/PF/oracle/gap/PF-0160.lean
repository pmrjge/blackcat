import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) ^ 3 - 6 ^ 2 = -21) := by
  norm_num
