import Mathlib

theorem eq_gap_refutation : ¬ ((4 : ℚ) * (6 / (4 - 1)) + 6 = 6 / (4 - 1)) := by
  norm_num
