import Mathlib

theorem eq_gap_refutation : ¬ ((-2 : ℤ) - (-4) * 3 = -10) := by
  norm_num
