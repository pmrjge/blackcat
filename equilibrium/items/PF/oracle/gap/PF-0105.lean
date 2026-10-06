import Mathlib

theorem eq_gap_refutation : ¬ ((2 : ℝ) * (8 / 2) + 8 / (8 / 2) = 8) := by
  norm_num
