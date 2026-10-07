import Mathlib

theorem eq_gap_refutation : ¬ ((3 : ℚ) * (-2 / (3 - 1)) + -2 = -2 / (3 - 1)) := by
  norm_num
