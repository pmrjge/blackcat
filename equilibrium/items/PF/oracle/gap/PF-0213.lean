import Mathlib

theorem eq_gap_refutation : ¬ ((5 : ℚ) * (-8 / (5 - 1)) + -8 = -8 / (5 - 1)) := by
  norm_num
