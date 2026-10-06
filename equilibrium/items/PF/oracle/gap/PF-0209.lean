import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℚ) * (1 / (2 - 1)) + 1 = 1 / (2 - 1)) := by
  norm_num
