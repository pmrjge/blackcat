import Mathlib

theorem eq_gap_refutation : ¬ ((3 : ℚ) * (4 / (3 - 1)) + 4 = 4 / (3 - 1)) := by
  norm_num
