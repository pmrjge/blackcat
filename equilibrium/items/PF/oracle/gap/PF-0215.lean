import Mathlib

theorem eq_gap_refutation : ¬ ((6 : ℚ) * (10 / (6 - 1)) + 10 = 10 / (6 - 1)) := by
  norm_num
