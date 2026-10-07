import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℚ) * (3 / (2 - 1)) + 3 = 3 / (2 - 1)) := by
  norm_num
