import Mathlib

theorem eq_gap_refutation : ¬ ((4 : ℝ) * (25 / 4) + 25 / (25 / 4) = 20) := by
  norm_num
