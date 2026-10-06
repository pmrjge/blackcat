import Mathlib

theorem eq_gap_refutation : ¬ ((-4 : ℤ) - (-3) * 3 = -5) := by
  norm_num
