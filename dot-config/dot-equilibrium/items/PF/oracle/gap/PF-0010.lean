import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℤ) - (-3) * 2 = -8) := by
  norm_num
