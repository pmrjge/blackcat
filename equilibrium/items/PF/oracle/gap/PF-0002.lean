import Mathlib

theorem eq_gap_refutation : ¬ ((7 : ℤ) - (-1) * 1 = -8) := by
  norm_num
