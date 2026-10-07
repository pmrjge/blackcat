import Mathlib

theorem eq_gap_refutation : ¬ ((3 : ℝ) * (12 / 3) + 12 / (12 / 3) = 12) := by
  norm_num
